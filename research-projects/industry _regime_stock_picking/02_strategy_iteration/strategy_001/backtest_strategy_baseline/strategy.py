"""strategy_001 · 对照基准 —— 云端原版（**选股层恒用反转方向**，与 regime 无关）。

与迭代一（`../backtest_strategy/strategy.py`）**唯一差异** = 加载 baseline 的目标持仓表
（`shared/build_weekly_targets.py` MODE=baseline）。行业层、稳定性过滤、持仓数、权重、
成本全部相同，用于干净隔离「选股层因子方向是否该随 regime 切换」这一个变量。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from targets_lookup import make_interfaces  # noqa: E402

entry_signal, exit_check, pool_invalidate, select_order, position_weight = \
    make_interfaces("baseline")
