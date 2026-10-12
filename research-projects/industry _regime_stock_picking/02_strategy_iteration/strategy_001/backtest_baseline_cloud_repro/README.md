# 云端原版策略的本地复现（**正式 baseline**）

> 承担 strategy_001 的「云端原版 = 恒反转」基准角色。
> 建立日期 2026-10-12 ｜ 引擎 `local_weight_backtest.py`（对标 bigtrader `handle_data_weight_based`）

## 它是什么

用户云端 BigQuant 策略（变盘指数行业轮动 + 行业内四因子**恒反转**选股）在**本地的等价复现**，
口径已与云端**逐值对齐**（选股集合 + 权重均一致）。**这是「基线」，不是「迭代一」**
（迭代一 = 选股层因子方向跟随 regime 切换，见 `../backtest_strategy/`）。

## 结果

| 口径 | 总倍数 | 累计 | 年化 | 夏普 | 最大回撤 | 成交 |
|---|---|---|---|---|---|---|
| **本地（本目录）** | 3.600x | +260.0% | 14.65% | 0.904 | −24.3% | 4,864 |
| **云端**（同窗 2017-05-15 ~ 2026-08-21） | 3.797x | +279.7% | 15.61% | — | — | 4,079 |

**比值 1.055x。** 云端全区间（到 2026-09-21）为 4.177x / 16.5%。剩余差主要在**引擎**——
本地引擎按**原始价**估值、不记分红现金（≈1.09x）；选股层已无差异。

## 与云端对齐的口径（六处）

| 项 | 取值 |
|---|---|
| 股票池 | **全市场**（行业源 = `stock_prefactors_attr.sw_level_index_code`，与云端 `cn_stock_prefactors` 同源） |
| 因子窗口 | **周频**（信号日序列上滚动，复刻云端 DAI 把 `date IN` 下推进 CTE 的行为） |
| 窗口起点 | **2016-12-30**（由云端真实首笔成交 2017-05-15 反标定） |
| 成交/估值价 | **原始价**（`后复权 ÷ adjust_factor`） |
| 引擎 | `local_weight_backtest.py`：三层对标 `handle_data_weight_based`（调仓模板/周期/`order_target_percent`） |
| 过滤 | `st_status=0 ∧ suspended=0 ∧ list_days>252 ∧ amount>2e7 ∧ 有行业归属`，**且剔除复合分为 NaN 的候选** |

## 对齐证据（2026-10-12）

- **选股集合**：与云端 `holdings_log.parquet` 逐周 **173/173 = 100% 完全一致**
- **权重**：最大绝对差 **1.3e-14**
- **对照云端真实逐日持仓**（`csv_持仓.csv`，含导出运行）：逐周集合一致 **94.3%**（2019 起 ~98–100%）

## 怎么复现

```bash
cd "research-projects/industry _regime_stock_picking"
IND=prefactors python shared/build_stock_panel_weekly.py
IND=prefactors UNIVERSE=weekly MODE=baseline PRICE=raw python shared/build_weekly_targets.py
python shared/expand_targets_daily.py
python .claude/skills/skill-research-assistant/scripts/local_weight_backtest.py "<project_dir>" \
  --market-data shared/_cache/engine_market_weekly_indpre_rawpx.parquet \
  --targets    shared/_cache/targets_daily_indpre.parquet \
  --output-dir 02_strategy_iteration/strategy_001/backtest_baseline_cloud_repro/backtest_logs
```

## ⚠️ 注意：不要和 `../backtest_strategy_baseline/` 混淆

`../backtest_strategy_baseline/` 是 **2026-09-23 的旧跑**，用的是**三指数池 + 日频因子 + 信号引擎**
（+83.2% / 夏普 0.433，与云端差 **~2 倍**）——它**只**能当「迭代一的同口径对照组」，
**不能**当云端原版基线。云端原版基线以本目录为准。
