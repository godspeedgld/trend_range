# 时序 CTA 回测引擎规则

默认用内置本地引擎（`scripts/local_backtest.py`）作为 Step 4 的策略执行/回测引擎。引擎是**信号驱动、资产无关**的：读外部行情 + 策略信号日志，按可配执行滞后与成本，写出可审计的回测产物。

## 入口

```bash
python scripts/local_backtest.py {project_dir} --market-data /path/to/market_data.csv
```

行情支持 CSV/Parquet，默认列：`date`、`symbol`、`close`。列名不同用 `--date-col`/`--symbol-col`/`--price-col` 覆盖。**行情由用户外部提供（本地路径），引擎/技能绝不下载。** 若策略需 OHLC（止损/止盈判断），行情文件可含 `open/high/low/volume`，由 `strategy.py` 读取使用。

引擎读信号：

```text
04_backtest_strategy/backtest_logs/signal_log.jsonl
```

每行：

```json
{"date": "YYYY-MM-DD", "signals": {"SYM": {"factor": 1.23, "direction": 1}}}
```

`direction` ∈ {1, -1, 0}（多/空/平）。引擎把 direction 经执行滞后转为持仓权重，按 close 收益核算，含成本/滑点，写 equity/trades/metrics + 中文 HTML。

若用户显式提供外部回测器，记录其模块/CLI/版本/配置/输出映射到 `manifest.json`，不得静默替换。

## 策略代码

`04_backtest_strategy/strategy.py` 必须做到：

- **三要素在此实现**：开仓 / 止损 / 止盈逻辑写在本文件里。引擎不内置 ATR 移动止损，所以由 `strategy.py` 读 OHLC、计算 entry/stop/target，**当止损或止盈触发时把 `direction` 置 0（或反向）**，写入 `signal_log.jsonl`。引擎只做组合核算（close-based）。
- 参数集中在顶部一个可见区。
- 为每个 date/symbol 记录 factor 与 direction。
- 显式写执行假设：rebalance 时点、下单时点、滑点、手续费、保证金、合约乘数、资金分配、风控。
- 写出 `backtest_logs/signal_log.jsonl`。
- 引擎应用可配执行滞后、手续费、滑点、初始资金、年化、单品种最大权重。

## 已知局限（写入报告）

- **日频 bar 口径**：引擎用 close 核算。止损/止盈在 `strategy.py` 用 OHLC 判断后以 direction 体现，**非 intraday 逐笔执行**；gap/跳空风险未完全建模。
- 未来增强（本版不做）：引擎原生支持 OHLC 止损命中价、intraday 路径回放。

## 回测报告

用户可见报告：`04_backtest_strategy/backtest_report.html`（中文）。
引擎原始输出（英文/JSON）：`04_backtest_strategy/backtest_report_raw.html`。

引擎写出：

```text
04_backtest_strategy/backtest_logs/equity_curve.csv
04_backtest_strategy/backtest_logs/performance_metrics.csv
04_backtest_strategy/backtest_logs/trades.csv
04_backtest_strategy/backtest_logs/position_return_detail.csv
03_strategy_evaluation/data/direction_matrix_from_strategy.csv
03_strategy_evaluation/data/portfolio_returns_dir_full.csv
03_strategy_evaluation/data/backtest_alignment_audit.csv
```

## 评估口径对账

回测跑完后，评估报告（`03_strategy_evaluation/evaluation_report.html`）须含一节"口径/已知局限"：

- 说明 `01_nav.png` 是回测实际净值（来自 `equity_curve.csv`），区别于任何理论净值。
- 在 `backtest_alignment_audit.csv` 记录数据源、频率、执行时点、权重/成本口径、最终 NAV、最大回撤、差异原因。
- 不存在"因子理论验证 vs 回测"的分阶段对账（本技能无因子阶段），只做"策略意图 vs 回测实际"的单口径说明。
