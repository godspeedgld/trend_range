"""随机对照目标生成（analysis_004 专用）—— 把选股层**复合分**换成【随机分】，其余全同基线。

为什么新文件：`build_weekly_targets.py` 已投产冻结（技能铁律），本文件只 **import 复用**
其函数（pick_industries / industry_weights / 常量），不改动它。

与基线逐项对齐（唯一差别 = 打分）：
  · 行业层：直接复用 weekly_plan.parquet（regime → top3、exposure 完全相同——计划文件与 mode 无关）
  · 候选池：当周 top3 行业内、且**至少一个因子非 NaN**（= 基线复合分非 NaN 的同一批候选，
            2017 年初基线无因子 → 随机也不交易，保持可比）
  · 选股：每个行业内按随机分排序取 2、缓冲 top-6 保老仓（保序 dict，跨空仓周延续）
  · 权重：行业内 1/vol_20 归一（industry_weights 同款）× exposure ÷ 3
  · 种子：`--seed`，默认 1001；rng = np.random.default_rng(seed)，每周 uniform 抽一次

用法：python shared/build_random_targets.py --seed 1001 [--out <parquet>]
      或 from build_random_targets import build_random; tgts = build_random(seed)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_weekly_targets import (  # noqa: E402  ★ 复用冻结函数，不内联修改
    CACHE, FACTORS, N_IND, N_PER_IND, BUF_MULT, industry_weights,
)

PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
PLAN = CACHE / "weekly_plan.parquet"


def build_random(seed: int) -> pd.DataFrame:
    """返回与 weekly_targets_* 同构的周频目标表（signal_date/exec_date/symbol/ind_name/weight）。"""
    rng = np.random.default_rng(seed)
    panel = pd.read_parquet(PANEL)
    plan = pd.read_parquet(PLAN)
    valid = panel[FACTORS].notna().any(axis=1)      # 基线复合分非 NaN 的候选条件
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    positions: dict[str, str] = {}                  # symbol -> ind（保序，= 基线缓冲记忆）
    prev_top3 = None
    rows = []
    keep_n = int(N_PER_IND * BUF_MULT)
    for r in plan.itertuples():
        t = r.signal_date
        day = panel_by_day.get(t)
        if day is None:
            continue
        top3 = [x for x in str(r.top3).split(",") if x]
        exposure = 1.0 if (prev_top3 is None or set(top3) == set(prev_top3)) else 0.0
        cand = day[day["ind_name"].isin(top3)
                   & valid.reindex(day.index, fill_value=False)].copy()
        exec_date = cand["exec_date"].iloc[0] if len(cand) else None
        new_pos: dict[str, str] = {}
        if len(cand):
            cand["_r"] = rng.random(len(cand))       # ★ 唯一改动：复合分 → uniform 随机分
            for ind in top3:
                sub = cand[cand["ind_name"] == ind].sort_values(
                    ["_r", "symbol"], ascending=[False, True])
                if sub.empty:
                    continue
                ranked = sub["symbol"].tolist()
                top_keep = set(ranked[:keep_n])
                picks = [s for s in positions
                         if positions[s] == ind and s in top_keep][:N_PER_IND]
                for s in ranked:
                    if len(picks) >= N_PER_IND:
                        break
                    if s not in picks:
                        picks.append(s)
                w = industry_weights(cand, picks)
                for s in picks:
                    new_pos[s] = ind
                    rows.append({"signal_date": t, "exec_date": exec_date, "symbol": s,
                                 "ind_name": ind,
                                 "weight": float(exposure * w[s] / N_IND)})
        positions = new_pos
        prev_top3 = top3
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1001)
    ap.add_argument("--out", default=None, help="默认 shared/_cache/weekly_targets_random_{seed}.parquet")
    a = ap.parse_args()
    tgts = build_random(a.seed)
    out = Path(a.out) if a.out else CACHE / f"weekly_targets_random_{a.seed}.parquet"
    tgts.to_parquet(out, index=False)
    n_full = int((tgts["weight"] > 0).groupby(tgts["signal_date"]).max().sum())
    print(f"[random seed={a.seed}] {len(tgts):,} 行 / 满仓周 {n_full} → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
