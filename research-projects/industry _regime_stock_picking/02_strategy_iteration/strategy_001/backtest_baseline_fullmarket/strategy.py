"""baseline（云端原版·恒反转）· **全市场池** 版 —— 2026-09-28 数据补全后的复验。

## 为什么有这个目录

`../backtest_strategy_baseline/` 用的是**当期三指数成分池**（HS300∪CSI500∪CSI1000，
3,475 只）——当时本地数据只有这些。它与云端（`cn_stock_prefactors` **全市场**）不可比：
2026-09-23 对账把"+100.5% vs 云端 +801%"的差异归因到**股票池**上（云端交易的 562 只里
本地缺 222 只、占云端平仓盈亏 60%）。

2026-09-28 数据补全（`stock_bar1d` 3475 → **5806 只 = 沪深全市场**，云端 562 只覆盖
**100%**）后，本目录用**同一套策略逻辑、全市场池**重跑，直接验证该归因。

**不覆盖原 baseline**：原目录是"三指数池"口径的历史产出，保留以便对比两个池的差异。

## 与 ../backtest_strategy_baseline/ 的唯一差异

| 项 | 原 baseline | 本版 |
|---|---|---|
| 股票池 | 当期三指数成分（3,475 只） | **全市场**（5,806 只，`UNIVERSE=full`） |
| 策略逻辑 | 恒反转（= 云端原版） | **完全相同** |
| 行业层 / 稳定性过滤 / 持仓数 / 权重 / 成本 | — | **完全相同** |

数据：`shared/_cache/signal_panel_full.parquet`（候选 4,576 只/信号日，2025）
→ `weekly_targets_baseline_full.parquet` → 引擎行情 `engine_market_full.parquet`。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from targets_lookup import make_interfaces  # noqa: E402

entry_signal, exit_check, pool_invalidate, select_order, position_weight = \
    make_interfaces("baseline_full")
