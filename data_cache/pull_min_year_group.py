"""按【年份 + 分组】补齐 stock_min_1m —— 逐月缺口法，断点安全，支持指定补齐顺序。

补齐顺序（用户指定，`--group all` 按此序连跑）：
    沪深300 → 中证500 → 中证1000 → 中证2000 → 其他(rest)
（2026-09-30 首次用于 2023 时是「中证1000/2000」合并一组；2026-10-09 按用户要求拆成两组独立排序。）

为什么用分组跑（而不是一个脚本全市场一把梭）：PandaData 有**单日 5GB 流量上限**
（错误码 500009）。按重要性分组、逐组跑 → 万一当天额度用尽，**重要的指数组已经完整**，
剩下的次日续传即可。

★ 逐月缺口法（2026-09-30 沉淀，月分区断点的正解）：
    某月拉取清单 = 该组符号 ∩ (bar1d 当月有交易) − 分钟表当月已有
  · 断点安全：某月完成不影响他月缺口（对比：跨月"已有"裁剪会吃掉未拉月份）
  · 零重复传输：当月已完整的组缺口=0，自动跳过
  · 自然排除停牌/未上市/已退市（bar1d 当月无成交即不在清单）

用法：
    python pull_min_year_group.py --year 2023 --group hs300            [--dry-run]
    python pull_min_year_group.py --year 2023 --group csi500
    python pull_min_year_group.py --year 2023 --group csi1000
    python pull_min_year_group.py --year 2023 --group csi2000
    python pull_min_year_group.py --year 2023 --group rest
    python pull_min_year_group.py --year 2023 --group all     # 上面五组按序连跑

产物：并入同一张 stock_min_1m（year=YYYY/month=MM 分区合并去重）→ 重建视图 → 更新 _meta.json
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
SKILL = REPO / ".claude/skills/skill-pandadata-api-main/scripts"
sys.path.insert(0, str(SKILL))

WAREHOUSE = HERE / "pandadata_warehouse"
TABLE = "stock_min_1m"
OUT = WAREHOUSE / TABLE
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"   # 成分/全市场清单来源

FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000

# 分组定义 + 用户指定的补齐顺序（all 按此序连跑）
GROUPS = {
    "hs300":    ("沪深300",    "instrument = '000300.SH'"),
    "csi500":   ("中证500",    "instrument = '000905.SH'"),
    "csi1000":  ("中证1000",   "instrument = '000852.SH'"),
    "csi2000":  ("中证2000",   "instrument = '932000.CSI'"),
    "rest":     ("其他(rest)", None),        # 全市场 − 上面四组
}
# ★ 2026-10-09 拆分：原 "csi1000csi2000" 合并组按用户要求拆成 csi1000 / csi2000 两组独立排序。
#   注意 932000.CSI（中证2000）2023-08 才发布 → **2023 年以前该组当年并集为空**，
#   那几年的符号全部落进 rest（rest 定义不受影响：过去减 1 个并集组、现在减 2 个，结果相同）。
ORDER = ["hs300", "csi500", "csi1000", "csi2000", "rest"]


def group_symbols(group: str, year: int) -> set[str]:
    """该组当年成分并集（SH/SZ）；rest = bar1d 全年在市 − 三指数并集。"""
    bq = duckdb.connect(str(BQ), read_only=True)
    def idx_syms(where):
        return {r[0] for r in bq.execute(f"""
            SELECT DISTINCT member_code FROM index_component
            WHERE {where} AND TRY_CAST(date AS VARCHAR) LIKE '{year}%'
              AND (member_code LIKE '%.SH' OR member_code LIKE '%.SZ')""").fetchall()}
    if group == "rest":
        allm = {r[0] for r in bq.execute(f"""
            SELECT DISTINCT instrument FROM stock_bar1d
            WHERE TRY_CAST(date AS VARCHAR) LIKE '{year}%' AND close IS NOT NULL
              AND (instrument LIKE '%.SH' OR instrument LIKE '%.SZ')""").fetchall()}
        for g in ("hs300", "csi500", "csi1000", "csi2000"):
            allm -= idx_syms(GROUPS[g][1])
        bq.close()
        return allm
    out = idx_syms(GROUPS[group][1])
    bq.close()
    return out


def month_gap(syms: set[str], year: int, m: int) -> list[str]:
    """该月缺口 = syms ∩ (bar1d 当月有交易) − 分钟表当月已有。"""
    lo = f"{year}-{m:02d}-01"
    hi = f"{year}-{m:02d}-{calendar.monthrange(year, m)[1]}"
    bq = duckdb.connect(str(BQ), read_only=True)
    traded = {r[0] for r in bq.execute(f"""
        SELECT DISTINCT instrument FROM stock_bar1d
        WHERE date >= '{lo}' AND date <= '{hi}' AND close IS NOT NULL""").fetchall()}
    bq.close()
    dw = duckdb.connect(str(DDB), read_only=True)
    have = {r[0] for r in dw.execute(
        f"SELECT DISTINCT symbol FROM {TABLE} WHERE year='{year}' AND month='{m:02d}'").fetchall()}
    dw.close()
    return sorted(syms & traded - have)


def part_path(year: int, m: int) -> Path:
    return OUT / f"year={year}" / f"month={m:02d}" / "part.parquet"


def build_view() -> int:
    con = duckdb.connect(str(DDB))
    glob = str(OUT / "year=*" / "month=*" / "*.parquet").replace("\\", "/")
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def run_group(year: int, group: str, dry_run: bool, pd_=None) -> int:
    name = GROUPS[group][0]
    syms = group_symbols(group, year)
    ckpt = OUT / f"_pull_{group}_{year}_ckpt.json"
    done = json.loads(ckpt.read_text(encoding="utf-8")) if ckpt.exists() else []
    done_set = set(done)
    print(f"\n{'='*70}\n【{name}】{year}  ·  该组当年并集 {len(syms)} 只  "
          f"（checkpoint 已完成 {len(done_set)}/12 月）\n{'='*70}")

    plan, total_est = [], 0
    for m in range(1, 13):
        if f"{year}{m:02d}" in done_set and part_path(year, m).exists():
            print(f"  {year}-{m:02d}  跳过（checkpoint）")
            continue
        miss = month_gap(syms, year, m)
        est = len(miss) * 21 * 240
        total_est += est
        plan.append((m, miss))
        print(f"  {year}-{m:02d}  缺口 {len(miss):>5} 只 ≈ {est:>10,} 行")
    print(f"  ── 本组待补 ≈ {total_est:,} 行 / ~{total_est*15.3/1e9:.2f} GB")
    if dry_run or not plan:
        return 0

    spent_rows = 0
    for m, miss in plan:
        key = f"{year}{m:02d}"
        if not miss:
            print(f"  {key}  缺口=0，跳过")
            done.append(key)
            ckpt.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
            continue
        lo = f"{year}{m:02d}01"
        hi = f"{year}{m:02d}{calendar.monthrange(year, m)[1]}"
        t = time.time()
        try:
            df = pd_.get_stock_min(symbol=miss, start_date=lo, end_date=hi,
                                   fields=FIELDS, frequency="1m")
        except Exception as ex:
            print(f"  {key}  ✗ {type(ex).__name__} {str(ex)[:90]}")
            print("     断点已存，重跑续传（逐月缺口，续传安全）")
            return 1
        if df is None or not len(df):
            print(f"  {key}  — 无数据")
            continue
        df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        f = part_path(year, m)
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            df = pd.concat([pd.read_parquet(f), df], ignore_index=True)
            df = df.drop_duplicates(subset=["symbol", "date", "minute"], keep="last")
            df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
        spent_rows += len(df)
        done.append(key)
        ckpt.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {key}  拉 {len(miss)} 只 → 合并后 {len(df):>9,} 行 / {df['symbol'].nunique()} 只"
              f"  {f.stat().st_size/1e6:6.1f} MB  {time.time()-t:4.1f}s")
    print(f"  ── 【{name}】完成，本组累计写入 {spent_rows:,} 行")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--group", required=True, choices=list(GROUPS) + ["all"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    groups = ORDER if a.group == "all" else [a.group]
    t0 = time.time()
    pd_ = None
    if not a.dry_run:
        from pandadata_runtime import init_pandadata
        pd_ = init_pandadata()

    for g in groups:
        rc = run_group(a.year, g, a.dry_run, pd_)
        if rc:
            print("\n★ 中止（配额或网络问题）—— 已完成的月份已落盘，次日重跑同命令续传")
            return rc

    if a.dry_run:
        return 0

    rows = build_view()
    print(f"\n{'='*70}\n完成：stock_min_1m 现共 {rows:,} 行 · 用时 {(time.time()-t0)/60:.1f} 分钟")

    # _meta.json 水位 + 逐年覆盖
    dw = duckdb.connect(str(DDB), read_only=True)
    cov = dw.execute(f"""SELECT year AS y, count(DISTINCT symbol) AS n_syms, count(*) AS cnt
        FROM {TABLE} GROUP BY 1 ORDER BY 1""").fetchdf()
    dw.close()
    print(cov.to_string(index=False))
    meta_p = WAREHOUSE / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    t = meta["tables"][TABLE]
    t["row_count"] = rows
    t["last_refresh_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    t["notes"] = (f"{a.year} 按分组补齐（顺序 {'/'.join(groups)}）；逐月缺口法；"
                  f"表总量 {rows:,} 行")
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("_meta.json 已更新")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
