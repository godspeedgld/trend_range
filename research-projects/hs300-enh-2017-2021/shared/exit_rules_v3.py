"""离场规则 v3 —— 吊灯止盈 + 固定止损（strategy_005 更新一，用户指定）。

承接链：exit_rules.py(v1, 45自然日, 冻结) → exit_rules_v2.py(30交易日, 冻结) → 本文件。
v3 **完全替代** v1/v2 的"回撤% + 持有时间"两条规则：

  ① 固定止损：close < 突破价格 × (1 − stop_pct)，stop_pct=5%
  ② 吊灯止盈：close < 突破后最高价 − atr_mult × ATR(14)，atr_mult=2

口径约定（调用方 strategy.py 负责取数，本文件只判条件）：
  · 突破价格   = 突破（信号）日收盘价
  · 突破后最高价 = 自突破日起最高 high（含突破日）
  · close      = 当前日收盘（收盘决策，次日开盘执行）
  · ATR(14)    = 当前日 Wilder ATR（shared/atr14_precompute.py 预计算，≤t 数据）
"""
from __future__ import annotations


def exit_triggered_v3(close, breakout_price, post_high, atr14,
                      stop_pct: float = 0.05, atr_mult: float = 2.0):
    """返回 (应离场: bool, 触发规则: None/'fixed_stop'/'chandelier'）。

    ATR 缺失（NaN/None，上市不足14根等）→ 只判固定止损，吊灯条件跳过。
    """
    if breakout_price and breakout_price > 0 and close < breakout_price * (1 - stop_pct):
        return True, "fixed_stop"
    if atr14 is not None and atr14 == atr14 and atr14 > 0:      # NaN 安全
        if post_high and close < post_high - atr_mult * atr14:
            return True, "chandelier"
    return False, None
