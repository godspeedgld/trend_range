"""拉取 2024 年【剩余股票】1 分钟线 → 并入 stock_min_1m（2024-01-01~2024-12-31）→ 2024 全市场。

用户 2026-09-30 指定（skill-pandadata-warehouse-main 流程）：
  · 池 = **本地 stock_bar1d 中 2024 年有数据的全部 SH/SZ 股票**（四指数并集已拉全，
    本批补成分外的小票，把 2024 补成全市场）
  · 区间 = 2024 全年（12 个月）
  · BJ 滤掉（PandaData get_stock_min 仅收 SH/SZ）

★ 断点教训（2026-09-30，同日 csi1000∪2000 脚本踩过）：月分区断点脚本，
  **拉取清单绝不能按"跨月已有股票"裁剪**——"已有"跨月，会把未拉月份的股票整个吃掉；
  且 symbol=[] 行为未定义（可能返回全市场或空）。
  ★ 本脚本的解法 = **逐月算缺口**：每个月的拉取清单 = 该月 bar1d 有交易的 SH/SZ 股 −
  该月分钟分区已有股。已完成月份由 checkpoint 跳过；未完成月份的缺口清单不受其他月完成
  的影响 → 天然断点安全，且不重复传输（10 月已是全市场 → 该月缺口=0 自动跳过）。
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date
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
CKPT = OUT / "_pull_rest_2024_ckpt.json"
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"   # 全市场清单来源

YEAR = 2024
START, END = "20240101", "20241231"
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def month_missing(m: int) -> list[str]:
    """该月缺口：bar1d 当月有交易的 SH/SZ 股 − 分钟表当月已有股。"""
    lo, hi = f"{YEAR}-{m:02d}-01", f"{YEAR}-{m:02d}-{calendar.monthrange(YEAR, m)[1]}"
    bq = duckdb.connect(str(BQ), read_only=True)
    traded = [r[0] for r in bq.execute(f"""
        SELECT DISTINCT instrument FROM stock_bar1d
        WHERE date >= '{lo}' AND date <= '{hi}' AND close IS NOT NULL
          AND (instrument LIKE '%.SH' OR instrument LIKE '%.SZ')""").fetchall()]
    bq.close()
    dw = duckdb.connect(str(DDB), read_only=True)
    have = {r[0] for r in dw.execute(
        f"SELECT DISTINCT symbol FROM {TABLE} WHERE year='{YEAR}' AND month='{m:02d}'").fetchall()}
    dw.close()
    return [s for s in traded if s not in have]


def month_ranges() -> list[tuple[str, str]]:
    out = []
    for m in range(1, 13):
        b = date(YEAR, m, calendar.monthrange(YEAR, m)[1])
        out.append((date(YEAR, m, 1).strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def part_path(m: int) -> Path:
    return OUT / f"year={YEAR}" / f"month={m:02d}" / "part.parquet"


def build_view() -> int:
    con = duckdb.connect(str(DDB))
    glob = str(OUT / "year=*" / "month=*" / "*.parquet").replace("\\", "/")
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []
    done_set = set(done)
    plan = []
    print(f"{YEAR} 全市场补齐 · 逐月缺口（checkpoint 已完成 {len(done_set)}/12 月）：")
    total_est = 0
    for s, e in month_ranges():
        m = int(s[4:6])
        if s[:6] in done_set and part_path(m).exists():
            print(f"  {s[:6]}  跳过（checkpoint）")
            continue
        miss = month_missing(m)
        est = len(miss) * 21 * 240
        total_est += est
        plan.append((s, e, miss))
        print(f"  {s[:6]}  缺口 {len(miss):>5} 只 ≈ {est:>9,} 行")
    print(f"合计待拉 ≈ {total_est:,} 行 / ~{total_est * 15.3 / 1e9:.2f} GB")
    if a.dry_run:
        return

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    t0 = time.time()
    for s, e, miss in plan:
        key, m = s[:6], int(s[4:6])
        f = part_path(m)
        if not miss:
            print(f"  {key}  缺口=0，跳过")
            done.append(key)
            CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
            continue
        t = time.time()
        try:
            df = pd_.get_stock_min(symbol=miss, start_date=s, end_date=e,
                                   fields=FIELDS, frequency="1m")
        except Exception as ex:
            print(f"  {key}  ✗ {type(ex).__name__} {str(ex)[:90]}")
            print("     断点已存，重跑续传（逐月缺口，续传安全）")
            return 1
        if df is None or not len(df):
            print(f"  {key}  — 无数据")
            continue
        df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            old = pd.read_parquet(f)
            df = pd.concat([old, df], ignore_index=True)
            df = df.drop_duplicates(subset=["symbol", "date", "minute"], keep="last")
            df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
        done.append(key)
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {key}  +{len(df):>9,} 行（拉 {len(miss)} 只，合并后 {df['symbol'].nunique()} 只）"
              f" {f.stat().st_size / 1e6:6.1f} MB  {time.time() - t:4.1f}s")

    rows = build_view()
    print("=" * 68)
    print(f"完成：stock_min_1m 现共 {rows:,} 行 · 用时 {(time.time() - t0) / 60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
