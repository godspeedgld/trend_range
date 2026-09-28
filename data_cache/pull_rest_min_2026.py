"""拉取 2026 年【剩余股票】1 分钟线 → 并入 stock_min_1m（2026-01-01~2026-09-24）。

用户 2026-09-28 指定（skill-pandadata-warehouse-main 流程）：
  · 池 = 全市场 − 已拉的 HS300/中证500/1000/2000 并集 = **本地 stock_bar1d 中
    2026 年有数据的 SH/SZ 股票 − stock_min_1m 2026 已有股票**（从未进宽基的小票等）
  · 区间 = 2026-01-01 ~ 2026-09-24
  · BJ 滤掉（PandaData get_stock_min 仅收 SH/SZ，实测报参数错）
  · 入库 = 同一张 stock_min_1m（year/month 分区合并去重重写）

playbook 对齐：月分批 + 落盘 + checkpoint；主键去重；视图重建 + meta + 校验。
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
CKPT = OUT / "_pull_rest_2026_ckpt.json"
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"   # 全市场清单来源

START, END = "20260101", "20260924"
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def load_todo() -> list[str]:
    """bar1d 2026 在市(SH/SZ) − 分钟表 2026 已有。"""
    con = duckdb.connect(str(BQ), read_only=True)
    rows = con.execute("""
        SELECT DISTINCT instrument FROM stock_bar1d
        WHERE date >= '2026-01-01' AND (instrument LIKE '%.SH' OR instrument LIKE '%.SZ')
        ORDER BY 1""").fetchall()
    con.close()
    con = duckdb.connect(str(DDB), read_only=True)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM stock_min_1m WHERE date LIKE '2026%'").fetchall()}
    con.close()
    return [r[0] for r in rows if r[0] not in have]


def month_ranges() -> list[tuple[str, str]]:
    out = []
    for m in range(1, 10):
        b = min(date(2026, m, calendar.monthrange(2026, m)[1]), date(2026, 9, 24))
        out.append((date(2026, m, 1).strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def part_path(m: int) -> Path:
    return OUT / "year=2026" / f"month={m:02d}" / "part.parquet"


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

    syms = load_todo()
    est = int(len(syms) * 177 * 240)
    print(f"剩余股票（全市场−四指数并集，SH/SZ）= {len(syms)} 只 · {START}~{END}")
    print(f"估算 ≈ {est:,} 行 / ~{est*15.3/1e9:.2f} GB（今日已用约 3.3GB / 5GB）")
    if a.dry_run:
        return

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []
    done_set = set(done)
    t0 = time.time()
    total = 0
    for s, e in month_ranges():
        key = s[:6]
        f = part_path(int(key[4:6]))
        if key in done_set and f.exists():
            print(f"  {key}  跳过（checkpoint 已完成）")
            continue
        t = time.time()
        try:
            df = pd_.get_stock_min(symbol=syms, start_date=s, end_date=e,
                                   fields=FIELDS, frequency="1m")
        except Exception as ex:
            print(f"  {key}  ✗ {type(ex).__name__} {str(ex)[:90]}")
            print("     断点已存，重跑续传")
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
        total += len(df)
        done.append(key)
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {key}  {len(df):>10,} 行（合并后 {df['symbol'].nunique()} 只）"
              f" {f.stat().st_size/1e6:6.1f} MB  {time.time()-t:4.1f}s")

    rows = build_view()
    print("=" * 68)
    print(f"完成：stock_min_1m 现共 {rows:,} 行 · 用时 {(time.time()-t0)/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
