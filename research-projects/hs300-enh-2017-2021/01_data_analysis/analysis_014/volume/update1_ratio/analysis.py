"""analysis_014/volume 更新一 — 单一指标 肥尾率/失败率 的区分效果检验。

指标（用户指定）：RATIO = 肥尾率(ret≥30%) / 失败率(ret≤0)——"每单位失败风险换多少肥尾机会"。
策略本质是"高失败率 + 右尾彩票"（中位 −5.1%），成败由右尾主导 → 用尾部机会密度/风险密度
做单指标有明确语义。基线 = 全样本 7.2/65.9 ≈ 0.109。

检验设计：
  1) RV / UDVR 十档：每档 RATIO + 排名，对照 均值% 排名（Spearman：单指标与"真金白银"
     的均值排序是否一致——一致才配当单一评价指标）
  2) 交互 3×3 的 RATIO 矩阵（生成版区分力最强处，单指标是否保留其形状）
  3) 分时段 RATIO 稳定性（2017-20 / 2021-26）
  4) 局限性备注：比值忽略幅度（肥尾 +30% 与 +300% 等权）、失败率接近 0 时发散（本样本
     失败率 ≥55% 无此问题）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    fail = (r <= 0).mean() * 100
    fat = (r >= 30).mean() * 100
    return pd.Series({"n": len(g),
                      "失败率%": round(fail, 1),
                      "肥尾率%": round(fat, 1),
                      "RATIO": round(fat / fail, 4) if fail > 0 else np.nan,
                      "均值%": round(r.mean(), 2)})


def main():
    d = pd.read_parquet(UP / "vol_features.parquet")
    base = stat(d)
    print("== 全体基线 ==\n", base.to_string())

    rows_rank = []
    for col, name in [("RV", "放量比"), ("UDVR", "涨量占比")]:
        d["dec"] = pd.qcut(d[col], 10, labels=False, duplicates="drop") + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["RATIO排名"] = t["RATIO"].rank(ascending=False).astype(int)
        t["均值排名"] = t["均值%"].rank(ascending=False).astype(int)
        t.to_csv(HERE / f"{col}_ratio.csv", encoding="utf-8-sig")
        sp = t["RATIO排名"].corr(t["均值排名"], method="spearman")
        rows_rank.append({"特征": name, "Spearman(RATIO排名,均值排名)": round(sp, 3)})
        print(f"\n== {name} 十档（按 RATIO 降序展示）==")
        print(t.sort_values("RATIO", ascending=False).to_string())
        print(f"Spearman(RATIO排名 vs 均值排名) = {sp:+.3f}")

    # 交互 3×3
    d["rv3"] = pd.qcut(d["RV"], 3, labels=["低RV", "中RV", "高RV"])
    d["ud3"] = pd.qcut(d["UDVR"], 3, labels=["低UDVR", "中UDVR", "高UDVR"])
    inter = d.groupby(["ud3", "rv3"], observed=True).apply(stat, include_groups=False)
    inter.to_csv(HERE / "interaction_ratio.csv", encoding="utf-8-sig")
    print("\n== 交互 3×3 RATIO ==\n", inter.to_string())

    # 分时段
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        b = stat(s)
        for col in ("RV", "UDVR"):
            s["dec"] = pd.qcut(s[col], 10, labels=False, duplicates="drop") + 1
            t = s.groupby("dec").apply(stat, include_groups=False)
            rows.append({"时段": seg, "特征": col, "基线RATIO": round(b["RATIO"], 3),
                         "最优档": f"D{int(t['RATIO'].idxmax())}({t['RATIO'].max():.3f})",
                         "最差档": f"D{int(t['RATIO'].idxmin())}({t['RATIO'].min():.3f})",
                         "极差比": round(t["RATIO"].max() / t["RATIO"].min(), 2) if t["RATIO"].min() > 0 else np.nan})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_ratio.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段 RATIO 稳定性 ==\n", per.to_string(index=False))
    pd.DataFrame(rows_rank).to_csv(HERE / "spearman.csv", index=False, encoding="utf-8-sig")
    (HERE / "baseline.txt").write_text(base.to_string(), encoding="utf-8")


if __name__ == "__main__":
    main()
