"""策略参考实现模板（时序 CTA：开仓 / 止损 / 止盈）。

复制本文件到 02_strategy_logic/reference_implementation.py 后填空。
本模板是"可审计的信号生成"骨架：读外部 OHLC → 计算 entry/stop/target → 产出 direction(1/-1/0)。
strategy.py（04_backtest_strategy/）是其可跑版本，把这里的方向逻辑写进 signal_log.jsonl。

check_strategy_logic.py 会检查：函数定义、开仓/止损/止盈函数命名、direction/long/short、参数定义。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# ════════════════════════════════════════════════════════════
# 参数区（集中可见，对齐 strategy_summary.md §7）
# ════════════════════════════════════════════════════════════
PARAMS = {
    "fast_window": 5,       # 快线窗口
    "slow_window": 20,      # 慢线窗口
    "atr_period": 14,       # ATR 周期
    "atr_mult": 2.0,        # 止损倍数 k
    # "rsi_period": 14,     # 震荡态反转参数（按需启用）
    # "max_hold": 20,       # 时间强制退出（按需启用）
}


# ── 指标 ────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    """ATR(period)：TR 的 EMA（Wilder）。"""
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ── 1. 开仓信号 ─────────────────────────────────────────
def entry_signal(df: pd.DataFrame, p: dict) -> pd.Series:
    """返回开仓方向意图（+1 多 / -1 空 / 0）。

    示例：双均线交叉。替换为研报实际信号（动量/突破/RSI/Kalman...）。
    若研报有市场状态门控，在此判断（趋势态才返回趋势方向）。
    """
    fast = df["close"].rolling(p["fast_window"]).mean()
    slow = df["close"].rolling(p["slow_window"]).mean()
    sig = pd.Series(0, index=df.index)
    sig[fast > slow] = 1
    sig[fast < slow] = -1
    return sig


# ── 2. 止损 ─────────────────────────────────────────────
def stop_loss(position: int, entry_price: float, ext: pd.Series, atr_val: float,
              p: dict, since_high: float | None = None, since_low: float | None = None) -> bool:
    """是否触发止损。

    支持：固定百分比 / ATR 静态 / ATR 移动（吊灯）。按 strategy_summary.md §5 选一种。
    - ATR 静态：止损价 = entry_price ∓ k*ATR
    - ATR 移动：止损价 = 持仓期最高/最低 ∓ k*ATR（传 since_high/since_low）
    触发返回 True，外层把 direction 置 0。
    """
    k = p["atr_mult"]
    if position > 0:  # 多单
        ref = since_high if since_high is not None else entry_price
        stop_price = ref - k * atr_val
        return ext <= stop_price
    if position < 0:  # 空单
        ref = since_low if since_low is not None else entry_price
        stop_price = ref + k * atr_val
        return ext >= stop_price
    return False


# ── 3. 止盈 / 退出 ──────────────────────────────────────
def take_profit(position: int, bars_held: int, p: dict, reason: str | None = None) -> bool:
    """是否触发止盈/退出。

    示例：时间强制退出（超 max_hold 平仓）。替换为研报实际退出
    （移动止盈已在 stop_loss 的 since_high 口径覆盖；震荡态反转退出另算）。
    """
    max_hold = p.get("max_hold")
    if max_hold and bars_held >= max_hold:
        return True
    return False


# ── 主：把三要素编排成逐根 direction ────────────────────
def compute_direction(df: pd.DataFrame, p: dict = None) -> pd.Series:
    """逐根 bar 产出 direction(1/-1/0)：开仓信号 + 止损 + 止盈。

    df 需含 open/high/low/close（按日期升序）。返回与 df.index 对齐的 Series。
    本函数是 reference 实现；strategy.py 用同样逻辑写 signal_log.jsonl。
    """
    p = p or PARAMS
    df = df.sort_index().copy()
    a = atr(df["high"], df["low"], df["close"], p["atr_period"])
    intent = entry_signal(df, p)

    direction = pd.Series(0, index=df.index, dtype=int)
    position = 0
    entry_price = 0.0
    bars_held = 0
    since_high = since_low = None

    for i, (idx, row) in enumerate(df.iterrows()):
        # 优先判断已有持仓的退出（止损/止盈），用当日极值
        if position != 0:
            bars_held += 1
            if position > 0:
                since_high = max(since_high or row["high"], row["high"])
            else:
                since_low = min(since_low or row["low"], row["low"])
            if stop_loss(position, entry_price, row["low"] if position > 0 else row["high"],
                         a.loc[idx], p, since_high, since_low) or take_profit(position, bars_held, p):
                position = 0
                entry_price = 0.0
                bars_held = 0
                since_high = since_low = None

        # 空仓时按开仓信号进场（次日开盘口径由 strategy.py 处理执行滞后）
        if position == 0:
            sig = int(intent.loc[idx])
            if sig != 0:
                position = sig
                entry_price = row["close"]
                bars_held = 0
                since_high = since_low = row["close"]

        direction.loc[idx] = position
    return direction


# ── 入口：读 OHLC → direction → 写 signal_log.jsonl（strategy.py 复用）──
def build_signal_log(df: pd.DataFrame, symbol: str, p: dict = None) -> list[dict]:
    """产出 signal_log.jsonl 记录列表：{"date","signals":{symbol:{"factor":0,"direction":...}}}。"""
    d = compute_direction(df, p or PARAMS)
    rows = []
    for idx, pos in d.items():
        rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "signals": {symbol: {"factor": 0.0, "direction": int(pos)}},
        })
    return rows


if __name__ == "__main__":
    # 自测：读外部 OHLC CSV → 方向序列
    # df = pd.read_csv("/path/to/market_data.csv", parse_dates=["date"]).set_index("date")
    # sig = compute_direction(df)
    # print(sig.value_counts())
    pass
