# skill-time-series-model

检测驱动的金融时序建模 Skill。对**收益率/差分序列**跑 ADF、Ljung-Box、ARCH-LM、
方差比(Lo-MacKinlay) 四项检测，自动判定该用哪种模型，按 AIC/BIC 选阶、估计参数、
再用 Ljung-Box 验证残差，最后产出中文 Markdown 报告（含检测图与「实际 + 拟合 + 预测」对比图）。

> 与 [`skill-time-series-analysis`](../skill-time-series-analysis-main) 互补：前者做
> 平稳性/分布/协整**诊断**，本 skill 做 **ARMA / GARCH / 随机游走建模与预测**。

## 支持模型

| 检测组合 | 建议模型 |
|---|---|
| 无自相关 + 无 ARCH 效应 + VR 不拒绝 | `RandomWalk`（ARIMA(0,1,0) 漂移）|
| 有自相关 + 无 ARCH 效应 | `ARMA` |
| 有自相关 + 有 ARCH 效应 | `ARMA+GARCH` |
| 无自相关 + 有 ARCH 效应 | `AR+GARCH` |

## 工作流

```
收益率序列
   │
   ▼
ADF · Ljung-Box · ARCH-LM · 方差比VR   ──►  recommend_model
   │
   ├── RandomWalk  ─► ARIMA(0,1,0) 漂移 → 残差 LB → 判定
   ├── ARMA        ─► AIC/BIC 选阶 → 估计 → 残差 LB → 判定
   ├── AR+GARCH    ─► 选 AR 阶 → AR(p)+GARCH → 标准化残差双 LB → 判定
   └── ARMA+GARCH  ─► 选 ARMA 阶 → 两步联合 → 标准化残差双 LB → 判定
   │
   ▼
Markdown 报告 + 检测图 + 预测图（reports/）
```

## 快速开始

```bash
# 依赖：arch / statsmodels / pandas / matplotlib
pip install arch statsmodels pandas matplotlib
```

```python
import sys, sqlite3, pandas as pd
sys.path.append(".claude/skills/skill-time-series-model")

from scripts.reporting import generate_model_report

# 从本地 pd_k_data.db 读 RB 后复权收盘，转对数收益率
conn = sqlite3.connect("data_cache/pd_k_data.db")
price = pd.read_sql("SELECT date, close FROM \"1d_k_data\" WHERE symbol='rb'", conn)
price = price.set_index("date")["close"].sort_index()
returns = np.log(price).diff().dropna()

report = generate_model_report(
    returns, series_name="RB_returns",
    output_dir=".claude/skills/skill-time-series-model/reports/rb",
    forecast_steps=30,
)
print(report["markdown_path"])
```

## Public API

报告 API：

- `generate_model_report(returns, series_name=..., output_dir=..., forecast_steps=20, criterion="aic")`
  → `dict(markdown, markdown_path, diag, fit, diag_plot, pred_plot)`

建模 API（`scripts/modeling.py`）：

- `fit_model(model_type, returns, **kwargs)` — 按 `RandomWalk`/`ARMA`/`AR+GARCH`/`ARMA+GARCH` 路由
- `fit_random_walk(returns, forecast_steps=20)` — ARIMA(0,1,0) with drift
- `fit_arma(returns, max_p=5, max_q=5, criterion="aic")`
- `fit_ar_garch(returns, max_ar=5, garch_p=1, garch_q=1)`
- `fit_arma_garch(returns, max_p=4, max_q=4, garch_p=1, garch_q=1)`

检测 API（`scripts/diagnostics.py`）：

- `run_diagnostics(series)` → `DiagnosticReport(adf, ljung_box, arch_lm, variance_ratio, recommendation, reason)`
- `adf_test` / `ljung_box_test` / `arch_lm_test` / `variance_ratio_test` / `recommend_model`

## 目录

```
skill-time-series-model/
├── SKILL.md
├── README.md
├── pyproject.toml            # arch, statsmodels, pandas, matplotlib
├── scripts/
│   ├── diagnostics.py        # ADF / Ljung-Box / ARCH-LM
│   ├── modeling.py           # ARMA / AR+GARCH / ARMA+GARCH
│   └── reporting.py          # 报告生成 + 检测图 + 预测图
├── references/
│   ├── workflow.md
│   ├── api.md
│   ├── interpretation.md
│   └── report-format.md
├── agents/                   # 各运行时适配（cursor / openai / portable）
└── reports/                  # 输出报告与图
```

## 边界

本 skill **不取数、不回测、不下单信号**，只做统计建模与诊断。输出仅用于研究方向判断。

License: GPL-3.0-only.
