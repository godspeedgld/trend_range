"""量化「股票池差异」对绩效的贡献。

云端用全市场（`cn_stock_prefactors`），本地池 = 当期 HS300∪CSI500∪CSI1000 成分。
云端交易的 562 只里有 222 只**本地根本没有行情**（占云端成交额 43.3%）。

本脚本用云端成交记录自带的 `平仓盈亏` 字段（形如 "68158.59 / 8.67%"），
按「本地是否覆盖该股」分组对比**云端已实现收益**，直接量化漏掉那部分的影响。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
WH = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"


def parse_pnl(s):
    """'68158.59 / 8.67%' → (金额, 收益率%)"""
    if not isinstance(s, str) or "/" not in s:
        return np.nan, np.nan
    a, b = s.split("/")
    try:
        return float(a.strip()), float(b.strip().rstrip("%"))
    except ValueError:
        return np.nan, np.nan


def main():
    tr = pd.read_csv(HERE / "csv.csv", encoding="utf-8-sig")
    tr.columns = ["date", "time", "symbol", "name", "side", "qty", "price",
                  "amount", "pnl", "fee", "type"]
    tr["date"] = pd.to_datetime(tr["date"])
    tr[["pnl_amt", "pnl_pct"]] = tr["pnl"].apply(lambda x: pd.Series(parse_pnl(x)))

    sells = tr[tr["pnl_amt"].notna()].copy()
    n_sell = int((tr["side"] == "卖出").sum())
    print(f"卖出记录 {n_sell} 笔，其中可解析平仓盈亏 {len(sells)} 笔")

    con = duckdb.connect(str(WH), read_only=True)
    local = set(r[0] for r in con.execute(
        "SELECT DISTINCT instrument FROM stock_bar1d").fetchall())
    con.close()
    sells["in_local"] = sells["symbol"].isin(local)
    print(f"  本地覆盖 {int(sells['in_local'].sum())} 笔 / 本地缺失 {int((~sells['in_local']).sum())} 笔")

    print("\n=== 云端已实现平仓收益：本地覆盖 vs 本地缺失 ===")
    g = sells.groupby("in_local")["pnl_pct"].agg(
        笔数="count", 平均收益="mean", 中位收益="median", 胜率=lambda s: (s > 0).mean())
    g.index = ["本地缺失（云端独有）", "本地覆盖"]
    print(g.round(3).to_string())

    print("\n=== 分年：单笔平均收益(%) 与笔数 ===")
    pv = sells.pivot_table(index=sells["date"].dt.year, columns="in_local",
                           values="pnl_pct", aggfunc="mean").round(2)
    pv.columns = ["本地缺失", "本地覆盖"]
    pv["笔数_缺失"] = sells[~sells["in_local"]].groupby(sells["date"].dt.year).size()
    pv["笔数_覆盖"] = sells[sells["in_local"]].groupby(sells["date"].dt.year).size()
    print(pv.to_string())

    print("\n=== 本地缺失股 TOP10（按云端累计平仓盈亏金额）===")
    m = (sells[~sells["in_local"]].groupby(["symbol", "name"])["pnl_amt"]
         .agg(["sum", "count"]).sort_values("sum", ascending=False).head(10))
    m.columns = ["累计盈亏(元)", "笔数"]
    print(m.round(0).to_string())

    print(f"\n全部平仓盈亏合计 {sells['pnl_amt'].sum():,.0f} 元 "
          f"（本地缺失部分 {sells.loc[~sells['in_local'], 'pnl_amt'].sum():,.0f} 元，"
          f"占 {sells.loc[~sells['in_local'], 'pnl_amt'].sum()/sells['pnl_amt'].sum():.1%}）")


if __name__ == "__main__":
    main()
