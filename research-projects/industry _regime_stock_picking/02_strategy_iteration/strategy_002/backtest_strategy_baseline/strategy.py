"""strategy_001 · baseline（云端原版 / 恒反转，云端对齐口径）—— 权重引擎的**策略文件**。

按 skill 模板 `.claude/skills/skill-research-assistant/templates/weight_strategy.py`
（**权重引擎**模板）的 4 个可替换点生成；策略逻辑复用在 `shared/`（只 import 不内联）。

【模板 4 点 → 本策略】
  ① config_signal_dates  每周最后一个交易日
  ② pick                 行业层：变盘指数 T′<0 → 240 日动量前 3 行业；T′>0 → 60 日反转前 3 行业
                         选股层：行业内四因子复合百分位排名取前 2 + 持仓缓冲（老仓在前 6 名内保留）
                         权重：行业内 20 周波动率**倒数**归一（风险平价）× 敞口 ÷ 行业数
                         ← `shared/build_weekly_targets.py`：pick_industries / build_targets /
                           industry_weights / factor_directions
  ③ config_expand        信号日目标 → 逐交易日 ← `shared/expand_targets_daily.py::expand_to_daily`
  ④ 空仓                 稳定性过滤：本周 3 行业与上周**不完全相同** → exposure=0
                         （该周目标权重全为 0 → 引擎看到 weight=0 → 清仓）

【与 `../backtest_regime_cloud_repro/strategy.py` 的唯一差别】`MODE`
    `"baseline"` ← 本文件：**恒反转**（四因子方向恒取负，与 regime 无关）= 云端原版
    `"regime"`     迭代一：选股层四因子方向随 regime 镜像（动量期取正 / 反转期取负）

【为什么用权重引擎】本策略对标云端 bigtrader `handle_data_weight_based`（每日 `order_target_percent`
  对齐目标 + 卖掉目标外持仓）。实测**同一份 targets**：权重引擎 +260.0% / 夏普 0.904；
  信号引擎走 5 接口那条路给不出这套绩效 ⇒ 必须用权重引擎 `local_weight_backtest.py`。

运行：`python strategy.py`（产出 `targets_daily_baseline_indpre.parquet` 并打印引擎命令）
"""
from __future__ import annotations

import subprocess
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

# ═══════════════════════════════════════════════
# 本迭代参数
# ═══════════════════════════════════════════════
MODE = "baseline"                            # ← 与迭代一目录的唯一差别
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"     # 周频因子窗口 + prefactors 行业源（全市场）
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"   # 原始价行情（兼作交易日历）
OUT = CACHE / "targets_daily_baseline_indpre.parquet"


# ═══════════════════════════════════════════════
# 接口②：选股 + 权重（★ 核心可替换点）
# ═══════════════════════════════════════════════
def pick(cand: pd.DataFrame, ctx: dict, params: dict) -> pd.DataFrame:
    """单个信号日的选股 + 权重，返回 DataFrame[instrument, weight]（weight 全 0 = 空仓）。

    ctx = {"industry_day": 当日行业指数行, "t_prime": T′ 值,
           "held": 老仓 {symbol: ind_name}, "prev_top3": 上周 3 行业}
    ★ 偏离模板签名之处：本策略有**跨周缓冲记忆**（老仓 + 上周行业），故 ctx 需携带这两项；
      并且 pick 会把本周目标写回 `ctx["held_next"]`，供下一周使用（模板默认策略无状态，不需要）。
    """
    top3, regime = pick_industries(ctx["industry_day"], ctx["t_prime"])
    dirs = factor_directions(params["mode"], regime)
    targets = build_targets(cand, top3, dirs, ctx["held"])      # 缓冲：老仓在前 6 名内保留

    # 接口④：稳定性过滤 —— 本周 3 行业与上周完全相同才满仓
    exposure = 1.0 if (ctx["prev_top3"] is None or set(top3) == set(ctx["prev_top3"])) else 0.0

    rows, held_next = [], {}
    for ind_name, syms in targets.items():
        if not syms:
            continue
        w = industry_weights(cand, syms)                        # 行业内 1/vol 归一
        for s in syms:
            held_next[s] = ind_name                             # ★ 老仓跨空仓周延续（不因 exposure=0 清空）
            rows.append({"instrument": s, "weight": float(exposure * w[s] / N_IND)})
    ctx["held_next"] = held_next      # 供下周缓冲用
    ctx["top3"] = top3                # 供下周比稳定性用
    return pd.DataFrame(rows, columns=["instrument", "weight"])


# ═══════════════════════════════════════════════
# 串联：① 信号日 → ② 逐日 pick → ③ 展开到每个交易日
# ═══════════════════════════════════════════════
def build(mode: str, panel: pd.DataFrame, ind: pd.DataFrame, reg: pd.DataFrame,
          calendar: pd.DatetimeIndex) -> pd.DataFrame:
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    prev_top3, held, frames = None, {}, []
    for t in sorted(panel["date"].unique()):        # 接口①：信号日 = 面板里出现的信号日（周频）
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), panel_by_day.get(t)
        if day is None or cand is None:
            continue
        ctx = {"industry_day": day, "t_prime": float(regi.at[t, "T_prime"]),
               "held": held, "prev_top3": prev_top3}
        r = pick(cand, ctx, {"mode": mode})
        if not r.empty:
            r.insert(0, "date", t)
            frames.append(r)
        held, prev_top3 = ctx["held_next"], ctx["top3"]      # 状态更新（同 shared 流水线）

    sig = (pd.concat(frames, ignore_index=True) if frames
           else pd.DataFrame(columns=["date", "instrument", "weight"]))
    return expand_to_daily(sig, calendar)           # 接口③


# ═══════════════════════════════════════════════
def main() -> int:
    panel = pd.read_parquet(PANEL)
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))

    tgts = build(MODE, panel, ind, reg, cal)
    tgts.to_parquet(OUT, index=False)
    print(f"[{MODE}] targets: {len(tgts):,} 行 / {tgts['date'].nunique()} 交易日 → {OUT}")

    engine = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
    print("\n跑引擎（权重引擎）：")
    print(f"  python {engine} '{PROJ}' \\")
    print(f"      --market-data '{MARKET}' --targets '{OUT}' \\")
    print(f"      --output-dir '{HERE}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
