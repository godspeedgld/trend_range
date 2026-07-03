# skill-trend-prediction

判断价格序列**趋势 / 震荡** regime 的 skill。**框架式设计**：路由 + 指标/规则/特征/标签/模型都由
调用方（agent）根据用户输入**动态生成代码**，再套用下面的模板；模板只固化流程骨架与子工具。

## 方法矩阵

| 方法 | 函数 | 状态 | 何时用 |
|---|---|---|---|
| 指标法 | `predict_by_indicator` | ✅ | 用户给了显式规则（ADX/Hurst/MACD/HMA 阈值+逻辑）|
| 决策树法 | `predict_by_tree` | ✅ | 用户给了特征集 + 学习目标，要数据驱动 |
| 马尔可夫 | `plan_markov()` | 🟡 占位 | HMM 状态切换（需 hmmlearn）|
| 深度学习 | `plan_dl()` | 🟡 占位 | LSTM/Transformer（需 torch）|

## 核心思想
1. agent 读懂用户规则 → 2. 用 `indicator` 库翻译成代码（`indicators` dict + `rule` 函数 / `features` DataFrame + `label_fn`）→
3. 调 `predict_by_indicator` 或 `predict_by_tree` → 4. 模板自动出报告 + 图（趋势红/震荡绿）。

## 快速开始
```bash
uv sync                       # 建 .venv：sklearn/xgboost/arch/statsmodels/matplotlib...
```

```python
import sys, sqlite3, numpy as np, pandas as pd
sys.path.append(".claude/skills/skill-trend-predition")
from scripts import indicator as ind
from scripts.prediction import predict_by_indicator, predict_by_tree

con = sqlite3.connect("data_cache/pd_k_data.db")
df = pd.read_sql('SELECT date,open,high,low,close,vol FROM "1d_k_data" WHERE symbol="hc" ORDER BY date', con)
df["date"] = pd.to_datetime(df["date"], format="%Y%m%d"); df = df.set_index("date").sort_index()
close, high, low, vol = ind.extract_ohlcv(df)
label_fn = lambda d: ind.trend_label(*ind.extract_ohlcv(d)[:3], horizon=10, k=1.5)

# —— 指标法：规则 "ADX>25 且 MACD>signal → 上行；反之 → 下行；否则震荡" ——
indicators = {"adx": ind.adx(high, low, close, 14),
              "macd_line": ind.macd(close)[0], "macd_sig": ind.macd(close)[1]}
def rule(d):
    pred = pd.Series(0.0, index=d["adx"].index)
    pred[(d["adx"] > 25) & (d["macd_line"] > d["macd_sig"])] = 1.0
    pred[(d["adx"] > 25) & (d["macd_line"] < d["macd_sig"])] = -1.0
    return pred
predict_by_indicator(df, indicators=indicators, rule=rule, label_fn=label_fn,
                     series_name="HC", output_dir="reports/hc")

# —— 决策树法：特征集 + 滚动训练（RF + XGBoost）——
feat = pd.DataFrame(index=close.index)
feat["adx"] = ind.adx(high, low, close); feat["macd_hist"] = ind.macd(close)[2]
feat["ret5"] = np.log(close).diff(5); feat["hma_dev"] = close / ind.hma(close, 20) - 1
feat["hurst200"] = ind.hurst_rolling(np.log(close).diff(), 200)
predict_by_tree(df, features=feat, label_fn=label_fn, task="classification",
                series_name="HC", output_dir="reports/hc", min_train=750, step=200, test_block=200)
```

## API（节选）
- 模板：`predict_by_indicator(df, *, indicators, rule, label_fn, output_dir=None)`
        `predict_by_tree(df, *, features, label_fn, task, output_dir=None, min_train=750, step=100, test_block=200)`
        `describe_data(df, hint="", output_dir=None)`；`plan_markov()` / `plan_dl()`
- 工具：`standardize(Xtr,Xte)`、`correlation_filter(X, thr=0.9, reference=None)`、`rolling_train(X,y,...)`
- 指标库：`adx / atr / macd / hma / hurst_rs / hurst_rolling / log_return / close_vol_ratio / trend_label / extract_ohlcv`
- 可视化：`plot_close_colored / plot_kline_colored / plot_confusion / plot_feature_importance / plot_corr_heatmap`

## 目录
```
skill-trend-predition/
├── SKILL.md
├── README.md
├── pyproject.toml          # sklearn, xgboost, arch, statsmodels, matplotlib, scipy
├── scripts/
│   ├── indicator.py        # 指标库 + 默认 trend_label
│   ├── prediction.py       # 模板 + 子工具（无 dispatcher）
│   ├── reports.py          # 按分支组装报告
│   └── viz.py              # 着色 close/K线 + 混淆/重要性/相关性
├── references/{api,workflow,report-format,interpretation}.md
├── agents/{cursor-rule.mdc, openai.yaml, portable-loader.md}
└── reports/                # 输出（gitignore，保留 README.md）
```

## 边界
不取数、不回测下单、不预测具体价格点位。只做"趋势/震荡 regime 判断"并量化评估。
评估依赖前瞻 ground-truth 标签，仅用于回测，不构成下单依据。

License: GPL-3.0-only.
