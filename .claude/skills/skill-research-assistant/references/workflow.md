# 投研工作流规范（workflow.md）

## 三类投研方向（平行能力）

初始化后按用户输入进入：**研报提取** / **数据分析** / **策略迭代**。

| 能力 | 输出目录 | 产出 |
|---|---|---|
| 研报提取（**仓库根**） | `<仓库根>/research_report/` | `<slug>_main.md`（思想+指标+回测方法/结果，**不复现**） |
| └ 行业研报提取（子能力） | `<仓库根>/research_report/industry_research/` | `<slug>_main.md`（背景+核心观点+投资建议，多要点六要素） |
| 数据分析 | `01_data_analysis/analysis_XXX/` | records.md / analysis.py / result_view.html |
| 策略迭代 | `02_strategy_iteration/strategy_XXX/` | main_idea.md / backtest_strategy/ / final_report.md |

三者**互不依赖**：研报提取是"读文献"，数据分析是"探数据"，策略迭代是"做回测"。
下游引用关系单向：研报提取 → （可选）数据分析 / 策略迭代。

## 研报提取（`<仓库根>/research_report/`，**不在工程内**）

> ★ 研报提取是**跨项目公共能力**：一篇研报会被多个工程引用（如银河「变盘指数」同时被
> analysis_001 与 strategy_001 引用），按工程各存一份会重复且无法统一检索。
> 故产出统一落**仓库根** `research_report/`，工程内不再创建该目录。
> 路径解析：`.env` 的 `RESEARCH_REPORT_ROOT` → 否则"最近含 `.git` 的上级目录"下的 `research_report/`。

**把一个研报/论文/链接/文本，转成结构化的量化思想卡。**

### 铁律

1. **只提取，不复现**。不写代码、不跑回测。原文给的数字标注「原文口径，未复现验证」。
2. **严禁脑补**。原文未明确的参数/设定，一律写「原文未明确」，不得替作者补全。
3. **现象与思路分开记**。现象=作者观察到的事实（含统计量），思路=由此推出的可交易假设。
   两者混在一起会导致后续无法判断思路的依据是否成立。
4. **公式照抄 + 变量解释**。量化指标必须给到「照着能写代码」的精度。

### 步骤

1. **取简称（slug）**：`<关键思想英文>_<机构拼音>_<YYYYMMDD>`，纯小写英文+数字+下划线。
   关键思想 2~4 个英文单词；机构用拼音（dongbei / bohai / huatai / zheshang / huaxi / gf …）；
   日期 = 研报发布日。例：`llt_low_lag_trendline_dongbei_20240115`。
2. **按模板提取**：`templates/research_report_template.md` —— 8 节：
   元信息 / 研报背景 / 现象观察 / 量化思路 / 量化算法·指标 / 回测方法 / 回测结果 /
   可复现性评估 / 与本工程关联。
   （核心是 **量化思路 · 量化指标 · 回测方法 · 回测结果** 四节，其余为上下文）
3. **落盘**：`<仓库根>/research_report/<slug>_main.md`（**目录不存在则创建**）。
4. **登记引用**：若该研报被后续分析/策略引用，在 `04_delivery/final_report.md` 的
   「引用研报」节追加一行（**只能追加，不得改写历史条目**）。

### 行业研报提取（子能力，`<仓库根>/research_report/industry_research/`）

面向**行业/宏观类研报**——重观点与逻辑链，而非量化算法。研报属于哪类由内容判断：
以观点/建议为主线 → 行业研报提取；以量化思路/回测为主线 → 母能力研报提取。

**与母能力完全一致的部分**：输入（网页 URL / 本地 PDF / 粘贴文本）、读 PDF
（`scripts/pdf_extract.py`，先跑这一步）、取简称（slug 规则同母能力）、
铁律（只提取不复现 / 严禁脑补 / 数字标「原文口径，未复现验证」）、落盘（不存在则创建）、
引用登记、与其他能力的衔接（见下节，同样适用）。

**仅两处不同**：

