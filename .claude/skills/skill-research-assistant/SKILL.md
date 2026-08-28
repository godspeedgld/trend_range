# Research Assistant — 投研助手

## Purpose

投研助手的核心职责：
1. **记录保存投研迭代过程**：改进原因、改进内容、回测结果、回测分析、改进建议等全过程记录
2. **辅助数据分析**：如波动率分析、行业排序等（生成/更新/回滚闭环）

投研方向分两类：**数据分析** 和 **策略迭代**。

## 数据输入（本技能不下载任何数据）

默认使用本地 warehouse（`data_cache/bigquant_warehouse`）。数据分三类（默认日线）：

| 类型 | 品种 | 本地覆盖 |
|------|------|---------|
| **指数** | 沪深300(000300.SH)、中证500(000905.SH)、中证1000(000852.SH)、中证2000(932000.CSI)、创业板指(399006.SZ)、科创50(000688.SH) | **仅沪深300**（2005~今） |
| **成分股** | 上述指数成分股所有日线 | ❌ 本地无（仅 1 只股票单月） |
| **期货** | 主要商品期货 | ❌ 本地无 |

> 缺失数据需先用 `skill-bigquant-sdk` 拉取入库，本技能只消费已入库数据。

## 铁律：严禁使用未来数据

- **每日收盘决策只用 ≤t 日数据**：所有指标计算截至当前日为止，不得引用 t 日之后的任何价格/成分/因子
- **执行在次日开盘**：t 日收盘生成的开仓池/平仓池，t+1 日开盘执行
- **股票池用当日成分**：指数增强类策略的可选股票池，必须用**当日**成分股（查 index_component 当日记录），严禁用历史全量成分并集或期末成分（前视）
- 回测引擎与策略代码任何一处使用未来数据，结果作废重写

## Workflow

### 1. 初始化
用户明确给出投研方向 → 建工程目录 + **数据检查**：
```bash
python scripts/create_project.py --title X --report-id Y [--root Z]
python scripts/check_data.py {project_dir} --needs 沪深300,中证500  # 或 成分股/期货
```
- 数据满足 → 按方向进入数据分析或策略迭代
- 不满足 → 反馈缺失清单 + 终止，提示用 skill-bigquant-sdk 拉取

### 2. 数据分析（01_data_analysis/analysis_XXX/）
每个分析一个 id（analysis_001, 002...），含 records.md / analysis.py / result_view.html：

- **比较**：新思路与已有分析相近 → 提示用户"更新"或"生成"
- **生成**：新思路 → 写 analysis.py + 运行 → 记录 records.md（main_idea + result）
- **更新**：按新思路更新算法 → 覆盖 analysis.py + result_view.html → records.md 追加更新条目（保留历史）
- **回滚**：按记录恢复到某次分析 → 覆盖代码/视图 → records.md 记录回滚点

### 3. 策略迭代（02_strategy_iteration/strategy_XXX/）
- **思路**：main_idea.md 记录当前迭代思路
- **回测**：
  - **单标的 CTA**：reference_implementation.py + `local_backtest.py`（事件驱动引擎）
  - **组合/选股/因子**：strategy.py 实现 5 接口 + `local_portfolio_backtest.py`（开仓池/平仓池引擎，`templates/portfolio_strategy.py` 模板）
- **分析**：根据回测结果给出改进建议
- **报告**：final_report.md 综合思路/回测/分析/改进
- **质控**：quality_gate_check.py
- **指标铁律**：回测结束后，净值、统计指标与相应可视化**必须用生成的交易记录（trades）直接推算**，严禁另算一套——交易记录是策略实际执行的唯一事实源，独立归因路径易产生口径不一致或隐性前视
- **迭代铁律**：每次迭代**严禁修改之前迭代的输出内容**——已完成迭代目录（main_idea.md / backtest_strategy/ / final_report.md 等）一律冻结，不得覆盖、删除或改写。要改进只能新建下一迭代，并在 main_idea.md 注明承接哪次迭代。
- **共享代码**：多迭代共用的文件放工程根 `shared/`（固定输出目录），各迭代 strategy.py 只 import 不内联。已投产的 shared 文件同样冻结，新需求以新增文件方式扩展（详见 workflow.md）。

### 4. 最终报告
`04_delivery/final_report.md`：方向级数据分析/策略结果总结 + 产物清单

## References

- `references/data_sources.md`：数据规范（指数/成分股/期货覆盖）
- `references/workflow.md`：数据分析（生成/更新/回滚/比较）+ 策略迭代步骤详解

## Templates

- `templates/records_template.md`：数据分析记录（生成/更新/回滚）
- `templates/main_idea_template.md`：策略思路（时序/因子两模板）
- `templates/final_report_template.md`：综合报告
