"""strategy_008 · **对照组 = strategy_007**（反向量能闸门）—— 权重引擎的策略文件。

本文件是 strategy_007 冻结件的**只读副本**（迭代铁律：不得改动 007 的任何产物），
仅把输出 targets 改名以免覆盖 007 的冻结件。用于 008 的自检（须逐值回到 4.5663）。

原 docstring：strategy_007 · 迭代七（反向量能闸门）—— 权重引擎的策略文件。

按 skill 模板 `.claude/skills/skill-research-assistant/templates/weight_strategy.py`
（**权重引擎**模板）的 4 个可替换点生成；策略逻辑复用在 `shared/`（只 import 不内联）。

【与基线（strategy_002 冻结件）的**唯一差别】**
    基线      ：exposure = 稳定性过滤（本周 top3 集合 ≠ 上周 → 空仓一周）
    本迭代    ：exposure = 稳定性过滤 AND NOT(动量周 AND top3 无量能确认 sc<2)
                —— 反向量能闸门（analysis_009-D：nav 级 3.56→4.08~4.24x，本迭代引擎验证）
    其余（行业层 T′ 选 top3 / 四因子恒反转选股 / 缓冲 / 权重 / 成本）**一字不动**。

【机制（analysis_009）】动量周失败集中在「无量能确认」的周（−0.15%/周 vs 有量能 +0.66%/周）；
  毒药格=动量·刚开仓·无量能 −2.03%/周。拥挤度=活跃=主升（剔除拥挤动量的方向已被 009 否决），
  正确用法=关掉无量能的动量周（量能是确认信号，不是剔除信号）。
  闸门与稳定性过滤正交：前者挡「名单没变但量能没确认」，后者挡「名单在变」。

【拥挤度信号】`shared/build_crowding_signals.py`（009 口径工程化落盘）
  → shared/_cache/industry_crowding_weekly.parquet：(week, ind, signal_count)。
  6 因子 = {vol, amt, turn, ×bias} 各自 104 周滚动百分位；触发 ≥60 分位；sc = top3 平均信号数。

【为什么用权重引擎】对标云端 bigtrader `handle_data_weight_based`；同一份 targets
  权重引擎与信号引擎可差到符号相反 ⇒ 必须用 `local_weight_backtest.py`。

运行：`python strategy.py`（产出 targets 并打印引擎命令）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # industry _regime_stock_picking
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
sys.path.insert(0, str(SHARED))

from build_weekly_targets import (           # noqa: E402  ★ 逻辑复用，不内联
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily   # noqa: E402

MODE = "baseline"                            # 恒反转四因子（云端原版），与基线一致
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"   # 原始价行情（兼作交易日历）
CROWD = CACHE / "industry_crowding_weekly.parquet"
OUT = CACHE / "targets_daily_gate007_base_indpre.parquet"

SC_THR = 2.0        # 闸门阈值：动量周 top3 平均信号数 < 2 → 空仓（analysis_009-D 主口径）


# ═══════════════════════════════════════════════
# 接口②：选股 + 权重（★ 核心可替换点 = 反向量能闸门）
# ═══════════════════════════════════════════════
def pick(cand: pd.DataFrame, ctx: dict, params: dict) -> pd.DataFrame:
    """单个信号日的选股 + 权重，返回 DataFrame[instrument, weight]（weight 全 0 = 空仓）。"""
    top3, regime = pick_industries(ctx["industry_day"], ctx["t_prime"])
    dirs = factor_directions(params["mode"], regime)
    targets = build_targets(cand, top3, dirs, ctx["held"])      # 缓冲：老仓在前 6 名内保留

    # 接口④-1：稳定性过滤（基线原样）
    exposure = 1.0 if (ctx["prev_top3"] is None or set(top3) == set(ctx["prev_top3"])) else 0.0
    # 接口④-2：★ 反向量能闸门（本迭代唯一新增）—— 动量周 & top3 无量能确认 → 空仓
    if regime == "momentum" and exposure == 1.0:
        sc = [ctx["crowd"].get((ctx["date"], p), np.nan) for p in top3]
        sc = [x for x in sc if pd.notna(x)]
        if sc and sum(sc) / len(sc) < params["sc_thr"]:
            exposure = 0.0

    rows, held_next = [], {}
    for ind_name, syms in targets.items():
        if not syms:
            continue
        w = industry_weights(cand, syms)                        # 行业内 1/vol 归一（冻结件）
        for s in syms:
            held_next[s] = ind_name                             # ★ 老仓跨空仓周延续
            rows.append({"instrument": s, "weight": float(exposure * w[s] / N_IND)})
    ctx["held_next"] = held_next
    ctx["top3"] = top3
    return pd.DataFrame(rows, columns=["instrument", "weight"])


# ═══════════════════════════════════════════════
# 串联：① 信号日 → ② 逐日 pick → ③ 展开到每个交易日
# ═══════════════════════════════════════════════
def build(panel: pd.DataFrame, ind: pd.DataFrame, reg: pd.DataFrame,
          calendar: pd.DatetimeIndex, crowd: dict, sc_thr: float = SC_THR) -> pd.DataFrame:
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    prev_top3, held, frames, n_gated = None, {}, [], 0
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), panel_by_day.get(t)
        if day is None or cand is None:
            continue
        ctx = {"industry_day": day, "t_prime": float(regi.at[t, "T_prime"]),
               "held": held, "prev_top3": prev_top3, "crowd": crowd, "date": t}
        r = pick(cand, ctx, {"mode": MODE, "sc_thr": sc_thr})
        if not r.empty:
            r.insert(0, "date", t)
            frames.append(r)
        held, prev_top3 = ctx["held_next"], ctx["top3"]

    sig = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame(columns=["date", "instrument", "weight"]))
    return expand_to_daily(sig, calendar)           # 接口③


def main() -> int:
    panel = pd.read_parquet(PANEL)
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    crowd_df = pd.read_parquet(CROWD)
    crowd = {(w, i): float(s) for w, i, s in zip(
        pd.to_datetime(crowd_df["week"]), crowd_df["ind"], crowd_df["signal_count"])}
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))

    tgts = build(panel, ind, reg, cal, crowd)
    tgts.to_parquet(OUT, index=False)
    d = pd.to_datetime(tgts["date"])
    print(f"[crowdgate] targets: {len(tgts):,} 行 / {tgts['date'].nunique()} 交易日 / "
          f"{d.min().date()}~{d.max().date()} → {OUT}")

    engine = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
    print("\n跑引擎（权重引擎）：")
    print(f"  python '{engine}' '{PROJ}' \\")
    print(f"      --market-data '{MARKET}' --targets '{OUT}' \\")
    print(f"      --output-dir '{HERE}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
