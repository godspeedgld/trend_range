# industry _regime_stock_picking — 综合报告

> 方向：行业 regime 选股（行业信息在选股框架中的用法：方向 vs 过滤）。

## 一句话结论

**行业信息在「买超跌」框架里是方向、在「买突破」框架里只是硬过滤**（analysis_001 六轮全负 +
strategy_001 验证）；且进一步：**选股层的「买超跌」方向本身是普适的，不随 regime 变化** ——
regime 该管「买哪个行业」，不该管「买什么样的股」。

## 数据分析结果

| 分析 | 思路 | 关键结果 |
|---|---|---|
| analysis_001 | 银河「变盘指数」当入场闸门/硬过滤/风格开关/行业池（六轮） | **全部负结果**。W2 基准 +186.7% → 最好 +127.2%（二级指数）、最差 +62.6%（行业池）。核心洞察：行业信息在买突破框架下只是过滤器 |
| analysis_002 | 财通 PB 回归法验证 + 0625 预测回验 | 方法可复现（保利修复空间 177% vs 原文 170%）；**0625「温和上行」兑现 +7.4%**；BigQuant `stock_valuation.pb` = **全权益非归母**（含少数股东），已修正 |

## 策略迭代结果

| 策略 | 思路 | 回测结果（trades 口径） | 分析/改进 |
|---|---|---|---|
| strategy_001 | 变盘指数行业轮动 · 迭代一：选股层四因子方向跟随 regime 切换（动量期全取正） | 迭代一 +72.1% / Sharpe 0.286 / 回撤 −42.2% / 689 笔<br>**基准（恒反转=云端原版）+100.5% / Sharpe 0.496 / 回撤 −24.2% / 703 笔** | **假设被否**（主口径 trades）。随机化对照（20 次随机选股）显示基准落在随机分布 **50 分位** → **选股层四因子 ≈ 随机选股**〔该实验待用技能引擎重建〕。下一步：稳定性过滤证伪（随机空仓 63.8%）、拆行业层净贡献、换因子 |

## 引用研报

| 简称 | 研报标题 | 机构 | 日期 | 提取文件 | 被谁引用 |
|---|---|---|---|---|---|
| `rotation_regime_index_yinhe_20260701` | 变盘指数（行业轮动 regime） | 银河证券 | 2026-07-01 | `research_report/rotation_regime_index_yinhe_20260701_main.md` | analysis_001（六轮）、**strategy_001（T′ 口径）** |
| `property_dip_accumulation_caitong_20260130` | 地产敢左侧（筹码四低） | 财通证券 | 2026-01-30 | `research_report/industry_research/property_dip_accumulation_caitong_20260130_main.md` | （背景，暂无引用） |
| `property_reversal_targets_caitong_20260531` | 地产反转标的（RNAV 折价） | 财通证券 | 2026-05-31 | `research_report/industry_research/property_reversal_targets_caitong_20260531_main.md` | **analysis_002** |
| `property_hk_mapping_timing_caitong_20260625` | 地产港股映射与时点（两阶段状态机） | 财通证券 | 2026-06-25 | `research_report/industry_research/property_hk_mapping_timing_caitong_20260625_main.md` | **analysis_002**（0625 预测回验） |
| `property_tier2_stabilization_caitong_20260915` | 地产空间分化（核心城市土储） | 财通证券 | 2026-09-15 | `research_report/industry_research/property_tier2_stabilization_caitong_20260915_main.md` | （背景，暂无引用） |
| `earnings_prosperity_rotation_bohai_20210930` | 业绩景气度行业轮动 | 渤海证券 | 2021-09-30 | `research_report/earnings_prosperity_rotation_bohai_20210930_main.md` | （研报提取，暂无引用） |
| `qrf_distribution_etf_rotation_yinhe_20251222` | QRF 分布预测 + 科技类 ETF 轮动 | 银河证券 | 2025-12-22 | `research_report/qrf_distribution_etf_rotation_yinhe_20251222_main.md` | （研报提取，暂无引用） |

> 另：strategy_001 承接**用户云端 BigQuant 策略**（非研报，无提取文件）。

## 综合结论

- **analysis_001**：变盘指数当闸门/过滤/风格开关**都没有正向价值** —— 行业信息在「买突破」
  框架下只是重复筛 + 过度收紧（「排序 ≫ 开关」定律第 3~6 次兑现）。
- **strategy_001**：把它当**方向**用（云端策略族）本是对的方向，但迭代一证明
  **该管的只是"买哪个行业"，不该管"买什么样的股"**；且更根本 ——
  **这个策略族的选股层四因子没有 alpha**（≈ 随机），收益只能来自行业层 + 稳定性过滤。
  这修正了先前"行业层切动量/选股层永远反转 = 框架内部矛盾"的诊断：那个分工**是对的**。

## 跨工程数据陷阱（复现本工程任何回测前必读）

1. **`trading_days` 表不是 A 股交易日历** —— 含 167 个实际休市日（2015-02-18、2017-04-03…）。
   拿它算"下一交易日"会误剔「信号日后紧跟长假」的整周。改用 `stock_bar1d` 的实际日期（2,828 天）。
2. **`stock_bar1d.close` 已是后复权价** —— 收益用 `close/pre_close − 1`（含分红再投资）；
   **绝不再乘 `adjust_factor`**（双重复权）；**不用 `change_ratio`**（未复权，除权日偏差达 9.9%）。
3. **`stock_industry_sw_bar1d` 需剔除 `801020.SWI`**（已废弃的「采掘」，与 801950 煤炭 +
   801960 石油石化在 2015-2021 重叠）。
4. **`上市>252` 会被池子起点截断** —— 首个交易日就在的股须视为已满 252 天。
5. **收益极度依赖尾部的策略族，变体比较必须配随机化对照** —— 本工程实测随机选股 20 次的
   收益跨度达 176pp，不配对照会把路径噪声当成 alpha。
6. **技能引擎 `local_portfolio_backtest.py` 漏算平仓日隔夜收益** —— 平仓在 d+1 开盘执行，
   引擎把持仓收益记到 `close[d]` 为止，未计入 `close[d]→open[d+1]` 段（本工程实测差 ~17pp）。
   trades 口径已计入。另：引擎成本为**对称双边**，不支持"买 0.03%/卖 0.13%"的不对称设定。

## 产物清单

| 产物 | 路径 |
|---|---|
| 研报提取 | `research_report/`（4 篇量化 + 5 篇行业） |
| 数据分析 | `01_data_analysis/analysis_001/`、`analysis_002/` |
| 策略迭代 | `02_strategy_iteration/strategy_001/`（main_idea.md · backtest_strategy/ · backtest_strategy_baseline/ · final_report.md） |
| 共享代码 | `shared/`（build_panel · build_stock_panel · build_weekly_targets · targets_lookup · from_trades） |
| 本报告 | `04_delivery/final_report.md` |
| 工程清单 | `manifest.json` |
