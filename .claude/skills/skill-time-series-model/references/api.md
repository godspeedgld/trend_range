# API Reference

## 报告 API（用户面向）

- `generate_model_report(returns, series_name="series", title=None, output_dir=None, forecast_steps=20, max_p=3, max_q=3, p_max=2, q_max=2, criterion="aic")`
  - 返回 dict：`{markdown, markdown_path, diag, fit, diag_plot, pred_plot, fit_error}`。
  - 非平稳输入会向上传播 `NonStationaryError`。

## 建模 API

- `fit_model(diag, series, *, max_p=3, max_q=3, p_max=2, q_max=2, criterion="aic", forecast_steps=20)`
  — 按 `diag.flow` 路由 flow_a/b/c/d（9 种组合全覆盖；返回 `FitSummary`，异常时由调用方捕获）。
- `flow_d(series, *, forecast_steps=20)` — 常数均值+不变方差：拟合 μ、σ²；残差单 LB。
- `flow_a(series, mean_eq, *, max_p=3, max_q=3, criterion="aic", forecast_steps=20)`
  — 均值方程(ARMA/ARFIMA) + 不变方差；残差单 LB。
- `flow_b(series, var_eq, *, p_max=2, q_max=2, criterion="aic", forecast_steps=20)`
  — 常数均值 + 方差方程(GARCH/GJR)；标准化残差双 LB。
- `flow_c(series, mean_eq, var_eq, *, max_p=3, max_q=3, p_max=2, q_max=2, criterion="aic", forecast_steps=20, max_iter=3)`
  — 均值方程 + 方差方程（迭代两步法）：① 定均值(p,q)取残差 → ② 残差上定方差(P,Q) →
  ③ 固定(P,Q)按 `mean_AIC+var_AIC` 重选(p,q)（至稳定）→ ④ 最佳阶最终拟合 → 标准化残差双 LB。

原子均值拟合器（`scripts/modeling.py`，各返回 dict 片段）：

- `fit_constant_mean(s)` → `{mu, resid, fitted, params, aic, bic, forecast}`
- `fit_arma_mean(s, max_p=3, max_q=3, criterion="aic", forecast_steps=20)` → `{order, params, resid, fitted, forecast, aic, bic}`
- `fit_arfima_mean(s, max_p=3, max_q=3, criterion="aic", forecast_steps=20)` → `{order=(p,d,q), d, params, resid, fitted, forecast, aic, bic}`（GPH 估 d → 分数差分 → ARMA）

原子方差拟合器（输入残差，返回方差阶 + arch result + 标准化残差）：

- `fit_garch_var(resid, p_max=2, q_max=2, criterion="aic")` — 对称 GARCH（`o=0`）
- `fit_gjr_var(resid, p_max=2, q_max=2, criterion="aic")` — GJR-GARCH（`o=1`，含 gamma 杠杆项）

`FitSummary` 字段：

- `model_type` / `order` / `criterion` / `params` / `aic` / `bic` / `n_obs`
  - `order`：ARMA→`(p,q)`；ARFIMA→`(p,d,q)`；含方差→`((均值阶),(P,Q))`
- `resid_lb`（flow_a 残差）/ `std_resid_lb`（方差类均值方程）/ `sq_std_resid_lb`（方差方程）
- `passed` / `reason` / `fitted` / `forecast_mean` / `forecast_index` / `resid`
- 两阶段：`mean_equation` / `variance_equation` / `flow` / `d`（ARFIMA 分数参数）

## 检测 API（`scripts/diagnostics.py`）

- `run_diagnostics(series, *, lb_lags=(10,15,20), arch_lags=(5,10,20), gph_bandwidth=None, acfpacf_nlags=30, significance=0.05)` → `DiagnosticReport`
- `adf_test(series)` → `ADFResult`
- `ljung_box_test(series, lags=(10,15,20))` → `LjungBoxResult`
- `gph_test(series, bandwidth=None, significance=0.05)` → `GPHResult`（`d_hat, se, tstat, pvalue, has_long_memory`）
- `arch_lm_test(series, lags=(5,10,20))` → `ArchLMResult`
- `engle_ng_sign_bias_test(residuals, significance=0.05)` → `SignBiasResult`（`sign_p, negative_p, positive_p, joint_p, has_asymmetry`）
- `acf_pacf(series, nlags=30)` → DataFrame（acf/pacf + 95% CI）
- `recommend_mean_equation(lb_has_ac, gph_has_lm)` → `"Constant"/"ARMA"/"ARFIMA"`
- `recommend_variance_equation(arch_has, engle_has_asym)` → `"Constant"/"GARCH"/"GJR"`
- `classify_model(mean_eq, var_eq)` → `(flow, model_type)`
- `NonStationaryError` — ADF 非平稳时由 `run_diagnostics` 抛出

## 模块路径

- 检测：`scripts/diagnostics.py`
- 建模：`scripts/modeling.py`
- 报告：`scripts/reporting.py`
