"""analysis_015/industry 更新五 — 按突破收益十档，看三个行业排名的**完整分布**。

用户指定：把 `ret` 分成十档，查看每档 **收益率排名 / 换手率排名 / 成交量排名** 的**分布**，并可视化。

与前序更新的差别：更新一/二只给了**中位数**（+P25/P75 带），本更新给**逐档完整分布**
（箱线 + 分位表），可以直观判断"档间位移"相对于"档内离散度"到底有多大——
这正是判断这些微弱效应是否值得采用的关键视角。

指标（与更新一/二同源，10 日窗口）：sw2021 二级行业（117 个）的日频横截面排名 → 10 日均值
  H10_RET   收益率排名均值
  H10_TURN  换手率排名均值
  H10_VOL   成交量排名均值
口径：**原始横截面排名** vs **行业内中性化**（causal expanding 基线，仅用 t 之前历史）

产物：dist_samples.parquet（逐笔，供画箱线）/ dist_stats.csv（逐档分位表）/ baseline.txt
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent                                   # industry/
PROJ = HERE.parents[3]                             # hs300-enh-2017-2021
sys.path.insert(0, str(PROJ))
warnings.filterwarnings("ignore")

DETAIL = PROJ / "01_data_analysis/analysis_012/v4_backtest/detail_v4.parquet"
WH = PROJ.parents[2] / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
METRICS = [("RET", "收益率排名"), ("TURN", "换手率排名"), ("VOL", "成交量排名"),
           ("AMT", "成交额排名")]
CALIPERS = [("RAW", "原始"), ("DM", "行业内")]
PCTS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    # 剔除未判定单（result='pending'，ret 为 NaN）——显式处理，勿依赖 groupby 静默丢 NaN
    n_pending = int(det["ret"].isna().sum())
    det = det[det["ret"].notna()].copy()
    print(f"剔除未判定 pending {n_pending} 笔 → 已判定 {len(det)} 笔")
    base = {"n": len(det),
            "失败率%": round((det["ret"] * 100 <= 0).mean() * 100, 1),
            "肥尾率%": round((det["ret"] * 100 >= 30).mean() * 100, 1),
            "均值%": round(det["ret"].mean() * 100, 2),
            "中位%": round(det["ret"].median() * 100, 2)}
    print(f"样本 {len(det)} 笔｜基线 失败率 {base['失败率%']}% / 肥尾率 {base['肥尾率%']}% / 均值 {base['均值%']:+.2f}%")

    # ── 10 日排名均值（原始 + 行业内）──
    pan = pd.read_parquet(UP / "industry_panel.parquet")[["ind2", "date", "r_RET", "r_TURN", "r_VOL"]]
    # 成交额排名：panel 原无，从仓库按二级聚合（amount=加总口径）→ 日频截面排名
    con0 = duckdb.connect(str(WH), read_only=True)
    amt = con0.execute("""SELECT substr(instrument,1,4) AS ind2, date, sum(amount) AS amt
                          FROM stock_industry_bar1d GROUP BY 1, 2""").df()
    con0.close()
    amt["date"] = pd.to_datetime(amt["date"])
    pan = pan.merge(amt, on=["ind2", "date"], how="left")
    pan["r_AMT"] = pan.groupby("date")["amt"].rank(pct=True)
    print(f"成交额聚合 {len(amt):,} 行 | r_AMT 缺失 {pan['r_AMT'].isna().sum()}")
    pan = pan.sort_values(["ind2", "date"]).copy()
    cols = []
    for m, _ in METRICS:
        c = f"H10_{m}_RAW"
        pan[c] = pan.groupby("ind2")[f"r_{m}"].transform(lambda s: s.rolling(10).mean())
        b = pan.groupby("ind2")[c].transform(lambda s: s.shift(1).expanding(min_periods=250).mean())
        pan[f"H10_{m}_DM"] = pan[c] - b
        cols += [c, f"H10_{m}_DM"]

    syms = "','".join(sorted(det["symbol"].unique()))
    con = duckdb.connect(str(WH), read_only=True)
    asof = con.execute(f"""SELECT instrument AS symbol, date,
                                  substr(industry_instrument,1,4) AS ind2
                           FROM stock_industry_component_daily
                           WHERE instrument IN ('{syms}')""").df()
    con.close()
    asof["date"] = pd.to_datetime(asof["date"])
    asof = asof.drop_duplicates(["symbol", "date"])

    d = det.merge(asof, on=["symbol", "date"], how="left").merge(pan, on=["date", "ind2"], how="left")
    d = d.dropna(subset=cols).copy()
    d["ret_dec"] = pd.qcut(d["ret"], 10, labels=False, duplicates="drop") + 1
    n_dec = d["ret_dec"].nunique()
    print(f"可配 {len(d)} 笔 | {d['ind2'].nunique()} 个二级行业 | 收益 {n_dec} 档\n")

    # ── 逐笔样本（画箱线用）──
    keep = ["symbol", "date", "ret", "ret_dec", "ind2"] + cols
    d[keep].to_parquet(HERE / "dist_samples.parquet", index=False)

    # ── 逐档分位表 ──
    rows = []
    for m, mlab in METRICS:
        for cal, clab in CALIPERS:
            c = f"H10_{m}_{cal}"
            for dec, g in d.groupby("ret_dec"):
                s = g[c]
                q = s.quantile(PCTS)
                rows.append({
                    "指标": mlab, "口径": clab, "档": f"D{int(dec)}",
                    "n": len(g), "收益中位%": round(g["ret"].mean() * 100, 2),
                    "均值": round(s.mean(), 4), "标准差": round(s.std(), 4),
                    "最小值": round(s.min(), 4), "P5": round(q.loc[0.05], 4),
                    "P10": round(q.loc[0.10], 4), "P25": round(q.loc[0.25], 4),
                    "P50": round(q.loc[0.50], 4), "P75": round(q.loc[0.75], 4),
                    "P90": round(q.loc[0.90], 4), "P95": round(q.loc[0.95], 4),
                    "最大值": round(s.max(), 4), "偏度": round(s.skew(), 3),
                    "IQP50−P25": round(q.loc[0.50] - q.loc[0.25], 4)})
    stats = pd.DataFrame(rows)
    stats.to_csv(HERE / "dist_stats.csv", index=False, encoding="utf-8-sig")

    # ── 摘要：档间位移 vs 档内离散度（判断效应是否值得用）──
    print("== 档间位移 vs 档内离散度（10 日）==")
    print(f"{'指标':<12}{'口径':<8}{'D1中位':>9}{'D10中位':>9}{'D1−D6':>9}{'档内IQR':>9}{'位移/IQR':>10}")
    summ = []
    for m, mlab in METRICS:
        for cal, clab in CALIPERS:
            c = f"H10_{m}_{cal}"
            med = d.groupby("ret_dec")[c].median()
            ion = d.groupby("ret_dec")[c].apply(
                lambda s: s.quantile(0.75) - s.quantile(0.25)).mean()
            shift = med.loc[1] - med.loc[min(6, n_dec)]
            ratio = abs(shift) / ion
            summ.append({"指标": mlab, "口径": clab, "D1中位": round(med.loc[1], 4),
                         "D6中位": round(med.loc[min(6, n_dec)], 4),
                         "D10中位": round(med.loc[n_dec], 4),
                         "D1−D6": round(shift, 4), "档内IQR": round(ion, 4),
                         "位移/IQR": round(ratio, 2)})
            print(f"{mlab:<10}{clab:<8}{med.loc[1]:>9.4f}{med.loc[n_dec]:>9.4f}"
                  f"{shift:>9.4f}{ion:>9.4f}{ratio:>10.2f}")
    pd.DataFrame(summ).to_csv(HERE / "dispersion_summary.csv", index=False, encoding="utf-8-sig")

    (HERE / "baseline.txt").write_text(
        f"n={base['n']}\n失败率%(ret≤0)={base['失败率%']}\n肥尾率%(ret≥30)={base['肥尾率%']}\n"
        f"均值%={base['均值%']}\n中位%={base['中位%']}\n可配笔数={len(d)}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
