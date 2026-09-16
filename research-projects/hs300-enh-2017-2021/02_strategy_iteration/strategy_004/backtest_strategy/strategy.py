"""strategy_004 — 豆粕期货·平台突破 + 1×ATR 静态止损（时序 CTA，单标的）。

迭代四相对迭代三的变化：
  - 标的：沪深300成分股组合 → **豆粕主力连续（单一期货）**
  - 数据：本地 k_data.db 导出 _fut_m_d.csv（2000-07 ~ 2026-06，换月平滑连续价）
  - 引擎：local_portfolio_backtest（多仓位组合）→ **local_backtest（时序单标的事件驱动）**
  - 开仓：平台突破（转折点+HSAR+突破3%，算法与迭代一~三完全一致）→ t收盘确认
    t+1 开盘入场（引擎语义；突破价≈次日开盘附近的突破水平）
  - 平仓：**1×ATR 静态止盈止损**（atr_static：入场价 ± k×ATR，日内 high/low 命中即成交，
    跳空取开盘价）——无 45 天持有、无 10% 回撤（迭代一的股票规则不适用期货单标的）
  - 方向：多头突破做多；allow_short 由引擎参数控制（平台突破向上→只做多）

铁律：严禁未来数据。entry 信号只用 ≤t 数据（转折点/阻力位在 252 日窗口内计算）。
本文件只 import 共享算法，不内联。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[3]
SHARED = PROJECT / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo import turning_points, resistance_level, PARAMS as BREAK_PARAMS  # noqa: E402

LOOKBACK = 252          # 阻力位回溯一年（同迭代一~三）


def build_strategy(df: pd.DataFrame) -> dict:
    """local_backtest 引擎接口：返回 spec（entry_long 数组 + ATR 静态止损）。"""
    # 数据按日期升序（k_data 导出已排序，防御性再排）
    df = df.sort_values("date").reset_index(drop=True)
    n = len(df)

    # 逐日检测平台突破（与迭代一完全同算法：转折点 N20/K1/P4 + HSAR M10/Q2 + 突破3%）
    entry_long = pd.Series(False, index=df.index)
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    p = BREAK_PARAMS
    ma = pd.Series(c).rolling(p["bb_window"]).mean().to_numpy()
    sd = pd.Series(c).rolling(p["bb_window"]).std().to_numpy()
    ub = ma + p["bb_k"] * sd
    lb = ma - p["bb_k"] * sd

    # 复用共享模块的逐窗口转折点（numpy 版，与 plateau_algo.turning_points 等价）
    from vol_enhance_v2 import tp_window_np  # noqa: E402  共享实现，不内联

    for b in range(LOOKBACK, n):
        a = b - LOOKBACK + 1
        hp, _ = tp_window_np(c, h, lo, ub, lb, a, b, p["bb_window"], p["p_clear"])
        res = resistance_level(hp, p)
        if res is None:
            continue
        if c[b] > res * (1 + p["break_pct"]):
            entry_long.iloc[b] = True

    return {
        "entry_long": entry_long,
        "allow_short": False,                    # 平台突破向上 → 只做多
        "stop": {
            "type": "atr_static",               # 1×ATR 静态止盈止损（入场价 ± k×ATR）
            "atr_period": 14,
            "k": 1.0,
        },
        "sizing": {"type": "fixed"},            # 满仓（pos_size=1）
    }
