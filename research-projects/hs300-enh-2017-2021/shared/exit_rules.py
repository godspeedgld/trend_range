"""策略离场规则集（单一事实源，可扩展多规则）。

离场规则统一在此定义，供两处共用（同一规则只实现一次）：
  ① 策略 exit_check —— 回测引擎运行时逐日判定（是否触发平仓）
  ② vol_enhance_v2._sim_exit_return —— 预计算事件标签（模拟实际离场收益）

每类离场规则一个函数，签名统一为判定条件；peak 的更新时序由调用方管理
（引擎/模拟均在判定之后更新，滞后一日），本文件只判条件。

现有规则：exit_triggered —— 滚动回撤 % + 最大持有自然日（长江研报 §1.3）。
后续新离场规则（如 ATR 吊灯止损等）在此新增函数即可，策略与标签模拟自动共用。
"""
from __future__ import annotations

import pandas as pd


def exit_triggered(peak, close, entry_date, cur_date,
                   trail_dd: float = 0.10, max_hold: int = 45) -> bool:
    """离场条件判定。返回 True = 应离场（回撤 trail_dd 或 max_hold 自然日，先到者）。

    参数：
      peak       入场后最高收盘价（由调用方维护，判定后更新）
      close      当前收盘价
      entry_date / cur_date  入场日 / 当前日（自然日持有期）
    """
    if peak and peak > 0 and close / peak - 1.0 < -trail_dd:
        return True
    return (pd.Timestamp(cur_date) - pd.Timestamp(entry_date)).days > max_hold
