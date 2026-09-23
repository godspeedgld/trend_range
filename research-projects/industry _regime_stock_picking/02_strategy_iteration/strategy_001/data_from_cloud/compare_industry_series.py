"""零配额验证：云端用的行业指数是哪一条？

云端代码用 `cn_stock_prefactors.sw_level1_close` 做变盘指数与行业动量/反转。本地有两条候选：
  A = `stock_industry_sw_bar1d`（801xxx.SWI 官方指数，市值加权）
  B = `stock_industry_bar1d`（784 个叶子行业，按 2 位前缀等权聚合 —— analysis_001 用的口径）

方法：从云端成交记录反推**每个信号日它实际选中的 top3 行业**（买入股的行业归属），
再看 A / B 两条序列中哪一条的「240 日动量 top3」或「60 日反转 top3」更常命中。
命中的那条即为云端口径（同时能反推当时是动量期还是反转期）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]                       # trend_range
CACHE = ROOT / "research-projects/industry _regime_stock_picking/shared/_cache"
WH = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

SW801 = {
    "农林牧渔": "801010", "基础化工": "801030", "钢铁": "801040", "有色金属": "801050",
    "电子": "801080", "汽车": "801880", "家用电器": "801110", "食品饮料": "801120",
    "纺织服饰": "801130", "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160",
    "交通运输": "801170", "房地产": "801180", "商贸零售": "801200", "社会服务": "801210",
    "银行": "801780", "非银金融": "801790", "综合": "801230", "建筑材料": "801710",
    "建筑装饰": "801720", "电力设备": "801730", "机械设备": "801890", "国防军工": "801740",
    "计算机": "801750", "传媒": "801760", "通信": "801770", "煤炭": "801950",
    "石油石化": "801960", "环保": "801970", "美容护理": "801980",
}
TOP_IND, MOM_W, REV_W = 3, 240, 60


def series_A() -> pd.DataFrame:
    """801 官方指数（date × 行业名）。"""
    df = pd.read_parquet(CACHE / "industry_index.parquet")
    df["ind_name"] = df["ind_code"].map({v: k for k, v in SW801.items()})
    return df.pivot(index="date", columns="ind_name", values="close").sort_index()


def series_B() -> pd.DataFrame:
    """784 叶子行业按 2 位前缀等权聚合（date × 行业名）。"""
    con = duckdb.connect(str(WH), read_only=True)
    si = con.execute("""SELECT DISTINCT substr(industry_instrument,1,2) AS p2,
                               industry_level1_name AS name
                        FROM stock_industry_component
                        WHERE industry='sw2021'""").fetchdf()
    plist = "','".join(sorted(si["p2"].unique()))
    close = con.execute(f"""SELECT date, substr(instrument,1,2) AS p2, close
                            FROM stock_industry_bar1d
                            WHERE substr(instrument,1,2) IN ('{plist}')""").fetchdf()
    con.close()
    p2name = dict(zip(si["p2"], si["name"]))
    close["date"] = pd.to_datetime(close["date"])
    # 等权聚合：各叶子行业等权 → 先算各叶子收益再做截面均值，再累乘成价格序列
    px = close.pivot_table(index="date", columns="p2", values="close").sort_index()
    ret = px.pct_change()
    agg = ret.groupby(p2name, axis=1).mean()          # 组内等权
    return (1 + agg.fillna(0)).cumprod()


def cloud_picks() -> pd.Series:
    """云端每个成交日实际买入的行业集合（exec 日 → frozenset）。"""
    tr = pd.read_csv(HERE / "csv.csv", encoding="utf-8-sig")
    tr.columns = ["date", "time", "symbol", "name", "side", "qty", "price",
                  "amount", "pnl", "fee", "type"]
    tr["date"] = pd.to_datetime(tr["date"])
    buy = tr[tr["side"] == "买入"][["date", "symbol"]]
    con = duckdb.connect(str(WH), read_only=True)
    inl = ",".join(repr(s) for s in sorted(buy["symbol"].unique()))
    si = con.execute(f"""SELECT instrument AS symbol, date, industry_level1_name AS ind
                         FROM stock_industry_component_daily WHERE instrument IN ({inl})""").fetchdf()
    con.close()
    si["date"] = pd.to_datetime(si["date"])
    buy = buy.merge(si, on=["symbol", "date"], how="left").dropna(subset=["ind"])
    return buy.groupby("date")["ind"].apply(frozenset)


def hit_rate(px: pd.DataFrame, picks_union: pd.Series, picks_by_date: pd.Series):
    """两条策略（动量 top3 / 反转 top3）各自对云端实际行业的命中率。"""
    mom = px / px.shift(MOM_W) - 1
    rev = px / px.shift(REV_W) - 1
    rows = []
    for d, inds_cloud in picks_by_date.items():
        # 成交日 d 对应信号日 = 上一交易日
        prior = px.index[px.index < d]
        if len(prior) == 0:
            continue
        sd = prior[-1]
        m = mom.loc[sd].dropna()
        r = rev.loc[sd].dropna()
        if len(m) < TOP_IND or len(r) < TOP_IND:
            continue
        set_m = set(m.nlargest(TOP_IND).index)                 # 动量：强者恒强
        set_r = set(r.nsmallest(TOP_IND).index)                # 反转：60 日跌得多
        rows.append({"exec_date": d, "n_cloud": len(inds_cloud),
                     "mom_hit": len(inds_cloud & set_m),
                     "rev_hit": len(inds_cloud & set_r)})
    r = pd.DataFrame(rows)
    # 只保留云端行业数 == 3 的干净样本（映射失败的日子行业数 <3）
    clean = r[r["n_cloud"] == TOP_IND]
    return r, clean


def main():
    A, B = series_A(), series_B()
    cp = cloud_picks()
    print(f"云端可反推的成交日 {len(cp)} 天（行业映射成功）\n")

    for tag, px in [("A = 801 官方指数(市值加权)", A), ("B = 784叶子按前缀等权聚合", B)]:
        allr, clean = hit_rate(px, cp, cp)
        # top3 完全命中的比例
        full_m = (clean["mom_hit"] == 3).mean()
        full_r = (clean["rev_hit"] == 3).mean()
        print(f"{tag}")
        print(f"  干净样本 {len(clean)} 天（云端行业数=3）")
        print(f"  动量 top3 命中率: 平均 {clean['mom_hit'].mean()/3:.1%}   完全命中 {full_m:.1%}")
        print(f"  反转 top3 命中率: 平均 {clean['rev_hit'].mean()/3:.1%}   完全命中 {full_r:.1%}")
        print(f"  「取二者较优」完全命中: {np.maximum(clean['mom_hit'], clean['rev_hit']).eq(3).mean():.1%}")
        print()


if __name__ == "__main__":
    main()
