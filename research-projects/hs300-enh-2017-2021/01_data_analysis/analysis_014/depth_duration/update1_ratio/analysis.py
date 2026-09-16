"""analysis_014/depth_duration 更新一 — 单一指标 RATIO=肥尾率/失败率 在深度/久度上的检验。

与 volume/update1_ratio 同款设计：RATIO = 肥尾率(ret≥30%)/失败率(ret≤0)——"每单位失败风险
换多少肥尾机会"。基线 = 全样本 7.2/65.9 ≈ 0.109。
检验：① DD/AGE 十档 RATIO + 与均值排名一致性（Spearman）② 绝对分带（并列感知）RATIO
③ 新高禁区组 RATIO ④ 分时段稳定性。
（AGE 十档 D1-D3 为 0 值并列 rank 强拆——十档仅形式对齐，结论以绝对分带为准，见生成版坑。）
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    fail, fat = (r <= 0).mean() * 100, (r >= 30).mean() * 100
    return pd.Series({"n": len(g), "失败率%": round(fail, 1), "肥尾率%": round(fat, 1),
                      "RATIO": round(fat / fail, 4) if fail > 0 else np.nan,
                      "均值%": round(r.mean(), 2)})


def main():
    d = pd.read_parquet(UP / "dd_features.parquet")
    base = stat(d)
    print("== 全体基线 ==\n", base.to_string())

    rows_rank = []
    for col, name in [("DD", "深度"), ("AGE", "久度")]:
        d["dec"] = pd.qcut(d[col].rank(method="first"), 10, labels=False) + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["RATIO排名"] = t["RATIO"].rank(ascending=False).astype(int)
        t["均值排名"] = t["均值%"].rank(ascending=False).astype(int)
        t.to_csv(HERE / f"{col}_ratio.csv", encoding="utf-8-sig")
        sp = t["RATIO排名"].corr(t["均值排名"], method="spearman")
        rows_rank.append({"特征": name, "Spearman(RATIO排名,均值排名)": round(sp, 3)})
        print(f"\n== {name} 十档（RATIO 降序）==\n", t.sort_values("RATIO", ascending=False).to_string())
        print(f"Spearman(RATIO排名 vs 均值排名) = {sp:+.3f}")

    # 绝对分带（并列感知）
    d["dd_band"] = pd.cut(d["DD"], [-1, -0.25, -0.05, -0.02, 0.0001, 2],
                          labels=["深<-25%", "中-25~-5%", "浅-5~-2%", "贴线-2~0%", "新高=0"])
    d["age_band"] = pd.cut(d["AGE"], [-1, 0, 30, 90, 180, 251],
                           labels=["0(今日新高)", "1-30天", "31-90天", "91-180天", "181-251天"])
    for bc, name in [("dd_band", "深度绝对分带"), ("age_band", "久度绝对分带")]:
        t = d.groupby(bc, observed=True).apply(stat, include_groups=False)
        t.to_csv(HERE / f"{bc}_ratio.csv", encoding="utf-8-sig")
        print(f"\n== {name} RATIO ==\n", t.to_string())

    nh = d[(d.DD >= 0) & (d.AGE == 0)]
    print("\n== 新高禁区组（DD=0∧AGE=0）==\n", stat(nh).to_string())

    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        b = stat(s)
        for col in ("DD", "AGE"):
            s["dec"] = pd.qcut(s[col].rank(method="first"), 10, labels=False) + 1
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
