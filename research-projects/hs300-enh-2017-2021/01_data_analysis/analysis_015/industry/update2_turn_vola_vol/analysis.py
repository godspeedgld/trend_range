"""analysis_015/industry 更新二 — 换手率 / 波动率 / 成交量 三指标，复用更新一的反向十分位。

分析设计与 update1_reverse_decile **完全相同**，只换被检验的行业热度指标：
  1) 按每笔突破的 `ret` 分十档等频 → 看每档的**行业热度中位数 / 均值 / P25 / P75**
  2) 单调性 Spearman(档位, 热度中位数) + 分时段 2017-2020 vs 2021-2026
  3) 窗口 10 日（主） vs 20 日；口径 原始横截面排名 vs 行业内中性化（causal expanding 基线）

三个指标（均为 sw2021 二级行业，117 个，日频纵向截面排名 0~1）：
  TURN  换手率**水平**的横截面排名
  VOLA  波动率**水平**的横截面排名
        ★ 新指标：panel 原无，此处定义 **20 日滚动日收益率标准差** 作为行业波动率
  VOL   成交量**水平**的横截面排名

产物：heat_panel.parquet / ret_decile_{TURN,VOLA,VOL}.csv / summary.csv / period_split.csv / baseline.txt
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

METRICS = [("TURN", "换手率"), ("VOLA", "波动率"), ("VOL", "成交量")]
VARIANTS = [(m, w, c) for m, _ in METRICS for w in (10, 20) for c in ("RAW", "DM")]
TAG = {"RAW": "原始", "DM": "行业内"}


def vname(m: str, w: int, c: str) -> str:
    return f"H{w}_{m}_{c}"


def bucket_stat(g: pd.DataFrame, cols: list[str]) -> pd.Series:
    r = g["ret"] * 100
    row = {"n": len(g), "收益中位%": round(r.median(), 2),
           "收益区间%": f"[{r.min():.0f},{r.max():.0f}]",
           "失败率%": round((r <= 0).mean() * 100, 1),
           "肥尾率%": round((r >= 30).mean() * 100, 1)}
    for v in cols:
        row[f"{v}_中位"] = round(g[v].median(), 3)
        row[f"{v}_均值"] = round(g[v].mean(), 3)
        row[f"{v}_P25"] = round(g[v].quantile(0.25), 3)
        row[f"{v}_P75"] = round(g[v].quantile(0.75), 3)
    return pd.Series(row)


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    base_fail = round((det["ret"] * 100 <= 0).mean() * 100, 1)
    base_fat = round((det["ret"] * 100 >= 30).mean() * 100, 1)
    print(f"样本 {len(det)} 笔（{det['date'].min().date()} ~ {det['date'].max().date()}）"
          f"｜基线 失败率 {base_fail}% / 肥尾率 {base_fat}%")

    # ── 行业热度面板 ──
    pan = pd.read_parquet(UP / "industry_panel.parquet")[["ind2", "date", "chg", "r_TURN", "r_VOL"]]
    pan = pan.sort_values(["ind2", "date"])
    # 波动率：20 日滚动日收益率标准差 → 日频横截面排名
    pan["vola"] = pan.groupby("ind2")["chg"].transform(lambda s: s.rolling(20).std())
    pan["r_VOLA"] = pan.groupby("date")["vola"].rank(pct=True)
    ranks = {"TURN": "r_TURN", "VOLA": "r_VOLA", "VOL": "r_VOL"}

    allcols = []
    for m, _ in METRICS:
        for w in (10, 20):
            col = vname(m, w, "RAW")
            pan[col] = pan.groupby("ind2")[ranks[m]].transform(lambda s: s.rolling(w).mean())
            # 行业内中性化：expanding 基线仅用 t 之前历史（shift 1），causal
            base = pan.groupby("ind2")[col].transform(
                lambda s: s.shift(1).expanding(min_periods=250).mean())
            pan[vname(m, w, "DM")] = pan[col] - base
        allcols += [vname(m, w, c) for w in (10, 20) for c in ("RAW", "DM")]
    pan.to_parquet(HERE / "heat_panel.parquet")

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
    print(f"可配热度 {len(d)} 笔 | {d['ind2'].nunique()} 个二级行业 | 收益 {ndec} 档\n")

    # ── ① 十档：每指标一张表（含 4 变体）──
    summ = []
    for m, label in METRICS:
        cols = [vname(m, w, c) for w in (10, 20) for c in ("RAW", "DM")]
        t = d.groupby("ret_dec").apply(bucket_stat, cols=cols, include_groups=False)
        t.index.name = "ret_dec"
        t.to_csv(HERE / f"ret_decile_{m}.csv", encoding="utf-8-sig")
        idx = pd.Series(t.index, index=t.index)
        for w in (10, 20):
            for c in ("RAW", "DM"):
                v = vname(m, w, c)
                sp = t[f"{v}_中位"].corr(idx, method="spearman")
                summ.append({"指标": label, "窗口": f"{w}日", "口径": TAG[c],
                             "档↔热度中位数": round(sp, 2),
                             "D1": t.loc[1, f"{v}_中位"], "D6": t.loc[6, f"{v}_中位"],
                             "D10": t.loc[ndec, f"{v}_中位"],
                             "D10−D1": round(t.loc[ndec, f"{v}_中位"] - t.loc[1, f"{v}_中位"], 3),
                             "U型深度(D1−D6)": round(t.loc[1, f"{v}_中位"] - t.loc[6, f"{v}_中位"], 3)})
        print(f"== {label} 十档（热度中位数）==")
        print(t[[c for c in t.columns if c.endswith("_中位") or c in
                 ("n", "收益中位%", "失败率%", "肥尾率%")]].to_string(), "\n")
    summary = pd.DataFrame(summ)
    summary.to_csv(HERE / "summary.csv", index=False, encoding="utf-8-sig")
    print("== 12 变体总表 ==\n", summary.to_string(index=False))

    # ── ② 分时段（五分位）──
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"),
                        ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        s["rd"] = pd.qcut(s["ret"], 5, labels=False, duplicates="drop") + 1
        for m, label in METRICS:
            for c in ("RAW", "DM"):
                v = vname(m, 10, c)
                t = s.groupby("rd")[v].median()
                sp = t.corr(pd.Series(t.index, index=t.index), method="spearman")
                rows.append({"时段": seg, "指标": label, "口径": TAG[c],
                             "档↔中位数": round(sp, 2),
                             **{f"Q{k}": round(t.get(k, np.nan), 3) for k in range(1, 6)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段五分位（热度中位数，10日）==\n", per.to_string(index=False))

    (HERE / "baseline.txt").write_text(
        f"n={len(det)}\n失败率%(ret≤0)={base_fail}\n肥尾率%(ret≥30)={base_fat}\n"
        f"均值%={det['ret'].mean()*100:.2f}\n中位%={det['ret'].median()*100:.2f}\n"
        f"可配热度笔数={len(d)}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
