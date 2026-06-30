# API Reference

## 报告 API（用户面向）

- `generate_model_report(returns, series_name="series", title=None, output_dir=None, forecast_steps=20, max_p=5, max_q=5, criterion="aic")`
  - 返回 dict：`{markdown, markdown_path, diag, fit, diag_plot, pred_plot, fit_error}`。

## 建模 API

- `fit_model(model_type, returns, **kwargs)` — 按 `RandomWalk`/`ARMA`/`AR+GARCH`/`ARMA+GARCH` 路由（`none` 视同 `RandomWalk`）。
- `fit_random_walk(returns, forecast_steps=20)` — ARIMA(0,1,0) with drift：收益率空间常数漂移 μ + 白噪声。
- `fit_arma(returns, max_p=5, max_q=5, criterion="aic", forecast_steps=20)` — AIC/BIC 选 (p,q) → 估计 → 残差 LB → 判定。
- `fit_ar_garch(returns, max_ar=5, criterion="aic", garch_p=1, garch_q=1, forecast_steps=20)` — 选 AR 阶 → AR(p)+GARCH → 标准化残差双 LB。
- `fit_arma_garch(returns, max_p=4, max_q=4, criterion="aic", garch_p=1, garch_q=1, forecast_steps=20)` — 选 ARMA 阶 → 两步联合 ARMA+GARCH → 标准化残差双 LB。

返回 `FitSummary`，字段：

- `model_type`（`RandomWalk`/`ARMA`/`AR+GARCH`/`ARMA+GARCH`）/ `order` / `criterion` / `params` / `aic` / `bic` / `n_obs`
- `resid_lb`（ARMA/RandomWalk 残差 LB）/ `std_resid_lb`（GARCH 类均值方程）/ `sq_std_resid_lb`（方差方程）
- `passed` / `reason` / `fitted` / `forecast_mean` / `forecast_index`

## 检测 API

- `run_diagnostics(series, *, lb_lags=(10,15,20), arch_lags=(5,10,20), vr_lags=(2,5,10,20), significance=0.05)` → `DiagnosticReport`
- `adf_test(series)` → `ADFResult`
- `ljung_box_test(series, lags=(10,15,20))` → `LjungBoxResult`
- `arch_lm_test(series, lags=(5,10,20))` → `ArchLMResult`
- `variance_ratio_test(series, lags=(2,5,10,20))` → `VarianceRatioResult`
- `recommend_model(lb_has_ac, arch_has_effect, vr_is_random_walk=True)` → `(model_type, reason)`

## 模块路径

- 检测：`scripts/diagnostics.py`
- 建模：`scripts/modeling.py`
- 报告：`scripts/reporting.py`
