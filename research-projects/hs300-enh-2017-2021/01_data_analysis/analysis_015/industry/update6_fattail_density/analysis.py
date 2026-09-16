"""analysis_015/industry 更新六 — **肥尾档（收益最高十档 D10）** 的行业排名**密度分布**。

用户指定：取突破收益最后一档（D10，肥尾档），看 **收益率排名 / 换手率排名 / 成交量排名**
的分布，**不要箱线图，要类高斯的密度曲线**（KDE）。

数据：直接复用 update5_dist_by_ret/dist_samples.parquet（8550 笔已配行业排名，10 日窗口，
原始 + 行业内两种口径，含成交额列但本更新按用户指定只画三个）。

设计：每个指标 × 口径画两条密度——
  · **D10 肥尾档**（n≈855，收益中位 +35.2%）
  · **全体参照**（D1~D10 全部，灰线）——单看一条分布没有参照系，无法判断"肥尾档偏哪儿"
另出逐组统计（均值/中位/偏度/分位，含 ×117 名次口径）。

产物：density_curves.csv / group_stats.csv / baseline.txt
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

HERE = Path(__file__).resolve().parent
UPD5 = HERE.parent / "update5_dist_by_ret"
sys.path.insert(0, str(HERE.parents[3]))
warnings.filterwarnings("ignore")

METRICS = [("RET", "收益率排名"), ("TURN", "换手率排名"), ("VOL", "成交量排名")]
CALIPERS = [("RAW", "原始"), ("DM", "行业内")]
N_IND = 117          # 二级行业数（名次口径换算）
GRID = 241           # KDE 网格点数


def main():
    d = pd.read_parquet(UPD5 / "dist_samples.parquet")
    n_dec = d["ret_dec"].nunique()
    fat = d[d["ret_dec"] == n_dec]          # D10 = 肥尾档
    print(f"全体 {len(d)} 笔 | 肥尾档 D{int(n_dec)} {len(fat)} 笔"
          f"（收益中位 {fat['ret'].median()*100:+.1f}%）")

    curves, stats = [], []
    for m, mlab in METRICS:
        for cal, clab in CALIPERS:
            c = f"H10_{m}_{cal}"
            xs = d[c].dropna()
            xf = fat[c].dropna()
            lo = min(xs.min(), xf.min())
            hi = max(xs.max(), xf.max())
            pad = 0.05 * (hi - lo)
            grid = np.linspace(lo - pad, hi + pad, GRID)
            k_f = gaussian_kde(xf)(grid)
            k_a = gaussian_kde(xs)(grid)
            for gname, dens in [("肥尾档D10", k_f), ("全体参照", k_a)]:
                for x, y in zip(grid, dens):
                    curves.append({"指标": mlab, "口径": clab, "组": gname,
                                   "x": round(float(x), 5), "密度": round(float(y), 5)})
            for gname, s in [("肥尾档D10", xf), ("全体参照", xs)]:
                stats.append({
                    "指标": mlab, "口径": clab, "组": gname, "n": len(s),
                    "均值": round(s.mean(), 4), "均值名次": round(s.mean() * N_IND, 1),
                    "中位": round(s.median(), 4), "中位名次": round(s.median() * N_IND, 1),
                    "标准差": round(s.std(), 4), "偏度": round(s.skew(), 3),
                    "P25": round(s.quantile(.25), 4), "P75": round(s.quantile(.75), 4)})
    pd.DataFrame(curves).to_csv(HERE / "density_curves.csv", index=False, encoding="utf-8-sig")
    st = pd.DataFrame(stats)
    st.to_csv(HERE / "group_stats.csv", index=False, encoding="utf-8-sig")

    print("\n== 肥尾档 vs 全体（密度曲线读数）==")
    for m, mlab in METRICS:
        for cal, clab in CALIPERS:
            f = st[(st.指标 == mlab) & (st.口径 == clab) & (st.组 == "肥尾档D10")].iloc[0]
            a = st[(st.指标 == mlab) & (st.口径 == clab) & (st.组 == "全体参照")].iloc[0]
            print(f"{mlab:<8}{clab:<6} 肥尾档均值 {f.均值:+.4f}（第{f.均值名次}名）"
                  f"偏度 {f.偏度:+.2f} | 全体均值 {a.均值:+.4f}（第{a.均值名次}名）"
                  f"| 差 {f.均值 - a.均值:+.4f}")

    (HERE / "baseline.txt").write_text(
        f"n_all={len(d)}\nn_fat={len(fat)}\n肥尾档收益中位%={fat['ret'].median()*100:.2f}\n"
        f"n_industry={N_IND}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
