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
- `adx_components(high, low, close, n=14)` → `(adx, plus_di, minus_di)`，副图同画 ADX+DI 用。
- `adx_hma(high, low, close, n=14)` —— **低延迟 ADX**：DX→ADX 的 Wilder SMMA 换成 HMA（DI 仍标准 Wilder），趋势反转响应更快、滞后更低（HC 实测领先标准 ADX ~5 根）。
- `adx_hma_components(high, low, close, n=14)` → `(adx_hma, plus_di, minus_di)`。
- `adx_diff_hma(high, low, close, n=14)` —— **方向性低延迟变体**：DX 不用差/和比值，而用带符号差值 (DI+ − DI−)，再 HMA 平滑。返回**有符号**序列（正=多头、负=空头、绝对值=强度）；阈值需重新标定（HC 上 \|值\|>25 仅 11%，严于标准 ADX>25 的 48%）。
- `adx_diff_hma_components(high, low, close, n=14)` → `(adx_diff_hma, plus_di, minus_di)`。
- `kdj(high, low, close, n=9, m1=3, m2=3)` → `(K, D, J)`。
- `hurst_rs(series, max_lag=None)` —— 经典 R/S Hurst（标量；>0.5 持续/趋势，<0.5 反持久）。
- `hurst_rolling(series, window=200)` —— 滚动 Hurst（特征用）。
- `macd(close, fast=12, slow=26, signal=9)` → `(macd_line, signal, hist)`。
- `hma(close, n=20)` —— Hull MA。
- `log_return(close)`；`close_vol_ratio(close, vol)` = ln(close)−ln(vol)。
- `trend_label(close, high, low, horizon=10, k=1.5, atr_n=14)` —— 前瞻 3 分类标签（默认 ground truth）。

## 可视化（`scripts/viz.py`）
- `plot_panels(df, *, main="close"|"kline", main_colored=None, panels=None, title=None, path=None, last_n=None)`
  —— **通用主图+副图**（一个函数、参数控制）：
    * 主图：close 折线 或 K 线（`main`）；
    * `main_colored`：regime 标签（0/非0）→ 主图趋势红/震荡绿（折线背景着色 / K线按regime上色）；
    * `panels`：副图列表，每项 `{"title", "lines":{name:Series}, "bars":{name:Series}, "hlines":[...]}`。
    * 示例：MACD 副=`{"title":"MACD","lines":{"MACD":..,"signal":..},"bars":{"hist":..},"hlines":[0]}`；
      ADX 副=`{"title":"ADX","lines":{"ADX":..,"+DI":..,"-DI":..},"hlines":[25]}`；KDJ 副=`{"title":"KDJ","lines":{"K":..,"D":..,"J":..}}`。
- `plot_close_colored(close, labels, path)` / `plot_kline_colored(df, labels, path, last_n=200)`
  —— 薄封装（= `plot_panels` 的着色特例），报告自动调用。
- `plot_confusion(cm, classes, path)`；`plot_feature_importance(importances, path, top_n=20)`；
  `plot_corr_heatmap(corr, path)`。

> `plot_panels` 可独立于报告使用：`from scripts import indicator, viz` 算指标后直接 `viz.plot_panels(...)` 出图。

## 报告（`scripts/reports.py`）
- `generate_report(result, df, *, output_dir=None, series_name="series")` →
  `{markdown, markdown_path, plots}`；按 `result["branch"]` 选模板渲染（indicator/tree/markov/dl/default）。

## 模块路径
- 指标：`scripts/indicator.py`
- 模板/工具：`scripts/prediction.py`
- 报告：`scripts/reports.py`
- 可视化：`scripts/viz.py`
