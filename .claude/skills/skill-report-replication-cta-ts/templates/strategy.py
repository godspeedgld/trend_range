"""策略规格模板（时序 CTA 事件驱动引擎）。

复制到 03_backtest_strategy/strategy.py 后填空。本文件只定义 build_strategy(df)->spec，
引擎（scripts/local_backtest.py）按 spec 跑事件驱动状态机（入场事件 + ATR 吊灯止损即时触发）。
指标/信号的可审计实现放 reference_implementation.py；此处可直接 import 复用。
"""

import pandas as pd

# 参数区（对齐 backtest_features.md）
PARAMS = {
    "fast_window": 5,
    "slow_window": 20,
    "atr_period": 14,
    "atr_k": 2.0,
}


def _atr(high, low, close, period):
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build_strategy(df):
    """df: 单品种 OHLC DataFrame（含 open/high/low/close）。返回 spec 喂事件驱动引擎。"""
    p = PARAMS
    fast = df["close"].rolling(p["fast_window"]).mean()
    slow = df["close"].rolling(p["slow_window"]).mean()
    # 入场事件：穿越当根
    entry_long = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    entry_short = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    return {
        "entry_long": entry_long,
        "entry_short": entry_short,
        "stop": {"type": "atr_chandelier", "atr_period": p["atr_period"], "k": p["atr_k"]},
        "sizing": {"type": "full"},
        "allow_short": True,
    }
