"""analysis_015/industry 更新一 — **反向十分位**：按突破收益分档，反查行业热度。

用户人工理解：近期总进入收益率排行榜的行业（=受资金关注），突破后的肥尾/失败率应较高。
父目录（初建）是「按**热度**分档 → 看收益」；本更新把它反过来：
「按**突破收益**分档 → 看该档的**行业热度**」，回答"**好的突破是不是来自热的行业？**"

指标（用户指定）：sw2021 二级行业（117 个）的「近 **10** 日收益率**横截面排名**均值」，0~1；
每笔突破信号按信号日 t 的 asof 二级行业取值。
对照三组（用户确认）：
  · 窗口    10 日（主） vs 20 日
  · 口径    原始横截面排名 vs **行业内中性化**
    （中性化用 causal expanding 基线——只用到 t 之前的历史，**不用全样本均值**，
      规避初建诊断版的前视问题）

分析：
  1) 按 ret 分十档（等频）→ 每档 n / 热度中位数 / 热度均值 / P25 / P75 / 收益区间 / 失败率 / 肥尾率
  2) 单调性 Spearman(档位, 热度中位数) —— 预期若假设成立则 D10 显著高于 D1
  3) 分时段 2017-2020 vs 2021-2026
  4) 四变体横向对照

产物：heat_panel.parquet / ret_decile_{VARIANT}.csv / summary.csv / period_split.csv / baseline.txt
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
VARIANTS = [("H10_RAW", "10日·原始"), ("H10_DM", "10日·行业内"),
            ("H20_RAW", "20日·原始"), ("H20_DM", "20日·行业内")]


def bucket_stat(g: pd.DataFrame, col: str) -> pd.Series:
    r = g["ret"] * 100
    h = g[col]
    return pd.Series({
        "n": len(g),
        "热度中位数": round(h.median(), 3),
        "热度均值": round(h.mean(), 3),
        "热度P25": round(h.quantile(0.25), 3),
        "热度P75": round(h.quantile(0.75), 3),
        "收益中位%": round(r.median(), 2),
        "收益区间%": f"[{r.min():.0f},{r.max():.0f}]",
        "失败率%": round((r <= 0).mean() * 100, 1),
        "肥尾率%": round((r >= 30).mean() * 100, 1)})


def build_heat(trades: pd.DataFrame) -> pd.DataFrame:
    """在父目录 industry_panel.parquet 的日频截面排名上派生 10/20 日热度（原始 + 行业内）。"""
    pan = pd.read_parquet(UP / "industry_panel.parquet")[["ind2", "date", "r_RET"]]
    pan = pan.sort_values(["ind2", "date"])
    g = pan.groupby("ind2")
    for w in (10, 20):
        col = f"H{w}_RAW"
        pan[col] = g["r_RET"].transform(lambda s: s.rolling(w).mean())
        # 行业内中性化：expanding 基线只用 t 之前历史（shift 1），causal
        base = g[col].transform(lambda s: s.shift(1).expanding(min_periods=250).mean())
        pan[f"H{w}_DM"] = pan[col] - base
    return pan


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    print(f"样本 {len(det)} 笔（{det['date'].min().date()} ~ {det['date'].max().date()}）")
    base_fail = round((det["ret"] * 100 <= 0).mean() * 100, 1)
    base_fat = round((det["ret"] * 100 >= 30).mean() * 100, 1)
    print(f"基线：失败率 {base_fail}% / 肥尾率 {base_fat}% / 均值 {det['ret'].mean()*100:+.2f}% "
          f"/ 中位 {det['ret'].median()*100:+.2f}%")

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

    pan = build_heat(det)
    pan.to_parquet(HERE / "heat_panel.parquet")

    d = det.merge(asof, on=["symbol", "date"], how="left")
    d = d.merge(pan, on=["date", "ind2"], how="left")
    d = d.dropna(subset=[v for v, _ in VARIANTS]).copy()
    print(f"可配热度 {len(d)} 笔 | {d['ind2'].nunique()} 个二级行业")

    # ── ① 按 ret 分十档（等频）──
    d["ret_dec"] = pd.qcut(d["ret"], 10, labels=False, duplicates="drop") + 1
    ndec = d["ret_dec"].nunique()
    print(f"收益分档：{ndec} 档（等频，每档 ~{len(d)//ndec} 笔）\n")

    summ = []
    for var, label in VARIANTS:
        t = d.groupby("ret_dec").apply(bucket_stat, col=var, include_groups=False)
        t.to_csv(HERE / f"ret_decile_{var}.csv", encoding="utf-8-sig")
        idx = pd.Series(t.index, index=t.index)
        sp_med = t["热度中位数"].corr(idx, method="spearman")
        sp_mu = t["热度均值"].corr(idx, method="spearman")
        summ.append({"变体": label, "档↔热度中位数": round(sp_med, 2), "档↔热度均值": round(sp_mu, 2),
                     "D1热度中位": t.loc[1, "热度中位数"], "D10热度中位": t.loc[ndec, "热度中位数"],
                     "D10−D1": round(t.loc[ndec, "热度中位数"] - t.loc[1, "热度中位数"], 3)})
        print(f"== {label}：按收益分档看热度 ==  (Spearman 档↔中位数 {sp_med:+.2f} / 档↔均值 {sp_mu:+.2f})")
        print(t.to_string(), "\n")
    summary = pd.DataFrame(summ)
    summary.to_csv(HERE / "summary.csv", index=False, encoding="utf-8-sig")
    print("== 四变体对照 ==\n", summary.to_string(index=False))

    # ── ② 分时段 ──
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"),
                        ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        for var, label in VARIANTS:
            s["rd"] = pd.qcut(s["ret"], 5, labels=False, duplicates="drop") + 1
            t = s.groupby("rd")[var].median()
            sp = t.corr(pd.Series(t.index, index=t.index), method="spearman")
            rows.append({"时段": seg, "变体": label, "档↔热度中位数(Spearman)": round(sp, 2),
                         "n": len(s), **{f"Q{k}热度中位": round(t.get(k, np.nan), 3) for k in range(1, 6)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段（收益五分位 Q1最低 → Q5最高，热度中位数）==\n", per.to_string(index=False))

    (HERE / "baseline.txt").write_text(
        f"n={len(det)}\n失败率%(ret≤0)={base_fail}\n肥尾率%(ret≥30)={base_fat}\n"
        f"均值%={det['ret'].mean()*100:.2f}\n中位%={det['ret'].median()*100:.2f}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
