# skill-report-replication-ts

**Time-series CTA / trend-following report replication skill.** Turns a time-series
CTA paper, PDF, webpage, or text into a complete replication package:

**Full Chinese translation → strategy-logic extraction (entry / stop-loss / take-profit)
→ backtest strategy code → real local backtest → Chinese evaluation report → delivery summary**

## Difference from skill-report-replication-factor

| Dimension | -factor (cross-sectional) | **-ts (time-series CTA)** |
|-----------|---------------------------|---------------------------|
| Report type | stock/asset cross-sectional factor | trend-following / momentum / reversal timing |
| Core validation | IC / quantile / long-short | **entry/stop/target + NAV/Sharpe/Calmar** |
| Factor-validation phase | yes | **none** |
| Cross-sectional analysis | yes | no (time-series has no cross-section) |

## Inputs

- Webpage (URL, e.g. WeChat article)
- Local PDF
- Text

## Data source (key)

Market data is supplied by the user as an **external local path**
(`local_backtest.py --market-data <CSV/Parquet>`). **The skill itself never downloads
market data.** Provenance/path/symbols/period are recorded in `manifest.json`.

## Workflow (7 steps)

1. Initialize — scaffold + manifest
2. Extract & Translate — Chinese translation
3. Extract Strategy Logic — entry / stop-loss / take-profit
4. Generate & Run Backtest — strategy.py + local backtest
5. Strategy Evaluation Report — Chinese HTML (NAV / drawdown / regime / benchmark)
6. Final Delivery — summary
7. Quality Gate — automated checks

## License

GPL-3.0
