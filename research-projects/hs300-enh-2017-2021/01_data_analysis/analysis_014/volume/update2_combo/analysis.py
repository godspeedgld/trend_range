"""analysis_014/volume 更新二·修正 — COMBO=UDVR−RV 组合：自历史语义归一（用户方法论修正后重写）。

修正要点（用户质询成立）：
  ① 特征语义必须是"vs 自己的历史"——RV 的放量/UDVR 的涨量结构都是自历史概念；
     同日截面分位（上一版主口径）会洗掉"全市场齐放量日"的绝对量级信息，弃用（截面比较
     只留给最终选股步骤）
  ② 实证支持：same-day rankIC(RV)=−0.004≈0——量能信息在绝对量级（巨量禁区），不在截面排序
  ③ 修复上一版 bug：ret 双重 ×100；qcut 重复边界
归一（主口径）：log-z，且 μ/σ 用**前半样本（≤2021-06-30）标定**、后半应用——零前视：
  COMBO_logz = z(UDVR) − z(log RV)   （log 处理 RV 厚尾；两特征 z 化后同尺度可减）
对照：绝对分带组合（整阈值，语义直读）：RV 带 [0,1.9)/[1.9,3.8)/[3.8,∞)，UDVR 带
  [0,0.55)/[0.55,0.78)/[0.78,1] → 九宫格（生成版 3×3 的绝对化）。
检验：pooled 十档（失败率/肥尾率/均值/RATIO）+ 同日截面 rankIC（排序场景该看的）+ 分时段。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent
CAL_END = "2021-06-30"      # 标定截止（前半样本）


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    fail, fat = (r <= 0).mean() * 100, (r >= 30).mean() * 100
    return pd.Series({"n": len(g), "失败率%": round(fail, 1), "肥尾率%": round(fat, 1),
                      "RATIO": round(fat / fail, 4), "均值%": round(r.mean(), 2)})


def main():
    d = pd.read_parquet(UP / "vol_features.parquet").replace([np.inf, -np.inf], np.nan)
    d = d.dropna(subset=["RV", "UDVR", "ret"]).copy()

    # ── 主口径：log-z，前半样本标定 ──
    d["lrv"] = np.log(d["RV"])
    cal = d[d["date"] <= CAL_END]
    mu_u, sd_u = cal["UDVR"].mean(), cal["UDVR"].std()
    mu_r, sd_r = cal["lrv"].mean(), cal["lrv"].std()
    d["COMBO"] = ((d["UDVR"] - mu_u) / sd_u) - ((d["lrv"] - mu_r) / sd_r)

    # ── 对照：绝对分带九宫格 ──
    d["rv_band"] = pd.cut(d["RV"], [0, 1.9, 3.8, np.inf], labels=["低量(<1.9)", "中量(1.9-3.8)", "巨量(>3.8)"])
    d["ud_band"] = pd.cut(d["UDVR"], [0, 0.55, 0.78, 1.0], labels=["低UD(<0.55)", "中UD(0.55-0.78)", "高UD(>0.78)"])

    d.to_parquet(HERE / "combo_features.parquet")
    base = stat(d)
    print(f"标定集(≤{CAL_END}) n={len(cal)} | μ_UDVR={mu_u:.3f} σ={sd_u:.3f} | μ_logRV={mu_r:.3f} σ={sd_r:.3f}")
    print("== 全体基线 ==\n", base.to_string())

    d["dec"] = pd.qcut(d["COMBO"].rank(method="first"), 10, labels=False) + 1
    t = d.groupby("dec").apply(stat, include_groups=False)
    t["COMBO均值"] = d.groupby("dec")["COMBO"].mean().round(2)
    t.to_csv(HERE / "COMBO_decile.csv", encoding="utf-8-sig")
    print("\n== COMBO(log-z, 前半标定) 十档 ==\n", t.to_string())

    inter = d.groupby(["ud_band", "rv_band"], observed=True).apply(stat, include_groups=False)
    inter.to_csv(HERE / "abs_bands.csv", encoding="utf-8-sig")
    print("\n== 绝对分带九宫格（行=UDVR 列内=RV）==\n", inter.to_string())

    def ric(g, col):
        return g[col].rank().corr(g["ret"].rank()) if len(g) >= 5 else np.nan
    rows = []
    for col in ["COMBO", "RV", "UDVR"]:
        ics = d.groupby("date").apply(ric, col, include_groups=False).dropna()
        halves = d.groupby("date").apply(
            lambda g: pd.Series({"hi": g.loc[g[col] >= g[col].median(), "ret"].mean(),
                                 "lo": g.loc[g[col] < g[col].median(), "ret"].mean()})
            if len(g) >= 5 else None, include_groups=False).dropna()
        rows.append({"指标": col, "同日rankIC": round(ics.mean(), 4), "IR": round(ics.mean() / ics.std(), 2),
                     "高分半区−低分半区pp": round((halves.hi.mean() - halves.lo.mean()) * 100, 2)})
    ic = pd.DataFrame(rows)
    ic.to_csv(HERE / "same_day_rankic.csv", index=False, encoding="utf-8-sig")
    print("\n== 同日截面 rankIC ==\n", ic.to_string(index=False))

    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)]
        ics = s.groupby("date").apply(ric, "COMBO", include_groups=False).dropna()
        s2 = s.copy()
        s2["dec"] = pd.qcut(s2["COMBO"].rank(method="first"), 10, labels=False) + 1
        tt = s2.groupby("dec").apply(stat, include_groups=False)
        rows.append({"时段": seg, "COMBO rankIC": round(ics.mean(), 4),
                     "D1失败率%": tt.loc[1, "失败率%"], "D10失败率%": tt.loc[10, "失败率%"],
                     "D10均值%": tt.loc[10, "均值%"]})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段 ==\n", per.to_string(index=False))


if __name__ == "__main__":
    main()
