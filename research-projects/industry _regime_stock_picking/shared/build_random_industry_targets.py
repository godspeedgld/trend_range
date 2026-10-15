"""随机**行业**对照目标生成（analysis_010 / A2 臂专用）—— 块自助法（block bootstrap）。

要回答的问题：基线绩效里「**行业层**（变盘指数选 top3）」贡献多少？
已有臂：A0 基线 3.600x / A1 去空仓 2.369x（strategy_006）/ A3 随机选股 中位 2.199x（analysis_004）。
本文件 = **A2：随机行业**——摧毁「选哪 3 个行业」的信息，其余全部保持真实。

设计（★ 关键：保持真实切换时间表，否则空仓过滤会退化）：
  · 切换点 = weekly_plan 里真实 top3 **集合发生变化**的周（含首周）
  · 只在切换点从「当周面板里出现的行业」中随机抽 3 个持有到下一个切换点；
    其余周沿用上周随机行业 ⇒ 随机 top3 的变化时点与真实**完全同步**
  · ⇒ exposure（稳定性过滤）日程与基线**逐周一致**（构建后 assert 校验）
  · 选股 = 真实四因子（恒反转，冻结件 build_targets/industry_weights 原样调用）+ 前 6 缓冲
  · 权重 = 行业内 1/vol 归一 × exposure ÷ 3；成本/引擎同基线

与 analysis_004（随机打分）/ analysis_007（随机因子集）的区别：
  · 004 随机化**打分**（答：选股层有无 alpha）
  · 007 随机化**因子身份**（答：方案 B 挑的 3 个因子排第几）
  · 本文件随机化**行业身份**（答：行业层选 top3 的信息值多少净值）——A2 臂

用法：from build_random_industry_targets import build_random_industry
      tgts, chk = build_random_industry(seed)   # tgts: (signal_date,symbol,weight,regime)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_weekly_targets import (  # noqa: E402  ★ 复用冻结函数
    N_IND, build_targets, factor_directions, industry_weights,
)

CACHE = Path(__file__).resolve().parent / "_cache"
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
PLAN = CACHE / "weekly_plan.parquet"


def build_random_industry(seed: int) -> tuple[pd.DataFrame, dict]:
    """一个种子的 A2 目标表。返回 (weekly_targets, 自检信息)。"""
    rng = np.random.default_rng(seed)
    plan = pd.read_parquet(PLAN)
    for c in ("signal_date", "exec_date"):
        plan[c] = pd.to_datetime(plan[c])
    panel = pd.read_parquet(PANEL)
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    rows, held, prev_real, prev_rnd = [], {}, None, None
    n_switch, mismatch = 0, 0
    for _, r in plan.sort_values("signal_date").iterrows():
        t = r["signal_date"]
        cand = panel_by_day.get(t)
        if cand is None:
            continue
        real3 = set(r["top3"].split(","))
        # 切换点判定（与基线 exposure 公式同源：集合不同 = 切换）
        if prev_real is None or real3 != prev_real:
            avail = sorted(cand["ind_name"].dropna().unique())
            # ★ 拒绝采样：随机块必须与上一块不同 —— 否则真实已切换、随机未切换，
            #   exposure 会比基线多一周满仓（20 种子 × 314 切换点必撞 ~1 次，实测踩中）
            for _ in range(50):
                rnd3 = list(rng.choice(avail, size=min(3, len(avail)), replace=False))
                if prev_rnd is None or set(rnd3) != set(prev_rnd):
                    break
            n_switch += 1
        else:
            rnd3 = prev_rnd
        # exposure 与基线同一公式、同一切换时点 → 日程一致
        exposure = 1.0 if (prev_rnd is None or set(rnd3) == set(prev_rnd)) else 0.0
        if exposure != r["exposure"]:
            mismatch += 1
        dirs = factor_directions("baseline", r["regime"])     # 恒反转（基线）
        targets = build_targets(cand, list(rnd3), dirs, held)  # 真实四因子 + 缓冲
        new_pos = {}
        for ind_name, syms in targets.items():
            if not syms:
                continue
            w = industry_weights(cand, syms)
            for s in syms:
                new_pos[s] = ind_name
                rows.append({"signal_date": t, "symbol": s, "regime": r["regime"],
                             "weight": float(exposure * w[s] / N_IND)})
        held, prev_real, prev_rnd = new_pos, real3, rnd3

    chk = {"n_switch": n_switch, "exposure_mismatch_vs_plan": mismatch}
    return pd.DataFrame(rows), chk


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1001)
    a = ap.parse_args()
    tg, chk = build_random_industry(a.seed)
    print(f"seed={a.seed}: {len(tg):,} 行 / {tg['symbol'].nunique()} 只 / 自检 {chk}")
    print(f"  满仓周权重合计: {tg.groupby('signal_date')['weight'].sum().describe().round(4).to_dict()}")
