---
name: time-series-model
description: Use when an agent needs to perform time series modeling on input data,
  including ARMA, ARFIMA, GARCH, GJR-GARCH, and two-stage diagnostic-driven model
  selection via ADF, Ljung-Box, GPH, ARCH-LM, and Engle-Ng sign-bias tests.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-time-series-model
  repository_url: https://github.com/quantskills/skill-time-series-model
  project_type: skill
  collection: quant-research-tools
  license: GPL-3.0
  category: tooling
  tags: [time-series, arma, arfima, garch, gjr-garch, arch, volatility, long-memory, leverage, quant-research]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 两阶段检测驱动建模：ADF 前提→均值方程(LB/GPH/ACF-PACF：Constant/ARMA/ARFIMA)+方差方程(ARCH-LM/Engle-Ng：Constant/GARCH/GJR)，均值×方差 9 种组合全覆盖（常数均值+不变方差也建模为 flow_d）。
  summary_en: Two-stage diagnostic-driven modeling: ADF gate, then mean equation (LB/GPH/ACF-PACF → Constant/ARMA/ARFIMA) and variance equation (ARCH-LM/Engle-Ng → Constant/GARCH/GJR-GARCH); all 9 mean×variance combos are modeled (constant+constant = flow_d).
---

# Time Series Model

Use this skill to model a **return / differenced series** (stationary) after diagnosing
its dynamics. It runs a **two-stage** detection — a mean equation and a variance
equation — picks one of four modeling flows (all 9 mean×variance combos are modeled),
fits with AIC/BIC order selection, validates residuals with Ljung-Box, and writes a Chinese
conclusion-first Markdown report with diagnostics, parameters, residual tests, and an
in-sample fit + forward forecast plot.

## Core Workflow

1. Input must be a **return / differenced series**. `run_diagnostics` runs ADF first;
   a non-stationary series raises `NonStationaryError` (pass returns, not price).
2. **Mean equation** — decided by Ljung-Box (short-lag autocorrelation) + GPH (long
   memory / fractional integration d) + ACF/PACF (auxiliary):
   - no autocorrelation (Ljung-Box) → `Constant`
   - else long memory (GPH `|d|>0.1` & p<0.05) → `ARFIMA`
   - else → `ARMA`
3. **Variance equation** — decided by ARCH-LM (heteroskedasticity) + Engle-Ng sign-bias
   (leverage / asymmetry):
   - no ARCH → `Constant`
   - ARCH + leverage (Engle-Ng) → `GJR-GARCH` (asymmetric, `o=1`, captures the sign effect)
   - ARCH, no leverage → `GARCH`
4. `classify_model` maps the (mean, variance) pair to a flow (all 9 combos modeled):
   - `flow_d` (Constant + Constant) → fit constant model (μ, σ²; random-walk-with-drift baseline), residual Ljung-Box
   - `flow_a` (mean model + Constant variance) → ARMA/ARFIMA, residual Ljung-Box
   - `flow_b` (Constant mean + variance model) → GARCH/GJR-GARCH on de-meaned residuals, double LB
   - `flow_c` (mean + variance) → iterated two-step: pick mean order → pick variance order →
     fix variance and re-select mean order (by mean_AIC+var_AIC) → final fit with best orders → double LB
5. Fit with `fit_model(diag, returns, ...)`; for an end-to-end report call
   `generate_model_report(returns, series_name=..., output_dir=...)`.
6. Return `report["markdown"]` or the written `.md` file. Conclusions before evidence.

> Note on EGARCH: `arch` 8.0's EGARCH carries only a `|z|` magnitude term and no sign
> term, so it cannot capture the leverage that Engle-Ng detects. The asymmetric member
> is therefore **GJR-GARCH** (`vol='GARCH', o=1`, which estimates a `gamma` leverage
> coefficient). ARFIMA uses a two-step filter (arch/statsmodels do not support
> fractional d): GPH estimates d → fractional-difference → ARMA on the differenced series.

## API Pyramid

| Layer | Use first | Purpose |
|---|---|---|
| Report API | `generate_model_report` | End-to-end user-facing Markdown report + plots |
| Modeling | `fit_model`, `flow_a`/`flow_b`/`flow_c`/`flow_d`, `fit_arma_mean`, `fit_arfima_mean`, `fit_constant_mean`, `fit_garch_var`, `fit_gjr_var` | Fit a chosen flow / atomic mean-variance component |
| Diagnostics | `run_diagnostics`, `adf_test`, `ljung_box_test`, `gph_test`, `arch_lm_test`, `engle_ng_sign_bias_test`, `acf_pacf`, `recommend_mean_equation`, `recommend_variance_equation`, `classify_model` | ADF gate + mean/variance detection |
| Helpers | `FitSummary`, `DiagnosticReport`, `NonStationaryError` | Result containers / custom workflows |

## Output Contract

Always produce:

- a flow, mean/variance equation verdict, and one-sentence conclusion
- ADF / Ljung-Box / GPH / ARCH-LM / Engle-Ng / ACF-PACF evidence
- selected model class and **optimal order** chosen by AIC/BIC (incl. ARFIMA `d`)
- fitted **parameter estimates** (incl. GJR `gamma` leverage coefficient when present)
- post-fit **Ljung-Box** results (residuals for `flow_a`/`flow_d`; standardized residuals and
  their squares for `flow_b`/`flow_c`) and a pass/fail conclusion
- a chart of actual series + in-sample fit + forward forecast
- caveats: short samples, conflicting tests, non-stationary inputs

## References

- `references/workflow.md` — the detect (two-stage) → model → validate flow
- `references/api.md` — public API map
- `references/interpretation.md` — how to read each test and model
- `references/report-format.md` — Markdown report template

## Boundary

This skill does **not** fetch data, run trading backtests, or generate trading
signals. It builds and validates statistical models only. Outputs are research
diagnostics, not orders.
