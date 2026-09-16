"""analysis_007 更新七 — 成功/失败分拆的 degree、decile 分布。

在 ret_stats（更新六）基础上，把已判定交易拆为：
  成功 = ret_pct > 0；失败 = ret_pct <= 0
对每组分别做 degree / decile 的分布统计（n / 平均 / 中位 / 该组内占比）+ 期望视角。

⚠ 期望的口径说明（避免误导）：
  - 组内"平均收益率"是条件期望（已知成败后），不是策略期望
  - 策略意义要看"该档里 成功占比 × 成功均值 + 失败占比 × 失败均值"= 档整体期望（by_degree/by_decile 已有）
  - 分拆的价值 = 看成功/失败分别集中在什么 degree / decile，成败结构是否随维度移动
输出 CSV + 供 build_view 比较。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
inp = pd.read_csv(HERE / "stats_input.csv")
inp = inp.dropna(subset=["decile"]).copy()
inp["ok"] = inp["ret_pct"] > 0
# degree 桶：2..11 逐档 + 12+ 尾桶（用 99 标记，避免与真 degree 11 混淆）
inp["g_deg"] = inp["degree"].apply(lambda d: d if d <= 11 else 99)
DEG_LABEL = {**{i: str(i) for i in range(2, 12)}, 99: "12+"}

print(f"已判定 {len(inp)} | 成功 {(inp.ok).sum()} / 失败 {(~inp.ok).sum()}")

def split_stats(df, key):
    out = []
    for k, g in df.groupby(key):
        ok, bad = g[g.ok], g[~g.ok]
        label = DEG_LABEL.get(k, str(k)) if key == "g_deg" else str(k)
        out.append({
            key: k, "label": label, "n_ok": len(ok), "n_bad": len(bad), "n": len(g),
            "ok_share_of_grp": len(ok) / len(g),               # 该档成功率
            "ok_mean": ok["ret_pct"].mean() if len(ok) else np.nan,   # 成功组平均盈利
            "ok_median": ok["ret_pct"].median() if len(ok) else np.nan,
            "bad_mean": bad["ret_pct"].mean() if len(bad) else np.nan, # 失败组平均亏损
            "bad_median": bad["ret_pct"].median() if len(bad) else np.nan,
            "grp_mean": g["ret_pct"].mean(),                    # 档整体期望
            "p90_ok": ok["ret_pct"].quantile(0.9) if len(ok) else np.nan,
        })
    return pd.DataFrame(out)

deg = split_stats(inp, "g_deg").sort_values("g_deg")
deg.to_csv(HERE / "sf_by_degree.csv", index=False, encoding="utf-8-sig")
dci = split_stats(inp, "decile").sort_values("decile")
dci.to_csv(HERE / "sf_by_decile.csv", index=False, encoding="utf-8-sig")

print("\n═══ 按 degree（12+=尾桶）═══")
print(deg.round(2).to_string(index=False))
print("\n═══ 按十分位 ═══")
print(dci.round(2).to_string(index=False))

# 成功/失败各自的 degree / decile 分布占比
inp_ok, inp_bad = inp[inp.ok], inp[~inp.ok]
for nm, sub in (("成功组", inp_ok), ("失败组", inp_bad)):
    print(f"\n{nm}（{len(sub)} 笔）degree 分布（占比前 8）:")
    print((sub["g_deg"].map(DEG_LABEL).value_counts(normalize=True).head(8).round(3) * 100).to_string())
    print(f"{nm} decile 分布（占比）:")
    print((sub["decile"].value_counts(normalize=True).round(3) * 100).to_string())
print("\n写出 sf_by_degree.csv / sf_by_decile.csv")
