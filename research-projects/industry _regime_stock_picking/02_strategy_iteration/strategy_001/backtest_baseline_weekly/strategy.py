"""baseline（云端原版·恒反转）· **周频因子口径**版 —— 复现云端的真实窗口行为。

## 为什么有这个目录

2026-09-28 定位到：云端 `cloud_code_with_industry_log.py::load_stock_panel` 的五个因子
**实际是在「信号日（周频）序列」上滚动的**，不是日频 —— 外层
`SELECT * FROM ts WHERE date IN ({dl})` 被 DAI **下推进 CTE**，而 `dl` 只含周频信号日，
于是「20 行」= 20 周。

已逐值验证（`data_from_cloud/verify_weekly_window.py`）：按周频行序重算，
五个因子各 11,124~11,300 可比行 **100.00% 相等**（最大相对差 4e-15~4e-07）。

⇒ 本地日频口径的 baseline（`../backtest_baseline_fullmarket`，+127.4%）与云端（+801.2%）
   **用的不是同一套因子**。本目录把本地因子换成**周频口径**，其余一字不改。

## 与 ../backtest_baseline_fullmarket/ 的唯一差异

| 项 | 原 baseline（全市场） | 本版 |
|---|---|---|
| 因子窗口 | 日频（5/60 **日**、20 **日**） | **周频**（5/60 **周**、20 **周**） |
| 成交量门槛 | 20 日**均**额 > 2e7 | **当日**额 > 2e7（对齐云端 WHERE） |
| 次日可成交过滤 | 有 | 无（云端没有这条） |
| 行业层 / 稳定性过滤 / 持仓数 / 权重 / 成本 | — | **完全相同** |

数据：`shared/_cache/signal_panel_weekly.parquet`（`shared/build_stock_panel_weekly.py` 产出）
→ `weekly_targets_baseline_weekly.parquet` → 引擎行情 `engine_market_weekly.parquet`。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from targets_lookup import make_interfaces  # noqa: E402

entry_signal, exit_check, pool_invalidate, select_order, position_weight = \
    make_interfaces("baseline_weekly")
