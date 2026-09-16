"""analysis_014/depth_duration 更新三 — RED 双阈值硬规则负向过滤指标检验（用户选 A）。

指标（≤t 因果）：
    RED = [ (high252 − close)/close ≤ 0.5% ]  ∧  [ AGE ≤ 30 ]
    语义："价格贴着顶（≤0.5%）且这个顶是近 30 天内刚做的"——刚做完顶又贴回来=追高。
    甜点区（贴顶 ∧ AGE≥180）与中期带（31-180）与 RED 顶龄段不相交 → 不受影响（已证）。
检验：① 分离度（RATIO=肥尾/失败率 主 + 失败率/均值护栏）② 阈值敏感性网格
    dd_thr∈{0.3%,0.5%,1%} × AGE_thr∈{20,30,60}（防刀锋参数）③ 分时段 ④ 过滤后留存样本
    构成（甜点区仍在）。
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
                      "均值%": round(r.mean(), 2), "中位%": round(r.median(), 2)})


def main():
    d = pd.read_parquet(UP / "dd_features.parquet")
    d["dd_user"] = -d["DD"] / (1 + d["DD"])              # (high−close)/close ≥ 0
    d["GREEN"] = (d["dd_user"] <= 0.005) & (d["AGE"] >= 180)
    base = stat(d)
    print("== 全体基线 ==\n", base.to_string())

    # ── ① 分离度 ──
    d["RED"] = (d["dd_user"] <= 0.005) & (d["AGE"] <= 30)
    sep = pd.DataFrame([
        {"组": "RED 禁区(贴顶≤0.5% ∧ AGE≤30)", **stat(d[d.RED]).to_dict()},
        {"组": "非 RED", **stat(d[~d.RED]).to_dict()},
        {"组": "其中: 甜点区(贴顶∧AGE≥180)", **stat(d[d.GREEN]).to_dict()},
    ])
    sep.to_csv(HERE / "separation.csv", index=False, encoding="utf-8-sig")
    print("\n== 分离度 ==\n", sep.to_string(index=False))

    # ── ② 阈值敏感性网格 ──
    rows = []
    for dd_thr in (0.003, 0.005, 0.010):
        for age_thr in (20, 30, 60):
            m = (d["dd_user"] <= dd_thr) & (d["AGE"] <= age_thr)
            s1, s0 = stat(d[m]), stat(d[~m])
            rows.append({"dd_thr%": round(dd_thr * 100, 1), "AGE_thr": age_thr, "n_红": int(s1["n"]),
                         "红失败率%": s1["失败率%"], "红均值%": s1["均值%"], "红RATIO": s1["RATIO"],
                         "其余失败率%": s0["失败率%"], "其余均值%": s0["均值%"],
                         "Δ失败率pp": round(s1["失败率%"] - s0["失败率%"], 1),
                         "Δ均值pp": round(s1["均值%"] - s0["均值%"], 2)})
    grid = pd.DataFrame(rows)
    grid.to_csv(HERE / "threshold_grid.csv", index=False, encoding="utf-8-sig")
    print("\n== 阈值敏感性（9 格）==\n", grid.to_string(index=False))

    # ── ③ 分时段 ──
    out = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)]
        r1, r0 = stat(s[s.RED]), stat(s[~s.RED])
        out.append({"时段": seg, "红n": int(r1["n"]), "红失败率%": r1["失败率%"], "红均值%": r1["均值%"],
                    "红RATIO": r1["RATIO"], "其余失败率%": r0["失败率%"], "其余均值%": r0["均值%"], "其余RATIO": r0["RATIO"]})
    per = pd.DataFrame(out)
    per.to_csv(HERE / "period.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段 ==\n", per.to_string(index=False))

    # ── ④ 过滤后留存构成 ──
    keep = d[~d.RED]
    comp = keep.groupby(pd.cut(keep["AGE"], [-1, 30, 180, 251],
                               labels=["AGE≤30(未贴顶)", "31-180", "≥181(甜点)"]), observed=False
                        ).apply(stat, include_groups=False)
    comp.to_csv(HERE / "keep_composition.csv", encoding="utf-8-sig")
    print("\n== 过滤后留存（按 AGE 带）==\n", comp.to_string())


if __name__ == "__main__":
    main()
