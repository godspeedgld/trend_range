"""strategy_006 · 迭代六（去掉稳定性空仓）—— 权重引擎的策略文件。

按 skill 模板 `.claude/skills/skill-research-assistant/templates/weight_strategy.py`
（**权重引擎**模板）的 4 个可替换点生成；策略逻辑复用在 `shared/`（只 import 不内联）。

【与基线（strategy_002 冻结件）的**唯一差别】**
    基线    ：稳定性过滤 —— 本周 top3 与上周不完全相同 → exposure=0（空仓一周）
              （494 周中 313 周空仓 = 63.4%；云端原版「贡献最大」的部件）
    本迭代  ：**exposure ≡ 1.0**（每周满仓，行业层/选股/缓冲/权重/成本全部不动）

【动机（用户 2026-10-15 指令）】analysis_009 发现稳定性过滤把 63% 的周关在场外，
  其绩效贡献到底多大没有单独量化过（云端说法是"贡献最大"，但那是与**没有该过滤的旧版**
  比的口径未存档）。本迭代 = 拆出这一个变量，基线四因子不动，直接回测对比。

【为什么用权重引擎】对标云端 bigtrader `handle_data_weight_based`；同一份 targets
  权重引擎与信号引擎可差到符号相反 ⇒ 必须用 `local_weight_backtest.py`。

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

from build_weekly_targets import (           # noqa: E402  ★ 逻辑复用，不内联
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily   # noqa: E402

MODE = "baseline"                            # 恒反转四因子（云端原版），与基线一致
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"   # 原始价行情（兼作交易日历）
OUT = CACHE / "targets_daily_nostab_indpre.parquet"


# ═══════════════════════════════════════════════
# 接口②：选股 + 权重（★ 核心可替换点 = exposure ≡ 1.0）
# ═══════════════════════════════════════════════
def pick(cand: pd.DataFrame, ctx: dict, params: dict) -> pd.DataFrame:
    """单个信号日的选股 + 权重，返回 DataFrame[instrument, weight]。"""
    top3, regime = pick_industries(ctx["industry_day"], ctx["t_prime"])
    dirs = factor_directions(params["mode"], regime)
    targets = build_targets(cand, top3, dirs, ctx["held"])      # 缓冲：老仓在前 6 名内保留

    exposure = 1.0                                              # ← 唯一差别：去掉稳定性空仓

    rows, held_next = [], {}
    for ind_name, syms in targets.items():
        if not syms:
            continue
        w = industry_weights(cand, syms)                        # 行业内 1/vol 归一（冻结件）
        for s in syms:
            held_next[s] = ind_name
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
        r = pick(cand, ctx, {"mode": MODE})
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
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))

    tgts = build(panel, ind, reg, cal)
    tgts.to_parquet(OUT, index=False)
    d = pd.to_datetime(tgts["date"])
    nz = tgts[tgts["weight"] > 0]
    print(f"[nostab] targets: {len(tgts):,} 行 / {nz['date'].nunique()} 个有仓交易日 / "
          f"{d.min().date()}~{d.max().date()} → {OUT}")

    engine = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
    print("\n跑引擎（权重引擎）：")
    print(f"  python '{engine}' '{PROJ}' \\")
    print(f"      --market-data '{MARKET}' --targets '{OUT}' \\")
    print(f"      --output-dir '{HERE}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
