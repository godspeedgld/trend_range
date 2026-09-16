"""analysis_015/industry 更新三 — **价量背离**指标：ma(收益率横截面排名,10) − ma(换手率横截面排名,10)。

用户指定指标 = 收益率排名均值 − 换手率排名均值（同为 10 日）。
语义：高值 = **行业涨了但没放量**（悄悄走强）；低值 = **放量滞涨**（拥挤/派发）。
分析流程与更新二**完全相同**（按 ret 分十档反查指标，看中位数/均值/P25/P75 + Spearman + 分时段），
对照：窗口 20−20；口径 原始 vs 行业内中性化（causal expanding 基线）。

注：中性化对差值可分配——demean(a−b) = demean(a) − demean(b)，故对 SPREAD 去均值无歧义。

产物：spread_panel.parquet / ret_decile_SPR.csv / summary.csv / period_split.csv / decomposition.csv / baseline.txt
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
VARIANTS = [("S10_RAW", "10−10·原始"), ("S10_DM", "10−10·行业内"),
            ("S20_RAW", "20−20·原始"), ("S20_DM", "20−20·行业内")]
# 分解用：原始口径的两个成分
COMPS = [("C_RET10", "收益率排名均值(10日)"), ("C_TURN10", "换手率排名均值(10日)")]


def bucket_stat(g: pd.DataFrame, cols: list[str]) -> pd.Series:
    r = g["ret"] * 100
    row = {"n": len(g), "收益中位%": round(r.median(), 2),
           "收益区间%": f"[{r.min():.0f},{r.max():.0f}]",
           "失败率%": round((r <= 0).mean() * 100, 1),
           "肥尾率%": round((r >= 30).mean() * 100, 1)}
    for v in cols:
        row[f"{v}_中位"] = round(g[v].median(), 4)
        row[f"{v}_均值"] = round(g[v].mean(), 4)
        row[f"{v}_P25"] = round(g[v].quantile(0.25), 4)
        row[f"{v}_P75"] = round(g[v].quantile(0.75), 4)
        row[f"{v}_正占比%"] = round((g[v] > 0).mean() * 100, 1)
    return pd.Series(row)


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    base_fail = round((det["ret"] * 100 <= 0).mean() * 100, 1)
    base_fat = round((det["ret"] * 100 >= 30).mean() * 100, 1)
    print(f"样本 {len(det)} 笔｜基线 失败率 {base_fail}% / 肥尾率 {base_fat}%")

    # ── 价量背离面板 ──
    pan = pd.read_parquet(UP / "industry_panel.parquet")[["ind2", "date", "r_RET", "r_TURN"]]
    pan = pan.sort_values(["ind2", "date"])
    allcols = []
    for w in (10, 20):
        pan[f"C_RET{w}"] = pan.groupby("ind2")["r_RET"].transform(lambda s: s.rolling(w).mean())
        pan[f"C_TURN{w}"] = pan.groupby("ind2")["r_TURN"].transform(lambda s: s.rolling(w).mean())
        raw = f"S{w}_RAW"
        pan[raw] = pan[f"C_RET{w}"] - pan[f"C_TURN{w}"]
        base = pan.groupby("ind2")[raw].transform(
            lambda s: s.shift(1).expanding(min_periods=250).mean())     # causal 基线
        pan[f"S{w}_DM"] = pan[raw] - base
        allcols += [raw, f"S{w}_DM"]
    pan[["ind2", "date", "C_RET10", "C_TURN10"] + allcols].to_parquet(HERE / "spread_panel.parquet")

    # ── 行业归属（asof）──
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
    d = d.dropna(subset=allcols).copy()
    d["ret_dec"] = pd.qcut(d["ret"], 10, labels=False, duplicates="drop") + 1
    ndec = d["ret_dec"].nunique()
    print(f"可配 {len(d)} 笔 | {d['ind2'].nunique()} 个二级行业 | 收益 {ndec} 档\n")

    # ── ① 十档 ──
    t = d.groupby("ret_dec").apply(
        bucket_stat, cols=allcols + ["C_RET10", "C_TURN10"], include_groups=False)
    t.index.name = "ret_dec"
    t.to_csv(HERE / "ret_decile_SPR.csv", encoding="utf-8-sig")
    idx = pd.Series(t.index, index=t.index)
    summ = []
    for v, label in VARIANTS:
        sp = t[f"{v}_中位"].corr(idx, method="spearman")
        summ.append({"变体": label, "档↔指标中位数": round(sp, 2),
                     "D1": t.loc[1, f"{v}_中位"], "D6": t.loc[6, f"{v}_中位"],
                     "D10": t.loc[ndec, f"{v}_中位"],
                     "最高档": int(t[f"{v}_中位"].idxmax()),
                     "D10−D1": round(t.loc[ndec, f"{v}_中位"] - t.loc[1, f"{v}_中位"], 4),
                     "D1−D6": round(t.loc[1, f"{v}_中位"] - t.loc[6, f"{v}_中位"], 4),
                     "正占比%": t.loc[ndec, f"{v}_正占比%"]})
    summary = pd.DataFrame(summ)
    summary.to_csv(HERE / "summary.csv", index=False, encoding="utf-8-sig")
    print("== 十档（指标中位数）==")
    print(t[[c for c in t.columns if c in ("n", "收益中位%", "失败率%", "肥尾率%")
             or c.endswith("_中位")]].to_string(), "\n")
    print("== 变体对照 ==\n", summary.to_string(index=False))

    # ── ② 分解：原始口径下 收益率/换手率/差值 三行并排 ──
    dec = pd.DataFrame({
        "收益率排名均值(10日)": t["C_RET10_中位"],
        "换手率排名均值(10日)": t["C_TURN10_中位"],
        "差值(=指标)": t["S10_RAW_中位"],
        "差值(行业内)": t["S10_DM_中位"],
        "差值正占比%(原始)": t["S10_RAW_正占比%"]})
    dec.to_csv(HERE / "decomposition.csv", encoding="utf-8-sig")
    print("\n== 成分分解（原始, 10日）==\n", dec.to_string())

    # ── ③ 分时段 ──
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"),
                        ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        s["rd"] = pd.qcut(s["ret"], 5, labels=False, duplicates="drop") + 1
        for v, label in VARIANTS:
            q = s.groupby("rd")[v].median()
            sp = q.corr(pd.Series(q.index, index=q.index), method="spearman")
            rows.append({"时段": seg, "变体": label, "档↔中位数": round(sp, 2), "n": len(s),
                         **{f"Q{k}": round(q.get(k, np.nan), 4) for k in range(1, 6)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段五分位（指标中位数）==\n", per.to_string(index=False))

    (HERE / "baseline.txt").write_text(
        f"n={len(det)}\n失败率%(ret≤0)={base_fail}\n肥尾率%(ret≥30)={base_fat}\n"
        f"均值%={det['ret'].mean()*100:.2f}\n中位%={det['ret'].median()*100:.2f}\n"
        f"可配笔数={len(d)}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
