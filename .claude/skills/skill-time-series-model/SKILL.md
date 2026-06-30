---
name: time-series-model
description: Use when an agent needs to perform time series modeling on input data,
  including ARMA, AR+GARCH, ARMA+GARCH, and diagnostic-driven model selection via
  ADF, Ljung-Box, and ARCH-LM tests.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-time-series-model
  repository_url: https://github.com/quantskills/skill-time-series-model
  project_type: skill
  collection: quant-research-tools
  license: GPL-3.0
  category: tooling
  tags: [time-series, arma, garch, arch, volatility, mean-reversion, quant-research]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 检测驱动的时序建模 Skill：ADF/Ljung-Box/ARCH-LM/方差比四项检测自动判定随机游走、ARMA、AR+GARCH、ARMA+GARCH。
  summary_en: Diagnostic-driven time-series modeling: ADF/Ljung-Box/ARCH-LM/Variance-Ratio decide among RandomWalk, ARMA, AR+GARCH, ARMA+GARCH.
---

# Time Series Model

Use this skill to model a return/differenced series after diagnosing its dynamics.
The skill runs four checks (ADF, Ljung-Box, ARCH-LM, Variance-Ratio), decides the
model class, fits it with AIC/BIC order selection (random walk when no structure is
detected), validates the residuals with Ljung-Box again, and writes a Chinese
conclusion-first Markdown report with diagnostics, parameters, residual tests, and
an in-sample fit + forward forecast plot.

## Core Workflow

1. Make sure the input is a **return / differenced series**, not raw non-stationary price.
2. Run `run_diagnostics(returns)` → `ADF` + `Ljung-Box` + `ARCH-LM` + `Variance-Ratio`
   + a recommendation.
3. The recommendation routes the model:
   - no autocorrelation & no ARCH effect & VR does not reject → `RandomWalk`
   - autocorrelation & no ARCH effect → `ARMA`
   - autocorrelation & ARCH effect → `ARMA+GARCH`
   - no autocorrelation & ARCH effect → `AR+GARCH`
4. Fit with `fit_model(recommendation, returns, ...)` (or the dedicated
   `fit_random_walk` / `fit_arma` / `fit_ar_garch` / `fit_arma_garch`).
5. For an end-to-end report, call `generate_model_report(returns, series_name=..., output_dir=...)`.
6. Return `report["markdown"]` or the written `.md` file. Conclusions before evidence.

## API Pyramid

| Layer | Use first | Purpose |
|---|---|---|
| Report API | `generate_model_report` | End-to-end user-facing Markdown report + plots |
| Modeling | `fit_random_walk`, `fit_arma`, `fit_ar_garch`, `fit_arma_garch`, `fit_model` | Fit a chosen model class with AIC/BIC order selection |
| Diagnostics | `run_diagnostics`, `adf_test`, `ljung_box_test`, `arch_lm_test`, `variance_ratio_test`, `recommend_model` | ADF / Ljung-Box / ARCH-LM / Variance-Ratio checks |
| Helpers | `FitSummary`, `DiagnosticReport` | Result containers / custom workflows |

## Output Contract

Always produce:

- a recommendation and one-sentence conclusion from the four checks
- ADF / Ljung-Box / ARCH-LM / Variance-Ratio evidence tables
- selected model class and **optimal order** chosen by AIC/BIC (random walk = `(0,1,0)`)
- fitted **parameter estimates**
- post-fit **Ljung-Box** results (residuals for ARMA/RandomWalk; standardized
  residuals and squared standardized residuals for GARCH-type) and a pass/fail conclusion
- a chart of actual series + in-sample fit + forward forecast
- caveats: short samples, conflicting tests, non-stationary inputs

## References

- `references/workflow.md` — the detect → model → validate flow
- `references/api.md` — public API map
- `references/interpretation.md` — how to read ADF/Ljung-Box/ARCH-LM/VR, ARMA, GARCH
- `references/report-format.md` — Markdown report template

## Boundary

This skill does **not** fetch data, run trading backtests, or generate trading
signals. It builds and validates statistical models only. Outputs are research
diagnostics, not orders.
