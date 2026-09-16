"""离场规则 v2 —— 承接 shared/exit_rules.py（冻结），strategy_005 新持仓口径。

exit_rules.py（strategy_001~003 依赖）已投产冻结，本文件以新增文件方式扩展：

  exit_triggered_v2 —— 10% 滚动回撤 + 最大持有 **30 个交易日**（交易口径）。

与 v1（exit_triggered）差异：v1 持有期为 45 **自然日**；v2 改交易 bar 数
（strategy_005 迭代要求"持仓时间大于 30 个交易日"）。回撤部分语义一致
（入场后最高收盘 peak → 当前收盘，跌破 -10% 触发）。

bars_held 的计数由调用方（策略 exit_check）给出：入场日之后（不含入场日）
至当前日的该标的交易 bar 数——停牌自然跳过，天然是交易口径。
"""
from __future__ import annotations


def exit_triggered_v2(peak, close, bars_held: int,
                      trail_dd: float = 0.10, max_hold_bars: int = 30) -> bool:
    """离场条件判定。返回 True = 应离场（回撤 trail_dd 或持有超 max_hold_bars 交易日，先到者）。

    参数：
      peak        入场后最高收盘价（调用方维护，判定后更新）
      close       当前收盘价
      bars_held   入场日之后至当前日的交易 bar 数（不含入场日）
    """
    if peak and peak > 0 and close / peak - 1.0 < -trail_dd:
        return True
    return bars_held > max_hold_bars
