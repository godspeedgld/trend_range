"""拉取沪深【非指数缺口】股票日线 → 入库 stock_bar1d（用户计划第二批，2026-09-28）。

背景：四指数并集已入库（5034 只，沪深全市场覆盖 100%——按 sw2021 行业归属口径），
但云端策略用的 cn_stock_prefactors 全市场还含「从未进过任何宽基指数」的小票
（云端对账：仍缺 62 只 = 51 沪深非指数 + 11 北交所，占云端平仓盈亏 5.1%）。

本脚本：
  ① 从云端 cn_stock_prefactors 抽样多个日期取 DISTINCT instrument → 全市场清单
     （配额极小：12 日 × ~5500 只 × 1 列 ≈ 66K 单元格）
  ② 缺口 = 全市场(SH/SZ) − 已入库；BJ 无法从 cn_stock_bar1d 拉（源表不含，已证）
  ③ 估算单元格量并打印（配额铁律：拉前先估）
  ④ 分批 100 只 + 断点续拉，显式 16 列（data_tables.md cn_stock_bar1d 定义列）

用法：直接运行。--dry-run 只算缺口不拉。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent          # data_cache/bigquant_warehouse
TABLE = "stock_bar1d"
SOURCE = "cn_stock_bar1d"
BATCH = 100
CKPT = ROOT / "_pull_nonindex_ckpt.json"
START, END = "2015-01-01", "2026-08-24"

COLS = ["date", "instrument", "name", "adjust_factor", "pre_close", "open", "close", "high",
        "low", "volume", "deal_number", "amount", "change_ratio", "turn", "upper_limit", "lower_limit"]

# 抽样日：每年 1 个 7 月首交易日附近 + 2026 最新，兼顾「上市又退市」的短命股
SAMPLE_DATES = ["2015-07-01", "2016-07-01", "2017-07-03", "2018-07-02", "2019-07-01",
                "2020-07-01", "2021-07-01", "2022-07-01", "2023-07-03", "2024-07-01",
                "2025-07-01", "2026-07-01"]


def fetch_universe() -> list[str]:
    """云端全市场清单（多日抽样并集，仅 SH/SZ）。"""
    from bigquant import dai
    allc: set[str] = set()
    for d in SAMPLE_DATES:
        df = dai.query("SELECT DISTINCT instrument FROM cn_stock_prefactors",
                       filters={"date": [d, d]}).df()
        allc |= set(df["instrument"])
        print(f"  {d}: {len(df):>5} 只（累计并集 {len(allc)}）")
    # 只留沪深（BJ 走不了 cn_stock_bar1d，已证源表不含）
    return sorted(s for s in allc if s.endswith((".SH", ".SZ")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只算缺口与配额估算，不拉")
    a = ap.parse_args()

    print("① 云端全市场抽样（SH/SZ）：")
    universe = fetch_universe()

    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    bar = {x[0] for x in con.execute("SELECT DISTINCT instrument FROM stock_bar1d").fetchall()}
    con.close()
    gap = [s for s in universe if s not in bar]
    bj_dropped = None
    print(f"\n② 全市场(SH/SZ) {len(universe)} 只，已入库 {len(universe) - len(gap)}，缺口 {len(gap)}")

    est_rows = int(len(gap) * 2860 * 0.55)   # 非指数小票多为次新/短命，按 55% 满窗估
    est_cells = est_rows * len(COLS)
    print(f"③ 估算：~{est_rows:,} 行 × {len(COLS)} 列 ≈ {est_cells/1e6:.1f}M 单元格")
    if a.dry_run:
        print("（--dry-run，到此为止）")
        return

    done = json.loads(CKPT.read_text()) if CKPT.exists() else []
    done_set = set(done)
    todo = [s for s in gap if s not in done_set]
    print(f"④ 待拉 {len(todo)} 只（断点已完成 {len(done_set & set(gap))}）· {START}~{END}")
    total = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        t0 = time.time()
        from bigquant import dai
        in_list = ",".join(f"'{s}'" for s in batch)
        sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
               f"WHERE instrument IN ({in_list}) AND date >= '{START}' AND date <= '{END}'")
        df = None
        for attempt in range(3):
            try:
                df = dai.query(sql).df()[COLS]
                break
            except Exception as e:
                print(f"    重试 {attempt+1}/3: {str(e)[:100]}")
                time.sleep(5)
        if df is None:
            print(f"  批 {i//BATCH+1} 三次失败，断点已存，配额恢复后重跑续传")
            break
        if len(df):
            d2 = df.copy()
            d2["year"] = pd.to_datetime(d2["date"]).dt.year
            for year, grp in d2.groupby("year"):
                out = ROOT / TABLE / f"year={int(year)}" / "part.parquet"
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists():
                    old = pd.read_parquet(out)
                    grp = pd.concat([old, grp], ignore_index=True)
                grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
                grp.to_parquet(out, index=False)
            total += len(df)
        done.extend(batch)
        CKPT.write_text(json.dumps(done, ensure_ascii=False))
        print(f"  批 {i//BATCH+1:>2}: {len(batch)} 只 → {len(df):>7,} 行  累计 {total:>9,}  ({time.time()-t0:.0f}s)")

    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n_syms, n_rows, d0, d1 = con.execute(
        f"SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM {TABLE}").fetchone()
    dup = con.execute(f"SELECT count(*) FROM (SELECT instrument, date, count(*) c "
                      f"FROM {TABLE} GROUP BY 1,2 HAVING c > 1)").fetchone()[0]
    con.close()
    print(f"\n完成：stock_bar1d 现有 {n_syms} 只 / {n_rows:,} 行 / {str(d0)[:10]}~{str(d1)[:10]}"
          f"（本次 +{total:,} 行）· 主键重复 {dup} {'OK' if dup == 0 else 'FAIL'}")


if __name__ == "__main__":
    main()
