# 时序 CTA 回测引擎规则（backtest_engine.md）

本技能用**事件驱动引擎**（`scripts/local_backtest.py`），不是 -factor 的 signal 驱动引擎。
时序 CTA 的回测结果由**开仓 + 止盈止损 + 策略逻辑共同、即时**决定，故引擎逐根推进状态机。

## 引擎接口

```bash
python scripts/local_backtest.py {project_dir} --market-data /path/to/ohlc.csv
```

- 行情：OHLCV CSV/Parquet（`date,symbol,open,high,low,close`[+volume]），**外部提供，技能不下载**。
- 策略：`03_backtest_strategy/strategy.py` 暴露 `build_strategy(df)->spec`，引擎 per-symbol 调用。

### strategy.py 的 spec 格式

```python
def build_strategy(df):  # df: 单品种 OHLC DataFrame
    # 指标 + 入场事件（向量化）
    ...
    return {
        "entry_long":  pd.Series(bool),    # 开多事件
        "entry_short": pd.Series(bool),    # 开空事件
        "stop": {"type": "atr_chandelier", "atr_period": 14, "k": 2.0},
        # stop.type: none / atr_static / atr_chandelier / percent
        "sizing": {"type": "full"}，        # 或 vol_target: {"type":"vol_target","target_vol":0.15,"vol_window":20}
        "allow_short": True,
    }
```

## 执行语义（事件驱动，防前视）

- **入场**：close[t] 信号确认 → 以 close[t] 进场，持有进入 bar t+1。
- **止损**：持仓中每根 bar 用 high/low 判 ATR 吊灯（或静态/百分比）命中 → 命中则以**止损价成交**（gapped 取 open），即时平仓。
- **收益**：close-to-close 基准；止损 bar 收益 = pos·(止损价/prev_close − 1)。
- **成本**：进场 + 出场各扣 cost_rate（手续费 bps + 滑点 bps）。
- **多品种**：per-symbol 跑，组合日收益等权合成。

## 提速

指标/入场信号向量化（numpy/pandas）；路径依赖状态机用 **numba @jit** 加速（不可用自动回退纯 Python，逻辑一致）。

## 产物（引擎写出，去因子化）

```
03_backtest_strategy/backtest_logs/
  equity_curve.csv            # date, net_return, nav, drawdown
  performance_metrics.csv     # 单行指标
  position_return_detail.csv  # 逐根 date/symbol/ret/pos/direction
  signal_log.jsonl            # 引擎产出的【实现方向】（审计用，非输入）
03_backtest_strategy/
  backtest_report.html        # 中文回测解释
  backtest_report_raw.html    # 原始 JSON（英文/数值）
```

指标口径（复用 -factor compute_metrics）：final_nav、total/annual_return、annual/downside_volatility、Sharpe、Sortino、Calmar、max_drawdown、win_rate、profit_factor。**不含**因子 IC/分位/多空。

## 已知局限（写进 backtest_report.html）

- bar 级别（日频/周频）事件驱动，非逐笔 intraday。
- gap 用命中价/open 近似。
- signal_log 为引擎产出（审计），不再是输入接口（区别于 -factor）。

## 外部回测器

若用户显式提供外部回测器（如 vectorbt/backtrader），在 manifest 记录其入口/命令/配置/输出映射，不得静默替换。
