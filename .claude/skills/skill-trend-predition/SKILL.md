---
name: trend-prediction
description: Use when an agent needs to predict trend vs range regime on OHLCV price data.
  Provides indicator / decision-tree / markov / deep-learning flows. The agent picks the
  flow, translates the user's natural-language rule into code (indicators, rule, features,
  label), then calls a template. Ships with ADX/Hurst/MACD/HMA library, RandomForest+XGBoost
  walk-forward, scaling, correlation filter, confusion/precision/recall, colored close/kline.
quantSkills:
  organization: https://github.com/quantskills
  project_type: skill
  collection: quant-research-tools
  license: GPL-3.0
  category: tooling
  tags: [trend, regime, adx, hurst, macd, hma, random-forest, xgboost, walk-forward, hmm, lstm]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 趋势/震荡预测 skill：指标法 + 决策树法（RandomForest/XGBoost 滚动训练）已实现，马尔可夫/深度学习为占位。路由与指标/特征/标签/模型均由调用方（LLM）根据用户输入动态生成代码后套模板。
  summary_en: Trend-vs-range prediction skill. Indicator + decision-tree (RF/XGBoost walk-forward) implemented; Markov / deep-learning are placeholders. The agent decides the flow and translates the user's NL rule into code (indicators/rule/features/label), then calls a template.
---

# Trend Prediction

判断价格序列的**趋势 / 震荡** regime。本 skill 是**框架**，不是固定流水线：

- **路由由你（agent）决定**：根据用户请求选 `predict_by_indicator`（指标法）或 `predict_by_tree`（决策树法），没有内置 dispatcher。
- **指标、评判规则、特征、标签、模型都由你根据用户输入动态生成代码**，再传入模板。
- 模板只固化流程骨架与子工具（量纲统一、相关性剔除、滚动训练、评估、绘图、报告）。

## 你要做什么（核心：把自然语言翻译成代码，再套模板）

1. **读懂用户规则**。例：
   - "ADX(14)>25 且 MACD 金叉 就是趋势，其余震荡" → 指标法。
   - "用 ADX、MACD、量比、Hurst 作特征，预测未来 10 天是否趋势" → 决策树法。
2. **按需挑模板**，把用户规则翻译成代码：
   - 指标法：用 `indicator` 库算指标 → 写 `rule` 函数（输入指标 dict，输出逐 bar 预测）→ 写/选 `label_fn`（ground truth）。
   - 决策树法：用 `indicator` 库构造 `features`（DataFrame，**必须滞后、无未来函数**）→ 写/选 `label_fn`。
3. **调模板**：`predict_by_indicator(df, indicators=, rule=, label_fn=, output_dir=...)` 或
   `predict_by_tree(df, features=, label_fn=, task=, output_dir=...)`。模板自动出报告 + 图。
4. 无法判断走哪条 → `describe_data(df)`，出数据描述报告。

> 标签：常用 `indicator.trend_label(close, high, low, horizon=10, k=1.5)`（前瞻 N 天收益 |r|>k×相对ATR → 上行/下行，否则震荡，3 类）。也可自定义任意 `label_fn`。

## 方法矩阵

| 方法 | 函数 | 状态 | 何时用 |
|---|---|---|---|
| **指标法** | `predict_by_indicator` | ✅ | 用户给了显式规则（ADX/Hurst/MACD/HMA 阈值 + 逻辑）|
| **决策树法** | `predict_by_tree` | ✅ | 用户给了特征集 + 学习目标，要数据驱动 |
| **马尔可夫** | `plan_markov()` | 🟡 占位 | 想用 HMM 状态切换（需 hmmlearn）|
| **深度学习** | `plan_dl()` | 🟡 占位 | 想用 LSTM/Transformer（需 torch）|

## 指标法（模板，不写死）

```python
from scripts import indicator as ind
from scripts.prediction import predict_by_indicator

close, high, low, vol = ind.extract_ohlcv(df)
indicators = {
    "adx": ind.adx(high, low, close, 14),
    "macd_line": ind.macd(close)[0], "macd_sig": ind.macd(close)[1],
}

# rule = 用户规则 "ADX>25 且 MACD>signal → 上行；ADX>25 且 MACD<signal → 下行；否则震荡"
def rule(d):
    pred = pd.Series(0.0, index=d["adx"].index)
    pred[(d["adx"] > 25) & (d["macd_line"] > d["macd_sig"])] = 1.0
    pred[(d["adx"] > 25) & (d["macd_line"] < d["macd_sig"])] = -1.0
    return pred

label_fn = lambda df: ind.trend_label(*ind.extract_ohlcv(df)[:3], horizon=10, k=1.5)
res = predict_by_indicator(df, indicators=indicators, rule=rule, label_fn=label_fn,
                           series_name="HC", output_dir="reports/hc")
```

