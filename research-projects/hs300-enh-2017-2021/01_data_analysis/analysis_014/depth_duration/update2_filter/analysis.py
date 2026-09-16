"""analysis_014/depth_duration 更新二 — 用户定义负向过滤指标 SR 的十分位检验。

指标（用户 2026-09-11 定义，≤t 因果）：
    SR = (high252 − close)/close × AGE/252
    禁区阈值（禁区参数代入）：TOP≥0.995 ∧ AGE≤30 → SR* = 0.005/0.995 × 30/252 ≈ 0.0006
    即 SR ≤ 0.0006 ⟺ dd×AGE ≤ ~0.15（"贴顶×近期顶"软边界）
性质披露：dd=0（close 恰在 252 高点）→ SR=0 恒入禁区（含老顶初破 n≈89 好样本，用户确认
甜点区不需要）；SR 高端（深且久）无优势——纯负向过滤器。
检验：SR 十档（RATIO=肥尾/失败率 主指标 + 失败率/均值护栏）+ D1 组成与 RED 定义重合度 +
阈值组 vs 其余 的分离度 + 分时段。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent
SR_THR = 0.005 / 0.995 * 30 / 252          # ≈ 0.000598


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    fail, fat = (r <= 0).mean() * 100, (r >= 30).mean() * 100
    return pd.Series({"n": len(g), "失败率%": round(fail, 1), "肥尾率%": round(fat, 1),
                      "RATIO": round(fat / fail, 4) if fail > 0 else np.nan,
                      "均值%": round(r.mean(), 2), "中位%": round(r.median(), 2)})


def main():
    d = pd.read_parquet(UP / "dd_features.parquet")
    dd_user = -d["DD"] / (1 + d["DD"])                    # (high−close)/close ≥ 0
    d["SR"] = dd_user * d["AGE"] / 252.0
    base = stat(d)
    print(f"SR* 阈值 = {SR_THR:.6f} | 全体基线 RATIO {base['RATIO']:.4f} 失败率 {base['失败率%']}% 均值 {base['均值%']}%")

    # ── 十档（rank-first 保 10 档；SR=0 并列大，附绝对组）──
    d["dec"] = pd.qcut(d["SR"].rank(method="first"), 10, labels=False) + 1
    t = d.groupby("dec").apply(stat, include_groups=False)
    t["SR区间"] = d.groupby("dec")["SR"].agg(["min", "max"]).apply(
        lambda r: f"[{r['min']:.5f},{r['max']:.5f}]", axis=1)
    t = t[["SR区间", "n", "失败率%", "肥尾率%", "RATIO", "均值%", "中位%"]]
    t.to_csv(HERE / "SR_decile.csv", encoding="utf-8-sig")
    print("\n== SR 十档 ==\n", t.to_string())

    # ── D1 组成 vs RED 定义的贴合度 ──
    d["RED"] = (d["DD"] >= -0.005) & (d["AGE"] <= 30)
    d1 = d[d["dec"] == 1]
    inter = len(d1[d1["RED"]])
    red = d[d["RED"]]
    print(f"\nD1 n={len(d1)}，其中命中 RED(贴顶∧AGE≤30) {inter}（RED 全集 n={len(red)}，"
          f"被 D1+阈值 覆盖 {len(red[red['SR']<=SR_THR])}）")
    print(f"阈值组(SR≤{SR_THR:.5f}) n={int((d['SR']<=SR_THR).sum())}")

    # ── 分离度：禁区 vs 其余 ──
    m = d["SR"] <= SR_THR
    sep = pd.DataFrame({"组": ["禁区 SR≤SR*", "其余", "全体"],
                        "n": [int(m.sum()), int((~m).sum()), len(d)]})
    rows = [stat(d[m]), stat(d[~m]), stat(d)]
    sep = pd.concat([sep.drop(columns="n").reset_index(drop=True),
                     pd.DataFrame(rows).drop(columns="n")], axis=1)
    sep.to_csv(HERE / "separation.csv", index=False, encoding="utf-8-sig")
    print("\n== 分离度（禁区 vs 其余）==\n", sep.to_string(index=False))

    # ── 分时段 ──
    out = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)]
        r1, r0 = stat(s[s["SR"] <= SR_THR]), stat(s[s["SR"] > SR_THR])
        out.append({"时段": seg, "禁区n": int(r1["n"]), "禁区失败率%": r1["失败率%"], "禁区均值%": r1["均值%"],
                    "禁区RATIO": r1["RATIO"], "其余失败率%": r0["失败率%"], "其余均值%": r0["均值%"], "其余RATIO": r0["RATIO"]})
    per = pd.DataFrame(out)
    per.to_csv(HERE / "period.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段 ==\n", per.to_string(index=False))
    d.to_parquet(HERE / "sr_features.parquet")


if __name__ == "__main__":
    main()
