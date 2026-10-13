"""strategy_004 · 迭代四（选股层换成 analysis_006 的 **6 因子** = 方案 B）—— 权重引擎的策略文件。

按 skill 模板 `.claude/skills/skill-research-assistant/templates/weight_strategy.py` 的 4 个可替换点生成；
策略逻辑复用在 `shared/`（只 import 不内联）。

【与基线 `../backtest_strategy_baseline/strategy.py` 的**唯一差别**】选股层的因子集合：
    基线      ：四因子 `turn_ratio / px_ma20 / mom_20 / liq_amount`，方向恒 −1（云端原版·恒反转）
    本迭代    ：六因子（方案 B）—— `mom_20` **换成** `breakdown_5w_smooth`(R076, +1)，
                再加 `price_volume_corr_5w_confirm_volume`(R221, −1) / `obv_slope_5w_confirm_volume`(R222, −1)
                ← `shared/build_weekly_targets_b6.py`（**新增文件**，不改冻结的 build_weekly_targets.py）
  行业层 / 调仓 / 缓冲 / 权重 / 稳定性过滤**全部不动**；复合方式（行业内 rank(pct) 等权平均）也不动。

【为什么用权重引擎】本策略对标云端 bigtrader `handle_data_weight_based`；实测同一份 targets
  权重引擎与信号引擎可差到**符号相反** ⇒ 必须用权重引擎 `local_weight_backtest.py`。

运行：`python strategy.py`（产出 targets 并打印引擎命令）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # industry _regime_stock_picking
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
sys.path.insert(0, str(SHARED))

from build_weekly_targets import N_IND, industry_weights, pick_industries      # noqa: E402
from build_weekly_targets_b6 import (                                          # noqa: E402 ★ 本迭代的差别
    DIRS6, build_targets6, factor_directions6, load_panel6,
)
from expand_targets_daily import expand_to_daily                               # noqa: E402

MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"   # 原始价行情（兼作交易日历）
OUT = CACHE / "targets_daily_b6_indpre.parquet"


# ═══════════════════════════════════════════════
# 接口②：选股 + 权重（★ 核心可替换点 = 6 因子复合）
# ═══════════════════════════════════════════════
def pick(cand: pd.DataFrame, ctx: dict, params: dict) -> pd.DataFrame:
    """单个信号日的选股 + 权重，返回 DataFrame[instrument, weight]（weight 全 0 = 空仓）。"""
    top3, _regime = pick_industries(ctx["industry_day"], ctx["t_prime"])
    dirs = factor_directions6()                                  # ← 6 因子，方向固定
    targets = build_targets6(cand, top3, dirs, ctx["held"])      # ← 6 因子复合分 + 缓冲

    # 接口④：稳定性过滤 —— 本周 3 行业与上周完全相同才满仓
    exposure = 1.0 if (ctx["prev_top3"] is None or set(top3) == set(ctx["prev_top3"])) else 0.0

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
          calendar: pd.DatetimeIndex) -> pd.DataFrame:
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    prev_top3, held, frames = None, {}, []
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), panel_by_day.get(t)
        if day is None or cand is None:
            continue
        ctx = {"industry_day": day, "t_prime": float(regi.at[t, "T_prime"]),
               "held": held, "prev_top3": prev_top3}
        r = pick(cand, ctx, {})
        if not r.empty:
            r.insert(0, "date", t)
            frames.append(r)
        held, prev_top3 = ctx["held_next"], ctx["top3"]

    sig = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame(columns=["date", "instrument", "weight"]))
    return expand_to_daily(sig, calendar)           # 接口③


def main() -> int:
    panel = load_panel6()
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))

    tgts = build(panel, ind, reg, cal)
    tgts.to_parquet(OUT, index=False)
    d = pd.to_datetime(tgts["date"])
    print(f"[b6] targets: {len(tgts):,} 行 / {tgts['date'].nunique()} 交易日 / "
          f"{d.min().date()}~{d.max().date()} → {OUT}")

    engine = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
    print("\n跑引擎（权重引擎）：")
    print(f"  python '{engine}' '{PROJ}' \\")
    print(f"      --market-data '{MARKET}' --targets '{OUT}' \\")
    print(f"      --output-dir '{HERE}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
