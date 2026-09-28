"""全市场个股缺口终版拉取（2026-09-28 第三批）—— 逐月抽样枚举 + 补拉。

背景：四指数并集已 100%；上午已用「年度抽样」(12 日) 拉过 464 只非指数股。
本脚本用**逐月抽样**（≈140 个月末日）从 cn_stock_bar1d 本尊枚举 2015 至今全部在市过
的证券（比年度抽样严谨——不漏「上市+退市落在同一年内」的短命股），再补拉本地缺口。

表口径：cn_stock_bar1d（个股后复权日线，16 定义列，与本地 stock_bar1d 完全一致）。
（注意：cn_stock_index_bar1d 是**指数**日线表，不含个股，勿混用。）

BJ 处理：920 新代码系列有数据（本地已 49 只），一并补；83x/43x 老代码无数据
（返回空，无害）。若不需要 BJ 用 --no-bj 跳过。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
TABLE = "stock_bar1d"
SOURCE = "cn_stock_bar1d"
BATCH = 100
CKPT = ROOT / "_pull_fullmarket_ckpt.json"
START, END = "2015-01-01", "2026-08-24"

COLS = ["date", "instrument", "name", "adjust_factor", "pre_close", "open", "close", "high",
        "low", "volume", "deal_number", "amount", "change_ratio", "turn", "upper_limit", "lower_limit"]


def month_last_trading_days() -> list[str]:
    """每月最后一个**真实交易日**（从本地 stock_bar1d 取，避免单日抽样撞上休市空分区）。

    ★ fetchall 返回**元组列表**——必须解包 r[0]！上次没解包，str((Timestamp,))[:10]
      产出 "(datetime." 这种脏串，被当成过滤值传给云端，连环触发三种"服务端错误"
      （cast 失败 / Comparison on NULL），排查了三轮才发现是本地 bug。
    """
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    days = [str(r[0])[:10] for r in con.execute(
        "SELECT DISTINCT date FROM stock_bar1d ORDER BY 1").fetchall()]
    con.close()
    by_month: dict[str, str] = {}
    for d in days:
        by_month[d[:7]] = d                  # 同月后值覆盖前值 → 月内最后交易日
    return [by_month[m] for m in sorted(by_month)]


def fetch_universe(no_bj: bool) -> list[str]:
    """逐月单日 DISTINCT instrument 并集。

    ★ 配额口径：单日 filters [d,d] 只扫当日分区 → 每日 ~4500-5500 只 × 1 列；
      140 个月总计 ≈ 0.7M 单元格（区间式 DISTINCT 会扫整段日期，一批 12 个月就要 1.3M+，勿用）。
    """
    from bigquant import dai
    allc: set[str] = set()
    dates = month_last_trading_days()
    print(f"  抽样 {len(dates)} 个月末交易日（{dates[0]} ~ {dates[-1]}）")
    for k, d in enumerate(dates):
        # ★ 枚举全市场用 cn_stock_prefactors + 单日 filters（今早 12 日抽样验证可用）。
        #   cn_stock_bar1d 上 "SELECT DISTINCT instrument + 纯日期过滤" 会触发服务端
        #   BigDB 分区裁剪崩溃（Comparison on NULL values，等值/区间写法都崩）——
        #   该表只有配合 instrument IN 过滤才正常（今早两批拉取均如此）。
        df = dai.query("SELECT DISTINCT instrument FROM cn_stock_prefactors",
                       filters={"date": [d, d]}).df()
        allc |= set(df["instrument"])
        if (k + 1) % 24 == 0:
            print(f"    {k+1}/{len(dates)} 个月，累计并集 {len(allc)}")
    if no_bj:
        allc = {s for s in allc if not s.endswith(".BJ")}
    return sorted(allc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-bj", action="store_true", help="跳过北交所")
    a = ap.parse_args()

    print("① 逐月枚举全市场（cn_stock_bar1d 本尊）：")
    universe = fetch_universe(a.no_bj)
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    bar = {x[0] for x in con.execute("SELECT DISTINCT instrument FROM stock_bar1d").fetchall()}
    con.close()
    gap = [s for s in universe if s not in bar]
    sfx = pd.Series(gap).str.split(".").str[1].value_counts().to_dict() if gap else {}
    print(f"\n② 全市场 {len(universe)} 只（本地已有 {len(universe) - len(gap)}），缺口 {len(gap)}，分布 {sfx}")

    est_rows = int(len(gap) * 2860 * 0.5)
    print(f"③ 估算：~{est_rows:,} 行 × 16 列 ≈ {est_rows*16/1e6:.1f}M 单元格")
    if a.dry_run:
        print("（--dry-run 到此为止）")
        return

    done = json.loads(CKPT.read_text()) if CKPT.exists() else []
    done_set = set(done)
    todo = [s for s in gap if s not in done_set]
    print(f"④ 待拉 {len(todo)} 只（断点已完成 {len(done_set & set(gap))}）")
    total = 0
    from bigquant import dai
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        t0 = time.time()
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
            print(f"  批 {i//BATCH+1} 三次失败，断点已存，重跑续传")
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
