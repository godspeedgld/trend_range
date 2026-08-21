# 投研工作流规范（workflow.md）

## 两类投研方向

初始化后按用户输入进入：**数据分析** 或 **策略迭代**。

## 数据分析（01_data_analysis/analysis_XXX/）

每个分析一个 id（analysis_001, 002, ...），目录含 records.md / analysis.py / result_view.html。

### 四种操作

1. **比较**：用户新思路与已有分析对比。相近 → 询问用户"更新原有分析"或"生成新分析"。
   - 更新 → 走更新流程；不更新 → 走生成流程
2. **生成**（新分析）：
   - 新建 analysis_00X/ 目录
   - 按思路写 analysis.py，运行得到结果
   - 写 records.md 记录 main_idea + result（保留历史）
3. **更新**（覆盖原分析）：
   - 更新 analysis.py（新算法），覆盖 result_view.html
   - records.md **追加**更新条目（main_idea + result），保留全部历史
4. **回滚**（对结果不满意）：
   - 按 records.md 历史恢复到某次分析
   - 重新生成 analysis.py + result_view.html，覆盖当前
   - records.md 记录回滚到哪次

### records.md 结构（见 templates/records_template.md）

- 每次生成/更新/回滚一个 section
- main_idea：本次思路（含更新原因）
- result：分析结果（关键数值/排序）

## 策略迭代（02_strategy_iteration/strategy_XXX/）

每个策略一个 id（strategy_001, ...）。

1. **思路**：main_idea.md 记录当前迭代思路（时序/因子模板见 templates）
2. **回测**：
   - backtest_strategy/reference_implementation.py 实现策略
   - 运行 local_backtest.py → backtest_logs/ + backtest_report.html + config.json
3. **分析**：根据回测结果给出改进建议
4. **报告**：final_report.md 综合思路/回测/分析/改进
5. **质控**：quality_gate_check.py

### 迭代不可变（铁律）

- 每次迭代**严禁修改之前迭代的输出内容**。一次迭代完成后，其目录内全部内容即冻结：`main_idea.md`、`backtest_strategy/`（strategy.py、config.json、backtest_logs/、backtest_report.html）、`final_report.md` 都不得在后续迭代中修改、覆盖或删除。
- 想改进上一迭代 → 新建 `strategy_00X+1`，main_idea.md 注明"承接 strategy_00X"，只迁移需要的资产。
- 唯一允许追加的两处：`manifest.json`（追加 strategy_iterations 条目）与 `04_delivery/final_report.md`（追加该迭代 section）。二者只能追加，不得改写历史条目。

### shared/ 共享目录（固定输出）

- 工程根 `shared/` 为**固定输出目录**：多迭代共用的代码（取数、指标算法、成分、共享参数等）放这里，一个文件一个职责。
- 各迭代策略只 `import`（如 `from shared.plateau_algo import ...`），**严禁**把共享逻辑复制内联进各自 strategy.py。
- 与迭代目录同等冻结：`shared/` 下文件一经被已完成迭代依赖即视为固定，后续迭代不得修改；需要新行为时新增文件（如 `plateau_algo_v2.py`）并在文件头注释说明承接关系。

## 最终报告（04_delivery/final_report.md）

方向级总结：所有数据分析/策略迭代的结果 + 产物清单。

## 迭代规范

- 每次改进记录：原因 / 内容 / 回测结果 / 分析 / 建议
- 所有历史保留（追加），不覆盖删除
- **严禁修改之前迭代的输出内容**：已完成迭代与已投产的 `shared/` 文件一律冻结，改进 = 新建下一迭代（承接注明在 main_idea.md），不回头改写
- 多迭代共享的文件统一放 `shared/`（固定输出目录），各迭代只 import 不内联
