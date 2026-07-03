# API Reference

> 设计：模板 + 指标库 + 子工具。**无顶层 dispatcher**——路由与具体指标/规则/特征/标签由调用方提供。

## 模板（`scripts/prediction.py`）

- `predict_by_indicator(df, *, indicators, rule, label_fn, class_labels=None, series_name="series", output_dir=None)`
  - `indicators: dict[str, pd.Series]` 调用方算好的指标
  - `rule: Callable[[dict[str,Series]], pd.Series]` 评判函数，输出逐 bar 预测（如 +1/−1/0）
  - `label_fn: Callable[[df], pd.Series]` ground truth
  - 返回 result dict 并写报告/图（output_dir 给定时）。
- `predict_by_tree(df, *, features, label_fn, task="classification", min_train=750, step=100, test_block=200, models=("rf","xgb"), corr_threshold=0.9, series_name="series", output_dir=None)`
  - `features: pd.DataFrame` 调用方构造（须滞后无未来函数）
  - `task: "classification" | "regression"`
  - 固化：量纲统一 + 相关性剔除 + 滚动训练 + 评估；RF/XGB 对比。
- `describe_data(df, hint="", *, series_name="series", output_dir=None)` —— 无法匹配流程时的数据描述报告。
- `plan_markov()` / `plan_dl()` —— 返回占位计划 dict。

## 子工具（写死、可独立复用，`scripts/prediction.py`）
- `standardize(X_train, X_test)` → `(tr_scaled, te_scaled)`，fit 于训练段。
- `correlation_filter(X, threshold=0.9, reference=None)` → `(keep, dropped, corr)`；`reference` 建议传初始训练段。
- `rolling_train(X, y, *, task, min_train, step, test_block, models)` →
  `{fold_metrics, oos_index, oos_pred:{model:Series}, oos_y, importances, setup}`。

## 指标库（`scripts/indicator.py`）
- `extract_ohlcv(df)` → `(close, high, low, vol)`，缺失用 close 近似。
- `atr(high, low, close, n=14)` —— Wilder ATR。
- `adx(high, low, close, n=14)` —— Wilder ADX。
- `hurst_rs(series, max_lag=None)` —— 经典 R/S Hurst（标量；>0.5 持续/趋势，<0.5 反持久）。
- `hurst_rolling(series, window=200)` —— 滚动 Hurst（特征用）。
- `macd(close, fast=12, slow=26, signal=9)` → `(macd_line, signal, hist)`。
- `hma(close, n=20)` —— Hull MA。
- `log_return(close)`；`close_vol_ratio(close, vol)` = ln(close)−ln(vol)。
- `trend_label(close, high, low, horizon=10, k=1.5, atr_n=14)` —— 前瞻 3 分类标签（默认 ground truth）。

## 可视化（`scripts/viz.py`，报告自动调用）
- `plot_close_colored(close, labels, path)` —— close 折线 + 趋势段红/震荡段绿 背景着色。
- `plot_kline_colored(df, labels, path, last_n=200)` —— 手画 K 线按 regime 着色。
- `plot_confusion(cm, classes, path)`；`plot_feature_importance(importances, path, top_n=20)`；
  `plot_corr_heatmap(corr, path)`。

## 报告（`scripts/reports.py`）
- `generate_report(result, df, *, output_dir=None, series_name="series")` →
  `{markdown, markdown_path, plots}`；按 `result["branch"]` 选模板渲染（indicator/tree/markov/dl/default）。

## 模块路径
- 指标：`scripts/indicator.py`
- 模板/工具：`scripts/prediction.py`
- 报告：`scripts/reports.py`
- 可视化：`scripts/viz.py`
