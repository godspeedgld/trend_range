# skill-time-series-model

两阶段**检测驱动**的金融时序建模 Skill。对**收益率/差分序列**做：

- **均值方程**检测：Ljung-Box（短期自相关）+ GPH（长记忆 / 分数积分 d）+ ACF/PACF
- **方差方程**检测：ARCH-LM（波动聚集）+ Engle-Ng 符号偏差（杠杆 / 非对称）

ADF 为前提（非平稳直接抛 `NonStationaryError`）。两阶段组合判定均值/方差方程，
落到三流程之一（白噪声不建模），按 AIC/BIC 选阶、估计参数，再用 Ljung-Box 验证残差，
产出中文 Markdown 报告（含检测图与「实际 + 拟合 + 预测」对比图）。

> 与 [`skill-time-series-analysis`](../skill-time-series-analysis-main) 互补：前者做
> 平稳性/分布/协整**诊断**，本 skill 做 **ARMA / ARFIMA / GARCH / GJR-GARCH 建模与预测**。

## 模型矩阵（均值 × 方差）

| 均值方程 ＼ 方差方程 | Constant（无 ARCH） | GARCH（对称） | GJR-GARCH（杠杆） |
|---|---|---|---|
| **Constant**（无自相关、无长记忆） | 白噪声（**不建模**） | `flow_b` GARCH | `flow_b` GJR-GARCH |
| **ARMA**（有自相关） | `flow_a` ARMA | `flow_c` ARMA+GARCH | `flow_c` ARMA+GJR-GARCH |
| **ARFIMA**（有长记忆） | `flow_a` ARFIMA | `flow_c` ARFIMA+GARCH | `flow_c` ARFIMA+GJR-GARCH |

- 均值 3 × 方差 3 = 9 格；白噪声不建模，共 **8 种建模组合**。
- 方程选择依据：均值由 LB + GPH 决定；方差由 ARCH-LM + Engle-Ng 决定（有杠杆 → GJR-GARCH）。

## 工作流

```
收益率序列（必须平稳）
   │
   ▼  ADF 前提：非平稳 → NonStationaryError
   │
   ├── 均值方程：Ljung-Box + GPH + ACF/PACF ─► Constant / ARMA / ARFIMA
   ├── 方差方程：ARCH-LM + Engle-Ng 符号偏差 ─► Constant / GARCH / GJR-GARCH
   │
   ▼  classify_model(mean, var) → flow
   │
   ├── white_noise ─► 不建模（fit_model 返回 None）
   ├── flow_a       ─► 均值方程(ARMA/ARFIMA) + 不变方差 → 残差 LB → 判定
   ├── flow_b       ─► 常数均值 + 方差方程(GARCH/GJR) → 标准化残差双 LB → 判定
   └── flow_c       ─► 两步：均值取创新 → 残差上 GARCH/GJR → 标准化残差双 LB → 判定
   │
   ▼
Markdown 报告 + 检测图 + 预测图（reports/）
```

## 快速开始

```bash
# 依赖：arch / statsmodels / scipy / pandas / matplotlib
pip install arch statsmodels scipy pandas matplotlib
```

```python
import sys, sqlite3
import numpy as np, pandas as pd
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
print("flow:", report["diag"].flow,
      "| mean:", report["diag"].mean_equation,
      "| var:", report["diag"].variance_equation)
```

## Public API

报告 API：

- `generate_model_report(returns, series_name=..., output_dir=..., forecast_steps=20, max_p=3, max_q=3, p_max=2, q_max=2, criterion="aic")`
  → `dict(markdown, markdown_path, diag, fit, diag_plot, pred_plot, fit_error)`

建模 API（`scripts/modeling.py`）：

- `fit_model(diag, series, *, max_p=3, max_q=3, p_max=2, q_max=2, criterion="aic", forecast_steps=20)` — 按 `diag.flow` 路由；白噪声返回 `None`
- `flow_a(series, mean_eq, ...)` / `flow_b(series, var_eq, ...)` / `flow_c(series, mean_eq, var_eq, ...)` — 三流程
- 原子均值：`fit_constant_mean` / `fit_arma_mean` / `fit_arfima_mean`（ARFIMA 两步法）
- 原子方差：`fit_garch_var`（对称）/ `fit_gjr_var`（杠杆，`o=1`）

检测 API（`scripts/diagnostics.py`）：

- `run_diagnostics(series)` → `DiagnosticReport(adf, ljung_box, arch_lm, gph, sign_bias, acf_pacf, mean_equation, variance_equation, flow, recommendation, reason)`
- `adf_test` / `ljung_box_test` / `gph_test` / `arch_lm_test` / `engle_ng_sign_bias_test` / `acf_pacf`
- `recommend_mean_equation` / `recommend_variance_equation` / `classify_model`
- `NonStationaryError`（ADF 非平稳时抛出）

## 目录

```
skill-time-series-model/
├── SKILL.md
├── README.md
├── pyproject.toml            # arch, statsmodels, scipy, pandas, matplotlib
├── scripts/
│   ├── diagnostics.py        # ADF / Ljung-Box / GPH / ARCH-LM / Engle-Ng / ACF-PACF + 两阶段判定
│   ├── modeling.py           # flow_a/b/c + 原子均值/方差拟合器
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

> 实现注记：`arch` 8.0 的 EGARCH 仅含 `|z|` 幅度项、无符号项，无法刻画杠杆；
> 故非对称情形用 **GJR-GARCH**（`vol='GARCH', o=1`，含 `gamma` 杠杆项）。
> ARFIMA 用两步法（arch/statsmodels 不支持分数 d）：GPH 估 d → 分数差分 → 差分序列上 fit ARMA。

License: GPL-3.0-only.
