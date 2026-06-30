---
name: time-series-analysis
description: Use when an agent needs conclusion-first diagnostics or Markdown reports for financial time series, including KDE/QQ distribution checks, Hurst/ADF/KPSS stationarity, Log diff analysis, spread half-life, and Engle-Granger cointegration.
quantSkills:
  organization: https://github.com/quantskills
  repository: quantskills/skill-time-series-analysis
  repository_url: https://github.com/quantskills/skill-time-series-analysis
  project_type: skill
  collection: quant-research-tools
  license: GPL-3.0
  category: tooling
  tags: [time-series, stationarity, cointegration, mean-reversion, quant-research]
  platforms: [claude-code, codex, openclaw, cursor]
  language: zh-en
  status: draft
  validation_level: runnable
  maintainer_type: community
  requires: []
  summary_zh: 结论先行的时序分析 Skill：原始序列、Log diff、分布、平稳性、协整和半衰期。
  summary_en: Conclusion-first time-series diagnostics for original series, Log diff, distributions, stationarity, cointegration, and half-life.
---

# Time Series Analysis

Use this skill to diagnose price series, spreads, or pairs before choosing a
model, factor, or strategy workflow. For user-facing answers, start with the
report API so the agent can return a Chinese, conclusion-first Markdown
diagnostic with evidence and research directions.

## Core Workflow

1. For a single price series, call `generate_time_series_report(...)`.
2. For a spread or price difference, call `generate_spread_report(...)`.
3. For two related series, call `generate_pair_cointegration_report(...)`.
4. Use `report.to_markdown()` or the written `.md` file as the user-facing answer.
5. For custom workflows, use `analyze_price_series`, `analyze_spread`, or `analyze_pair_cointegration`.
6. Report conclusions before evidence; phrase strategy output as research directions, not orders.

## API Pyramid

| Layer | Use first | Purpose |
|---|---|---|
| Report API | `generate_time_series_report`, `generate_spread_report`, `generate_pair_cointegration_report`, `interpret_time_series_analysis` | User-facing Markdown reports |
| Main API | `analyze_price_series`, `analyze_spread`, `analyze_pair_cointegration` | Agent-facing conclusions |
| Diagnostics | `distribution_diagnostics`, `stationarity_diagnostics`, `log_diff_diagnostics`, `mean_reversion_diagnostics`, `cointegration_diagnostics` | Composable workflows |
| Helpers | `kde_analysis`, `qq_analysis`, `TimeSeriesAnalyzer` | Advanced or custom analysis |

## Output Contract

Always produce:

- a short conclusion from `result.summary`
- key evidence tables or charts
- plain-language stationarity, memory, trend, and distribution interpretation
- original-series evidence plus Log diff 1/5/10 stationarity, KDE, and QQ diagnostics for price reports
- quant research directions for strategy and factor exploration
- explicit caveats when sample length is short, tests conflict, or residuals are unstable

## References

- `references/workflow.md` - recommended agent workflow
- `references/api.md` - public API map
- `references/interpretation.md` - Hurst/ADF/KPSS, KDE/QQ, half-life, cointegration interpretation
- `references/report-format.md` - Markdown report template
- `references/anti-patterns.md` - mistakes that make diagnostics misleading

## Boundary

This skill does not fetch data, run backtests, train ML models, or generate
trading signals. It provides research diagnostics only.
