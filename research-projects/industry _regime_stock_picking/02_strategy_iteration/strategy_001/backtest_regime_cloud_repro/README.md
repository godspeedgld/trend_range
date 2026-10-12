# strategy_001 迭代一 —— 云端对齐口径版

> 迭代一 = **选股层四因子方向跟随 regime 切换**（动量期 T′<0 全部取正 / 反转期维持取负）。
> 建立日期 2026-10-12 ｜ 引擎 `local_weight_backtest.py`（对标 bigtrader `handle_data_weight_based`）

## 为什么要重跑

原 `../backtest_strategy/`（2026-09-22）用的是**三指数池 + 日频因子 + 信号引擎**，
与云端不是同一口径 —— 拿它和云端（或和 `../backtest_baseline_cloud_repro/`）比是**苹果比橘子**。
本目录把迭代一放到**与云端逐值对齐的口径**下重跑，使它能与 baseline **同口径**对照。

## 结果（正确口径，同区间 2016-12 ~ 2026-08）

| | 总倍数 | 累计 | 年化 | 夏普 | 最大回撤 | 成交 |
|---|---|---|---|---|---|---|
| **迭代一（本目录）** | **4.779x** | **+377.9%** | 18.17% | 0.837 | −35.6% | 4,676 |
| baseline（`../backtest_baseline_cloud_repro/`，云端原版） | 3.600x | +260.0% | 14.65% | **0.904** | **−24.3%** | 4,864 |

## ⚠️ 结论随之变化（这是本版最重要的产出）

- **旧口径**（三指数池/日频/信号引擎）：迭代一 +72.1% / 夏普 0.286 **<** baseline +100.5% / 0.496
  → 当时判「**迭代一被否**」。
- **正确口径**：迭代一 **收益更高**（+377.9% vs +260.0%、年化 18.17% vs 14.65%），
  但**夏普更低**（0.837 vs 0.904）、**回撤深得多**（−35.6% vs −24.3%）。

⇒ 迭代一**不是被简单否定，而是「高收益·高风险」**：把选股层方向跟着 regime 镜像，
在动量期追强、赔率变好（收益↑），但波动/回撤明显放大（风险调整后更差）。
**旧口径的「被否」结论是口径偏差导致的，需修正。**

## 与 baseline 的唯一差别

行业层 / 信号稳定性过滤 / 持仓数（3 行业 × 2 只）/ 持仓缓冲 / 权重公式 / 成本**全部相同**，
**只差选股层四因子的方向**（迭代一随 regime 镜像；baseline 恒取负）。

## 怎么复现

```bash
cd "research-projects/industry _regime_stock_picking"
IND=prefactors UNIVERSE=weekly MODE=regime PRICE=raw python shared/build_weekly_targets.py
python shared/expand_targets_daily.py \
  --targets shared/_cache/weekly_targets_regime_weekly_indpre_rawpx.parquet \
  --out     shared/_cache/targets_daily_regime_indpre.parquet
python .claude/skills/skill-research-assistant/scripts/local_weight_backtest.py "<project_dir>" \
  --market-data shared/_cache/engine_market_weekly_indpre_rawpx.parquet \
  --targets    shared/_cache/targets_daily_regime_indpre.parquet \
  --output-dir 02_strategy_iteration/strategy_001/backtest_regime_cloud_repro/backtest_logs
```
