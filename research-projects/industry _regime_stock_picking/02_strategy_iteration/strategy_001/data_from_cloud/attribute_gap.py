"""绩效差异归因：区间 / regime / 池。

1. **区间**：云端 2015-05 起、本地 2016-12 起。按年汇总云端平仓盈亏，看被本地切掉的那段占多少。
2. **regime**：从云端成交反推它当期用的是动量还是反转（看买入行业命中哪条 top3），
   与本地变盘指数 T′ 的判定对比。
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
PROJ = ROOT / "research-projects/industry _regime_stock_picking"
TOP_IND, MOM_W, REV_W = 3, 240, 60
LOCAL_START = pd.Timestamp("2016-12-23")     # 本地 baseline 首个信号 exec 日


def parse_pnl(s):
    if not isinstance(s, str) or "/" not in s:
        return np.nan
    try:
        return float(s.split("/")[0].strip())
    except ValueError:
        return np.nan


def load_cloud():
    tr = pd.read_csv(HERE / "csv.csv", encoding="utf-8-sig")
    tr.columns = ["date", "time", "symbol", "name", "side", "qty", "price",
                  "amount", "pnl", "fee", "type"]
    tr["date"] = pd.to_datetime(tr["date"])
    tr["pnl_amt"] = tr["pnl"].apply(parse_pnl)
    return tr


def industry_series():
    ind = pd.read_parquet(PROJ / "shared/_cache/industry_index.parquet")
    SW = {"农林牧渔": "801010", "基础化工": "801030", "钢铁": "801040", "有色金属": "801050",
          "电子": "801080", "汽车": "801880", "家用电器": "801110", "食品饮料": "801120",
          "纺织服饰": "801130", "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160",
          "交通运输": "801170", "房地产": "801180", "商贸零售": "801200", "社会服务": "801210",
          "银行": "801780", "非银金融": "801790", "综合": "801230", "建筑材料": "801710",
          "建筑装饰": "801720", "电力设备": "801730", "机械设备": "801890", "国防军工": "801740",
          "计算机": "801750", "传媒": "801760", "通信": "801770", "煤炭": "801950",
          "石油石化": "801960", "环保": "801970", "美容护理": "801980"}
    ind["ind_name"] = ind["ind_code"].map({v: k for k, v in SW.items()})
    return ind.pivot(index="date", columns="ind_name", values="close").sort_index()


def cloud_industry_picks(tr):
    buy = tr[tr["side"] == "买入"][["date", "symbol"]]
    con = duckdb.connect(str(WH), read_only=True)
    inl = ",".join(repr(s) for s in sorted(buy["symbol"].unique()))
    si = con.execute(f"""SELECT instrument AS symbol, date, industry_level1_name AS ind
                         FROM stock_industry_component_daily WHERE instrument IN ({inl})""").fetchdf()
    con.close()
    si["date"] = pd.to_datetime(si["date"])
    buy = buy.merge(si, on=["symbol", "date"], how="left").dropna(subset=["ind"])
    return buy.groupby("date")["ind"].apply(frozenset)


def main():
    tr = load_cloud()
    sells = tr[tr["pnl_amt"].notna()]

    # ── ① 区间 ──
    by_year = sells.groupby(sells["date"].dt.year)["pnl_amt"].sum()
    tot = by_year.sum()
    cut = by_year[by_year.index < LOCAL_START.year].sum()
    before = sells[sells["date"] < LOCAL_START]
    print("=== ① 区间：云端平仓盈亏分年（元）===")
    for y, v in by_year.items():
        mark = "  ← 本地回测未覆盖" if y < LOCAL_START.year else ""
        print(f"  {y}: {v:>12,.0f}  ({v/tot:>5.1%}){mark}")
    print(f"  合计 {tot:,.0f}；本地起点({LOCAL_START.date()})之前占 "
          f"{cut:,.0f} ({cut/tot:.1%})，{len(before)} 笔")
    y2015 = before[before["date"].dt.year == 2015]
    print(f"    其中 2015 年 {len(y2015)} 笔 / {y2015['pnl_amt'].sum():,.0f} 元；"
          f"2016 年 {len(before[before['date'].dt.year==2016])} 笔 / "
          f"{before[before['date'].dt.year==2016]['pnl_amt'].sum():,.0f} 元")

    # ── ② regime ──
    px = industry_series()
    mom = px / px.shift(MOM_W) - 1
    rev = px / px.shift(REV_W) - 1
    picks = cloud_industry_picks(tr)
    plan = pd.read_parquet(PROJ / "shared/_cache/weekly_plan.parquet")
    plan["exec_date"] = pd.to_datetime(plan["exec_date"])
    local_reg = plan.set_index("exec_date")["regime"]

    rows = []
    for d, cloud_set in picks.items():
        if len(cloud_set) != TOP_IND:
            continue
        prior = px.index[px.index < d]
        if len(prior) == 0:
            continue
        sd = prior[-1]
        m, r = mom.loc[sd].dropna(), rev.loc[sd].dropna()
        if len(m) < TOP_IND or len(r) < TOP_IND:
            continue
        hit_m = len(cloud_set & set(m.nlargest(TOP_IND).index))
        hit_r = len(cloud_set & set(r.nsmallest(TOP_IND).index))
        cloud_reg = "momentum" if hit_m > hit_r else ("reversal" if hit_r > hit_m else "?")
        rows.append({"exec_date": d, "cloud_regime": cloud_reg,
                     "hit_m": hit_m, "hit_r": hit_r,
                     "local_regime": local_reg.get(d, None)})
    rr = pd.DataFrame(rows).dropna(subset=["local_regime"])
    rr = rr[rr["cloud_regime"] != "?"]
    agree = (rr["cloud_regime"] == rr["local_regime"]).mean()
    print(f"\n=== ② regime 判定：云端(反推) vs 本地(变盘指数 T′) ===")
    print(f"  可比 {len(rr)} 天    一致率 {agree:.1%}")
    print(pd.crosstab(rr["cloud_regime"], rr["local_regime"]).to_string())
    print(f"\n  云端 regime 分布: {rr['cloud_regime'].value_counts().to_dict()}")
    print(f"  本地 regime 分布: {rr['local_regime'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