1. **输出目录**：`<仓库根>/research_report/industry_research/<slug>_main.md`（独立目录，与母能力产出不混放）。
2. **提取内容**（模板 `templates/industry_research_template.md`，多要点结构）：
   - **研报背景**：作者为何写、行业与政策环境；含可选的**观察现象**（原文有则忠实记录）
   - **核心观点**（常为多要点）：每个要点一张六要素表——
     | 要素 | 说明 |
     |---|---|
     | 观点内容 | 忠实提取研报原文主张 |
     | 逻辑依据 | 忠实提取研报给出的推理链条 |
     | 事实依据 | 忠实提取研报列举的事实 |
     | 数据依据 | 忠实提取研报引用的数据（标「原文口径」） |
     | 观察指标及说明（可选） | 忠实提取研报的跟踪指标（名称/含义/阈值或方向） |
     | 观点解释 | **分析者解读**（非原文）：从经济学、产业规律等角度解释 |
   - **投资建议**（同多要点、同六要素模式）：建议内容 / 逻辑依据 / 事实依据 / 数据依据 /
     观察指标及含义说明（可选）/ 建议解释（**分析者解读**，须结合对应核心观点与依据）
   - **多要点拆分**：并列因素各算一个要点。例：观点「地产行业三个关键因素：公积金利率、
     核心城市房价、人民币汇率」→ 每个因素独立成块，分别按六要素提取与解释；
     投资建议含多条时同理。

**解读与提取的边界**（本子能力特有）：六要素前五项一律**忠实提取**（原文没写就标
「原文未明确」）；只有「观点解释 / 建议解释」是分析者解读，须明确标注，不得伪装成原文内容。

**模板生成**：按 `templates/industry_research_template.md` 逐节填充（独立模板，
与母能力 `research_report_template.md` 并列，不共用）。

### 与其他能力的衔接

- 研报提取完成后，若用户要**验证**其中某个指标 → 立 `01_data_analysis/analysis_XXX/`，
  在 records.md 的 main_idea 注明「承接 `<仓库根>/research_report/<slug>_main.md`」。
- 若要**实盘化**某个思路 → 立 `02_strategy_iteration/strategy_XXX/`，
  在 main_idea.md 注明引用来源。
- **不复现的回测**：研报里的回测结果只做记录，不在 `<仓库根>/research_report/` 下写任何回测代码。

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
6. **指标铁律**：回测结束后，净值、统计指标（年化/Sharpe/回撤/胜率等）与相应可视化**必须用生成的交易记录（trades_paired / 交易明细）直接推算**，严禁另算一套。交易记录是策略实际执行的唯一事实源；若引擎指标与交易记录推导不符，修引擎或明确标注口径差异，不得静默采用。

### 迭代不可变（铁律）

- 每次迭代**严禁修改之前迭代的输出内容**。一次迭代完成后，其目录内全部内容即冻结：`main_idea.md`、`backtest_strategy/`（strategy.py、config.json、backtest_logs/、backtest_report.html）、`final_report.md` 都不得在后续迭代中修改、覆盖或删除。
- 想改进上一迭代 → 新建 `strategy_00X+1`，main_idea.md 注明"承接 strategy_00X"，只迁移需要的资产。
- 唯一允许追加的两处：`manifest.json`（追加 strategy_iterations 条目）与 `04_delivery/final_report.md`（追加该迭代 section）。二者只能追加，不得改写历史条目。

### shared/ 共享目录（固定输出）

- 工程根 `shared/` 为**固定输出目录**：多迭代共用的代码（取数、指标算法、成分、共享参数等）放这里，一个文件一个职责。
- 各迭代策略只 `import`（如 `from shared.plateau_algo import ...`），**严禁**把共享逻辑复制内联进各自 strategy.py。
- 与迭代目录同等冻结：`shared/` 下文件一经被已完成迭代依赖即视为固定，后续迭代不得修改；需要新行为时新增文件（如 `plateau_algo_v2.py`）并在文件头注释说明承接关系。

## 最终报告（04_delivery/final_report.md）

方向级总结：所有数据分析/策略迭代的结果 + **引用研报清单** + 产物清单。

### 引用研报节（必填，若无引用则写「无」）

凡本工程的分析/策略**引用了某篇研报的思想或指标**，必须在此登记：

```markdown
## 引用研报

| 简称 | 研报标题 | 机构 | 日期 | 提取文件 | 被谁引用 |
|---|---|---|---|---|---|
| llt_low_lag_trendline_dongbei_20240115 | 低延迟趋势线与交易性择时 | 东北证券 | 2024-01-15 | `<仓库根>/research_report/…_main.md` | analysis_009 |
```

**只能追加，不得改写历史条目。**

## 迭代规范

- 每次改进记录：原因 / 内容 / 回测结果 / 分析 / 建议
- 所有历史保留（追加），不覆盖删除
- **严禁修改之前迭代的输出内容**：已完成迭代与已投产的 `shared/` 文件一律冻结，改进 = 新建下一迭代（承接注明在 main_idea.md），不回头改写
- 多迭代共享的文件统一放 `shared/`（固定输出目录），各迭代只 import 不内联
