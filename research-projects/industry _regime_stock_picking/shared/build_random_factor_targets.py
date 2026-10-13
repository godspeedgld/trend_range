"""随机**因子集**对照目标生成（analysis_007 专用）—— 与 strategy_004 的骨架全同，只换"因子的身份"。

与 analysis_004 的 `build_random_targets.py` 的区别：
  · analysis_004 随机化的是**打分**（复合分 → uniform 随机分）→ 答"选股层有没有 alpha"
  · 本文件随机化的是**因子**（把 3 个新槽位换成库里随机抽的因子）→ 答"方案 B 挑的这 3 个排在哪"

骨架（与 strategy_004 的 b6 逐项对齐）：
  · 行业层：复用 `weekly_plan.parquet`（regime → top3、exposure 完全相同）
  · 候选池：当周 top3 行业内、且**六因子中至少一个非 NaN**（= b6 的 `dropna(subset=['score'])` 同款）
  · 打分：`mean(rank_pct(因子ᵢ × 方向ᵢ))`；**槽位 = [turn_ratio, px_ma20, ?1, liq_amount, ?2, ?3]**
          三个固定槽的方向恒为 −1；三个随机槽用 analysis_005 扫描出的**该因子最优方向**
          （与 R076/R221/R222 当初被选中的口径一致 ⇒ 随机因子也拿到"最好的一面"，是更严的零假设）
  · 选股：行业内取 2、缓冲 top-6 保老仓（保序 dict）；权重行业内 1/vol 归一 × exposure ÷ 3

用法：python shared/build_random_factor_targets.py --seed 1001
      或 from build_random_factor_targets import build_random_factor; tgts, picks = build_random_factor(seed)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_weekly_targets import (  # noqa: E402  ★ 复用冻结函数
    BUF_MULT, CACHE, N_IND, N_PER_IND, WAREHOUSE, industry_weights,
)

PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
PLAN = CACHE / "weekly_plan.parquet"
A005 = Path(__file__).resolve().parents[1] / "01_data_analysis/analysis_005/scan_metrics.csv"

FIXED3 = ["turn_ratio", "px_ma20", "liq_amount"]     # 固定槽（基线骨架），方向恒 −1
EXCLUDE = ["breakdown_5w_smooth", "price_volume_corr_5w_confirm_volume",
           "obv_slope_5w_confirm_volume"]            # 方案 B 挑中的 3 个，不参与随机池


def load_pool() -> tuple[list[str], dict]:
    """随机池 = 库 512 因子（剔除方案 B 的 3 个）+ 每个因子的方向（取自 analysis_005 扫描）。"""
    sc = pd.read_csv(A005, index_col=0)
    dirs = {c: int(d) for c, d in zip(sc.index, sc["方向"])}
    pool = [c for c in sc.index if c not in EXCLUDE]
    return pool, dirs


def _load_panel(cols: list[str], base: pd.DataFrame | None = None) -> pd.DataFrame:
    panel = base if base is not None else pd.read_parquet(PANEL)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    con.register("k", panel[["date", "symbol"]].rename(columns={"symbol": "instrument"}))
    sel = ", ".join(f'f."{c}"' for c in cols)
    got = con.execute(f"""SELECT f.date, f.instrument AS symbol, {sel}
        FROM v_factor_1w f JOIN k ON f.instrument=k.instrument AND f.date=k.date""").df()
    con.close()
    got["date"] = pd.to_datetime(got["date"])
    return panel.merge(got, on=["date", "symbol"], how="left")


def build_random_factor(seed: int, pool: list[str], dirs_map: dict,
                        panel_base: pd.DataFrame | None = None) -> tuple[pd.DataFrame, list[str]]:
    """返回 (周频目标表, 本 seed 抽中的 3 个随机因子)。`panel_base` 可预载以省去重复读盘。"""
    rng = np.random.default_rng(seed)
    rnd3 = list(rng.choice(np.array(pool), size=3, replace=False))
    fac = FIXED3[:2] + [rnd3[0]] + [FIXED3[2]] + [rnd3[1], rnd3[2]]   # 槽位顺序 = b6 的六槽
    direction = {"turn_ratio": -1, "px_ma20": -1, "liq_amount": -1,
                 **{c: dirs_map[c] for c in rnd3}}

    panel = _load_panel(rnd3, panel_base)
    valid = panel[fac].notna().any(axis=1)
    plan = pd.read_parquet(PLAN)
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    positions: dict[str, str] = {}
    prev_top3, rows = None, []
    keep_n = int(N_PER_IND * BUF_MULT)
    for r in plan.itertuples():
        t = r.signal_date
        day = panel_by_day.get(t)
        if day is None:
            continue
        top3 = [x for x in str(r.top3).split(",") if x]
        exposure = 1.0 if (prev_top3 is None or set(top3) == set(prev_top3)) else 0.0
        cand = day[day["ind_name"].isin(top3) & valid.reindex(day.index, fill_value=False)].copy()
        exec_date = cand["exec_date"].iloc[0] if len(cand) else None
        new_pos: dict[str, str] = {}
        if len(cand):
            cand["score"] = pd.concat([cand[c].mul(direction[c]).rank(pct=True) for c in fac],
                                      axis=1).mean(axis=1)
            for ind in top3:
                sub = cand[cand["ind_name"] == ind].dropna(subset=["score"]).sort_values(
                    ["score", "symbol"], ascending=[False, True])
                if sub.empty:
                    continue
                ranked = sub["symbol"].tolist()
                top_keep = set(ranked[:keep_n])
                picks = [s for s in positions if positions[s] == ind and s in top_keep][:N_PER_IND]
                for s in ranked:
                    if len(picks) >= N_PER_IND:
                        break
                    if s not in picks:
                        picks.append(s)
                w = industry_weights(cand, picks)
                for s in picks:
                    new_pos[s] = ind
                    rows.append({"signal_date": t, "exec_date": exec_date, "symbol": s,
                                 "ind_name": ind, "weight": float(exposure * w[s] / N_IND)})
        positions = new_pos
        prev_top3 = top3
    return pd.DataFrame(rows), rnd3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1001)
    a = ap.parse_args()
    pool, dirs_map = load_pool()
    tgts, rnd3 = build_random_factor(a.seed, pool, dirs_map)
    out = CACHE / f"weekly_targets_randfac_{a.seed}.parquet"
    tgts.to_parquet(out, index=False)
    print(f"[randfac seed={a.seed}] 随机因子 {rnd3} | {len(tgts):,} 行 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
