"""strategy_009 目标构建 —— 在**不改动冻结的 shared/build_weekly_targets.py** 的前提下，
给行业层加上「同簇替换」分散约束。

做法（最小侵入）：import 冻结模块 → **monkeypatch 其模块级 `pick_industries`** → 调用它的 `build()`。
`build()` 内部按模块全局名查找 `pick_industries`，故替换生效；冻结文件零改动。

约束（analysis_020 §F，K=7）：
  只在**本周 top3 三行业落在同一个簇**时动手（全窗 47/494 周 = 9.5%）：保留前两名，
  末位换成**簇外同键最优**行业（动量周 mom_240 最高 / 反转周 mom_60 最低）。其余 447 周一字不动。

产物（写 shared/_cache/，文件名带 009 后缀，**不覆盖任何冻结件**）：
  sig_weekly_cluster009_K{K}.parquet   —— 全开表（date, instrument, weight），供引擎按周施加 exposure
  meta_cluster009_K{K}.parquet         —— 每周 regime / top3 / sc_mean / sc_max / stable / n_common / 是否被替换

自检（本脚本末尾）：
  ① 被改动的周数 = 47（K=7），且**逐周换入行业与 analysis_020/F_trigger_detail.csv 完全一致**；
  ② 每个满仓周权重合计 ≈ 1.0（等于 A.build_sig_full 的口径：行业内 1/vol 再除 N_IND）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
CACHE = PROJ / "shared" / "_cache"
sys.path.insert(0, str(PROJ / "shared"))
sys.path.insert(0, str(PROJ / "02_strategy_iteration" / "strategy_008"))

import build_weekly_targets as B                       # noqa: E402  （冻结件，只读 import）
import ab_engine_controls as A                         # noqa: E402  （引擎脚手架，复用）

K = int(os.environ.get("CLUSTER_K", 7))
LINKAGE = os.environ.get("CLUSTER_LINKAGE", "complete")
WIN = int(os.environ.get("CLUSTER_WIN", 252))
OUT_SIG = CACHE / f"sig_weekly_cluster009_K{K}.parquet"
OUT_META = CACHE / f"meta_cluster009_K{K}.parquet"
LAB_FILE = CACHE / f"industry_cluster_weekly_K{K}_{LINKAGE}_w{WIN}.parquet"

_LOG = {"mod": []}          # 被替换的周（供自检）

# ★ 2026-10-16 修（重要）：**在模块导入时固定一次"原始行业选择函数"**。
#   原先每个 maker 里写 `orig = B.pick_industries`，一旦之前已打过补丁，
#   新建的 wrapper 就会把"上一次打过补丁的函数"当作原始函数 ⇒ **约束层层叠加**
#   （实测 grid 的 K=7 触发数从 47 涨到 192、nav 2.63，四个对照模式全被污染）。
#   主矩阵与自检未受影响：列 1 走 A.build_sig_full 自己绑定的原函数，
#   列 2 用本文件独立运行时（首次打补丁）产出的 parquet。
ORIG_PICK = B.pick_industries


def make_pick(labels: pd.DataFrame):
    """返回一个替代 B.pick_industries 的函数（闭包持有标签表）。"""
    orig = ORIG_PICK

    def pick(ind_day: pd.DataFrame, t_prime: float):
        top3, regime = orig(ind_day, t_prime)
        t = pd.Timestamp(ind_day["date"].iloc[0])
        if t not in labels.index:
            return top3, regime
        lab = labels.loc[t]
        if len({lab.get(x, -1) for x in top3}) != 1:    # 只在"三行业同簇"时动手
            return top3, regime
        col = "mom_240" if regime == "momentum" else "mom_60"
        s = ind_day.set_index("ind_name")[col].astype(float)
        keep_cl = lab.get(top3[0], -1)
        outside = s[[lab.get(x, -2) != keep_cl for x in s.index]].dropna()
        if outside.empty:
            return top3, regime
        repl = outside.idxmax() if regime == "momentum" else outside.idxmin()
        _LOG["mod"].append({"周": str(t.date()), "regime": regime, "原top3": ",".join(top3),
                            "换入": repl, "新top3": ",".join([top3[0], top3[1], repl])})
        return [top3[0], top3[1], repl], regime

    return pick


def make_pick_live(labels: pd.DataFrame):
    """★ 隔离版约束：**只在"原规则本周本来会满仓"的周替换**。

    动机：主矩阵诊断显示约束会打断稳定性过滤链（exposure 差异 15~22 周），这把
    "分散本身的效果" 与 "暴露通道被打断的代价" 混在一起。本版要求
    「原 top3 == 上周原 top3」（**因果可得**：上周名单是已知信息）才施加约束 ⇒
    该周本来就会满仓，替换不会新增空仓周，从而把效果干净地归给"分散"。
    """
    orig = ORIG_PICK
    state = {"prev": None}

    def pick(ind_day: pd.DataFrame, t_prime: float):
        top3, regime = orig(ind_day, t_prime)
        cur = tuple(sorted(top3))
        prev, state["prev"] = state["prev"], cur
        if prev is not None and cur != prev:
            return top3, regime                      # 原规则本周会空仓 ⇒ 一字不动
        t = pd.Timestamp(ind_day["date"].iloc[0])
        if t not in labels.index:
            return top3, regime
        lab = labels.loc[t]
        if len({lab.get(x, -1) for x in top3}) != 1:
            return top3, regime
        col = "mom_240" if regime == "momentum" else "mom_60"
        s = ind_day.set_index("ind_name")[col].astype(float)
        keep_cl = lab.get(top3[0], -1)
        outside = s[[lab.get(x, -2) != keep_cl for x in s.index]].dropna()
        if outside.empty:
            return top3, regime
        repl = outside.idxmax() if regime == "momentum" else outside.idxmin()
        _LOG["mod"].append({"周": str(t.date()), "regime": regime, "原top3": ",".join(top3),
                            "换入": repl, "新top3": ",".join([top3[0], top3[1], repl])})
        return [top3[0], top3[1], repl], regime

    return pick


def build_sig_cluster():
    """镜像 ab_engine_controls.build_sig_full() 的循环，但用（已打补丁的）行业选择。"""
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
    crowd = {(pd.Timestamp(w), i): float(s) for w, i, s in
             zip(cd["week"], cd["ind"], cd["signal_count"])}

    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    pby = {d: g for d, g in panel.groupby("date")}
    prev_top3, held, frames, meta = None, {}, [], {}
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), pby.get(t)
        if day is None or cand is None:
            continue
        top3, regime = B.pick_industries(day, float(regi.at[t, "T_prime"]))
        dirs = B.factor_directions("baseline", regime)      # ★ 恒反转（与基线/007/008 一致）
        tg = B.build_targets(cand, top3, dirs, held)
        scs = [crowd.get((t, p), np.nan) for p in top3]
        scs_ok = [x for x in scs if pd.notna(x)]
        meta[t] = {"regime": regime, "top3": ",".join(top3),
                   "sc_mean": float(np.mean(scs_ok)) if scs_ok else np.nan,
                   "sc_max": float(np.nanmax([crowd.get((t, p), np.nan) for p in top3])),
                   "stable": (prev_top3 is None or set(top3) == set(prev_top3)),
                   "n_common": (3 if prev_top3 is None else len(set(top3) & set(prev_top3)))}
        rows, hn = [], {}
        for ind_name, syms in tg.items():
            if not syms:
                continue
            w = B.industry_weights(cand, syms)
            for s in syms:
                hn[s] = ind_name
                rows.append({"date": t, "instrument": s, "weight": float(w[s] / B.N_IND)})
        if rows:
            frames.append(pd.DataFrame(rows))
        held, prev_top3 = hn, top3
    sig = pd.concat(frames, ignore_index=True)
    mt = pd.DataFrame(meta).T.rename_axis("date").reset_index()
    mt["date"] = pd.to_datetime(mt["date"])
    return sig, mt


def main():
    labels = pd.read_parquet(LAB_FILE)
    labels.index = pd.to_datetime(labels.index)
    print(f"标签 {LAB_FILE.name}：{labels.shape[0]} 周 × {labels.shape[1]} 行业")
    B.pick_industries = make_pick(labels)               # ★ monkeypatch（冻结件零改动）
    sig, mt = build_sig_cluster()
    sig.to_parquet(OUT_SIG, index=False)
    mt.to_parquet(OUT_META, index=False)
    print(f"sig {sig.shape} → {OUT_SIG.name}；meta {mt.shape} → {OUT_META.name}")

    # ── 自检 ① 被改周数 + 逐周换入与 analysis_020 一致 ──
    mod = pd.DataFrame(_LOG["mod"])
    ref = pd.read_csv(PROJ / "01_data_analysis/analysis_020/F_trigger_detail.csv")
    ref7 = ref[ref["K"] == K][["周", "regime", "换入"]].sort_values("周").reset_index(drop=True)
    mine = mod[["周", "regime", "换入"]].sort_values("周").reset_index(drop=True)
    same = mine.equals(ref7)
    print(f"\n[自检①] 被改周数 = {len(mod)}（analysis_020 参考文献 K={K} 为 {len(ref7)}）；"
          f"逐周换入一致 = {same}")
    if not same:
        d = mine.merge(ref7, on="周", how="outer", suffixes=("_mine", "_ref"))
        print("  不一致明细（前 10）：")
        print(d[(d["换入_mine"] != d["换入_ref"]) | d["换入_mine"].isna() | d["换入_ref"].isna()]
              .head(10).to_string(index=False))
    print(f"  构成：动量 {int((mod['regime']=='momentum').sum())} / 反转 {int((mod['regime']=='reversal').sum())}")

    # ── 自检 ② 满仓周权重合计 ≈ 1.0 ──
    wsum = sig.groupby("date")["weight"].sum()
    whr = sig.groupby("date")["date"].size()
    print(f"[自检②] 全开表 {sig['date'].nunique()} 周、权重合计 "
          f"均值 {wsum.mean():.4f} / 最小 {wsum.min():.4f} / 最大 {wsum.max():.4f}；"
          f"每周股数 中位 {int(whr.median())}（应为 6）")
    # ── 自检 ③ meta 与原 top3 的差异面 ──
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    p2 = dict(zip(plan["signal_date"], plan["top3"]))
    mt["原top3"] = mt["date"].map(p2)
    changed = mt[mt["原top3"] != mt["top3"]]
    print(f"[自检③] meta 中 top3 与原版不同的周 = {len(changed)}（应 = 被改周数），"
          f"其中 stable 反转 {int(((changed['stable']) & (changed['regime']=='reversal')).sum())} 周")


if __name__ == "__main__":
    main()
