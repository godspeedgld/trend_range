"""strategy_001 · 迭代一 —— 变盘指数行业轮动（**选股层因子方向跟随 regime 切换**）。

技能结构：本文件只做「5 接口 → 共享查表」的薄封装；策略逻辑与查表实现在 `shared/`。
  · 决策逻辑（regime → 3 行业 → 行业内四因子复合选 2 只 → 缓冲 → 权重）
    → `shared/build_weekly_targets.py`（MODE=regime 预计算）
  · 查表 → 5 接口 → `shared/targets_lookup.py`

引擎：`.claude/skills/skill-research-assistant/scripts/local_portfolio_backtest.py`
（开仓池/平仓池框架：每日收盘决策 → 次日开盘执行）

迭代一改动（相对云端原版 = 恒反转）：
  动量期（T′<0）四因子全部取正；反转期维持取负。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from targets_lookup import make_interfaces  # noqa: E402

entry_signal, exit_check, pool_invalidate, select_order, position_weight = \
    make_interfaces("regime")
