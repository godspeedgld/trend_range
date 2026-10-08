"""补齐 stock_bar1d —— 四指数（沪深300/中证500/中证1000/中证2000）之外的其余股票。

用户 2026-10-08 指定（skill-bigquant-sdk Part 2 流程）：
  · 池 = `cn_stock_basic_info`（标的母表，含退市股）− 四指数成分并集 − 本地 stock_bar1d 已有
  · 列 = **严格按 references/data_tables.md 的 cn_stock_bar1d 定义列**（16 列，不用 SELECT *）
  · 区间 = 2015-01-01 ~ 2026-09-29（与库内其余部分对齐）
  · 入库 = year 分区合并去重（主键 instrument+date）→ 重建视图 → 更新 _meta.json

诊断（2026-10-08 实测）：四指数并集 5,054 只已 100% 覆盖；「四指数之外」应有 879 只，
已覆盖 772，**缺 107 只**（沪 49 / 深 48 / 北 10）。部分为 2015 年前已退市的老代码，
拉取会返回空 —— 属预期（母表含全历史标的，不全是区间内在市股）。

用法：python pull_rest_bar1d.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
TABLE, SOURCE = "stock_bar1d", "cn_stock_bar1d"
START, END = "2015-01-01", "2026-09-29"
BATCH = 40
CKPT = ROOT / "_pull_rest_bar1d_ckpt.json"

# ★ 严格按 data_tables.md 的 cn_stock_bar1d 定义列（16 列），禁 SELECT *
COLS = ["instrument", "date", "name", "open", "high", "low", "close", "pre_close",
        "volume", "amount", "turn", "deal_number", "change_ratio", "adjust_factor",
        "upper_limit", "lower_limit"]
INDEXES = "('000300.SH','000905.SH','000852.SH','932000.CSI')"


def find_gap() -> tuple[list[str], dict]:
    """缺口 = 母表 − 四指数并集 − 本地已有。返回 (缺口清单, 诊断信息)。"""
    from bigquant import dai
    ext = set(dai.query("SELECT instrument FROM cn_stock_basic_info").df()["instrument"])
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    uni = {r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument IN {INDEXES}"
    ).fetchall()}
    loc = {r[0] for r in con.execute(f"SELECT DISTINCT instrument FROM {TABLE}").fetchall()}
    con.close()
    rest = ext - uni
    gap = sorted(rest - loc)
    info = {"母表": len(ext), "四指数并集": len(uni), "四指数之外应有": len(rest),
            "四指数之外已覆盖": len(rest & loc), "缺口": len(gap),
            "缺口在指数内": len([s for s in gap if s in uni])}
    return gap, info


def ingest(df: pd.DataFrame) -> None:
    """按年分区合并去重（主键 instrument+date, keep=last）。"""
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, grp in df.groupby("year"):
        out = ROOT / TABLE / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            grp = pd.concat([pd.read_parquet(out), grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def rebuild_view() -> int:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    gap, info = find_gap()
    print("① 缺口诊断：")
    for k, v in info.items():
        print(f"   {k:<18}{v:>8,}")
    if info["缺口在指数内"]:
        print("   ⚠ 有指数成分落在缺口里 —— 与「指数 100% 覆盖」结论矛盾，需复查")
    print(f"\n② 待拉 {len(gap)} 只 · 16 列 · {START}~{END}")
    est = len(gap) * 2828 * len(COLS)
    print(f"   估算上限 ≈ {est:,} cells（部分为 2015 年前退市的老代码，实际远小于此）")
    if a.dry_run:
        print("（--dry-run 到此为止）")
        return

    from bigquant import dai
    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []
    done_set = set(done)
    todo = [s for s in gap if s not in done_set]
    print(f"   断点续传：已完成 {len(done_set)}，待拉 {len(todo)}")

    t0, total, empty = time.time(), 0, []
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        in_list = ",".join(f"'{s}'" for s in batch)
        sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
               f"WHERE instrument IN ({in_list}) AND date >= '{START}' AND date <= '{END}'")
        df = None
        for attempt in range(3):
            try:
                df = dai.query(sql).df()[COLS]
                break
            except Exception as e:
                print(f"   重试 {attempt+1}/3: {str(e)[:90]}")
                time.sleep(5)
        if df is None:
            print(f"   批 {i//BATCH+1} 三次失败，断点已存，重跑续传")
            break
        if len(df):
            ingest(df)
            total += len(df)
        else:
            empty += batch
        done.extend(batch)
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"   批 {i//BATCH+1:>2}: {len(batch):>3} 只 → {len(df):>8,} 行  累计 {total:>9,}")

    rows = rebuild_view()
    print(f"\n③ 完成：本次 +{total:,} 行；{TABLE} 现共 {rows:,} 行")
    if empty:
        print(f"   {len(empty)} 只在 {START}~{END} 无数据（2015 年前已退市，属预期）")

    # 校验：主键重复 + 缺口复查
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    dup = con.execute(f"""SELECT count(*) FROM (SELECT instrument, date FROM {TABLE}
        GROUP BY 1,2 HAVING count(*) > 1)""").fetchone()[0]
    n_sym = con.execute(f"SELECT count(DISTINCT instrument) FROM {TABLE}").fetchone()[0]
    con.close()
    gap2, info2 = find_gap()
    print(f"   标的数 {n_sym:,} | 主键重复 {dup} {'OK' if dup == 0 else 'FAIL'}")
    print(f"   缺口复查：{info2['缺口']:,} 只（{info['缺口']:,} → {info2['缺口']:,}）")

    meta_p = ROOT / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    t = meta.setdefault("tables", {}).setdefault(TABLE, {})
    t.update({"rows": rows, "symbols": n_sym,
              "last_refresh_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "notes": f"2026-10-08 补齐四指数之外的其余股票：+{total:,} 行；表 {rows:,} 行/{n_sym:,} 只；"
                       f"缺口 {info['缺口']} → {info2['缺口']} 只"})
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n④ {meta_p.name} 已更新")
    print(f"   用时 {(time.time()-t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