## 决策树法（流程模板：量纲/相关性 → 标签 → 滚动训练）

```python
features = pd.DataFrame(index=close.index)   # 你按用户给的算，必须滞后
features["adx"]   = ind.adx(high, low, close)
features["macd"]  = ind.macd(close)[2]        # hist
features["ret5"]  = np.log(close).diff(5)
features["hma_dev"] = close / ind.hma(close, 20) - 1
# ...
res = predict_by_tree(df, features=features, label_fn=label_fn, task="classification",
                      series_name="HC", output_dir="reports/hc", min_train=750, step=200, test_block=200)
# task="regression" 时标签连续化，模板自动切到 RF/XGB Regressor + RMSE/MAE/R²
```

## 只算指标 + 出图（不要报告）

indicator.py 与 viz.py 是**独立模块**，可跳过模板直接用。典型：主图 close/K线 + 副图 MACD/ADX/KDJ。

```python
from scripts import indicator as ind, viz
close, high, low, vol = ind.extract_ohlcv(df)
d = df.tail(400)                                   # 近 400 根
ml, ms, mh = ind.macd(close)
adx_, dip, dim = ind.adx_components(high, low, close)   # ADX + DI+/DI-
K, D, J = ind.kdj(high, low, close)

# 主图 close 折线 + MACD 副(线+柱+0线)
viz.plot_panels(d, main="close",
                panels=[{"title":"MACD","lines":{"MACD":ml,"signal":ms},"bars":{"hist":mh},"hlines":[0]}],
                title="HC close + MACD", path="reports/hc/macd.png")
# 主图 K线 + ADX 副(ADX/+DI/-DI + 25线)
viz.plot_panels(d, main="kline", last_n=200,
                panels=[{"title":"ADX","lines":{"ADX":adx_,"+DI":dip,"-DI":dim},"hlines":[25]}],
                title="HC k线 + ADX/DI", path="reports/hc/adx.png")
```
- `main`：`"close"`（折线）或 `"kline"`（K 线）。
- 每个 `panels` 项：`lines`(折线) / `bars`(柱状，如 hist) / `hlines`(水平参考线，如 0、25)。
- `main_colored=标签Series` 给主图加趋势红/震荡绿着色（K线则按 regime 上色）。

## API Pyramid

| Layer | Use first | Purpose |
|---|---|---|
| 模板 | `predict_by_indicator`, `predict_by_tree`, `describe_data` | 流程骨架，传 indicators/rule/features/label_fn |
| 工具 | `standardize`, `correlation_filter`, `rolling_train` | 写死、可独立复用 |
| 指标库 | `indicator.adx/atr/macd/hma/hurst_rs/hurst_rolling/log_return/close_vol_ratio/trend_label` | 构造 indicators / features / label_fn |
| 可视化 | `viz.plot_panels`（通用主图+副图）/ `plot_close_colored` / `plot_kline_colored` / `plot_confusion` / `plot_feature_importance` / `plot_corr_heatmap` | 报告自动调用，也可独立调用 |
| 结果 | 报告 md + 着色 close/K线 + 混淆矩阵 + 特征重要性 + 相关性 | 写入 output_dir |

## Output Contract
- 结论先行 + 评判规则源码（指标法）或特征筛选理由（决策树法）。
- 评估：accuracy / precision / recall / F1（分类）或 RMSE/MAE/R²（回归）+ 混淆矩阵。
- 可视化：close 与 K 线按 regime 着色（**趋势红 / 震荡绿**）。
- caveat：标签为前瞻 ground-truth，仅回测、不下单。

## References
- `references/workflow.md` — 4 流程 + 组合模式
- `references/api.md` — 函数签名
- `references/report-format.md` — 各分支报告模板
- `references/interpretation.md` — 指标数学、决策树流程、组合方法学

## Boundary
不取数、不回测下单、不预测具体价格点位。只做"趋势/震荡 regime 判断"并量化评估。
