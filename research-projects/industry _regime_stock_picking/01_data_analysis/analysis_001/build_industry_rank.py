"""analysis_001 补充预计算 —— 优先级 6.1 需要「股票所属行业的收益率排名」。

产出（`_precomputed/`）：
  ind_ret_rank.parquet   (date, p2, ret, rank)      申万一级 31 行业 × 日频
                         ret  = trailing-20 交易日收益率（研报"月度"口径的日频版）
                         rank = 当日截面排名，**1 = 收益率最高**（优先级 6.1 用）
  stock_industry.parquet (symbol, date, p2)         668 只个股的 asof 一级行业归属

独立重算，不复用 hs300-enh 的任何产物。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
OUT = HERE / "_precomputed"
OUT.mkdir(parents=True, exist_ok=True)

INDEX_CODE = "000300.SH"
START, END = "2015-01-05", "2026-08-21"
RET_WIN = 20                      # 行业收益率窗口（交易日）


def main():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)

    # ── 行业指数日线（sw2021 一级 31 个，2 位前缀聚合）──
    pre = con.execute("""SELECT DISTINCT substr(industry_instrument,1,2) AS p2
                         FROM stock_industry_component WHERE industry='sw2021'""").df()
    plist = "','".join(sorted(pre["p2"]))
    ind = con.execute(f"""SELECT substr(instrument,1,2) AS p2, date, avg(change_ratio) AS chg
                          FROM stock_industry_bar1d
                          WHERE substr(instrument,1,2) IN ('{plist}')
                            AND date >= '{START}' AND date <= '{END}'
                          GROUP BY 1, 2 ORDER BY 1, 2""").df()

    # ── 个股 asof 一级行业归属（只留沪深300 成分股）──
    mem = [r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument='{INDEX_CODE}'").fetchall()]
    inl = ",".join(f"'{s}'" for s in mem)
    si = con.execute(f"""SELECT instrument AS symbol, date,
                                substr(industry_instrument,1,2) AS p2
                         FROM stock_industry_component_daily
                         WHERE instrument IN ({inl})""").df()
    con.close()

    ind["date"] = pd.to_datetime(ind["date"])
    si["date"] = pd.to_datetime(si["date"])
    si = si.drop_duplicates(["symbol", "date"])

    # ── trailing-20 收益率 + 当日截面排名 ──
    piv = ind.pivot(index="date", columns="p2", values="chg").sort_index()
    cum = np.log1p(piv.fillna(0)).cumsum()
    ret = np.expm1(cum - cum.shift(RET_WIN))
    rk = ret.rank(axis=1, ascending=False)                    # 1 = 收益率最高
    long = (ret.stack().rename("ret").to_frame()
            .join(rk.stack().rename("rank"))
            .reset_index().rename(columns={"level_0": "date", "level_1": "p2"}))
    long = long.dropna(subset=["ret"])
    long.to_parquet(OUT / "ind_ret_rank.parquet", index=False)
    print(f"ind_ret_rank: {len(long):,} 行 / {long.p2.nunique()} 行业 / "
          f"{long.date.min().date()} ~ {long.date.max().date()}")

    si.to_parquet(OUT / "stock_industry.parquet", index=False)
    print(f"stock_industry: {len(si):,} 行 / {si.symbol.nunique()} 只 / {si.p2.nunique()} 个一级行业")


if __name__ == "__main__":
    main()
