# Research Assistant — 投研助手

## Purpose

投研助手的核心职责：
1. **研报提取**：把研报/论文的量化思想、指标、回测方法与结果，结构化提取成思想卡（**只提取，不复现**）
2. **记录保存投研迭代过程**：改进原因、改进内容、回测结果、回测分析、改进建议等全过程记录
3. **辅助数据分析**：如波动率分析、行业排序等（生成/更新/回滚闭环）

投研方向分**三类平行能力**：

| 能力 | 输出目录 | 产出 |
|---|---|---|
| **研报提取**（**仓库根**） | `<仓库根>/research_report/` | `<slug>_main.md` —— 思想·指标·回测方法/结果 |
| └ **行业研报提取**（子能力） | `<仓库根>/research_report/industry_research/` | `<slug>_main.md` —— 背景·核心观点·投资建议（多要点六要素） |
| **数据分析** | `<工程>/01_data_analysis/analysis_XXX/` | records.md / analysis.py / result_view.html |
| **策略迭代** | `<工程>/02_strategy_iteration/strategy_XXX/` | main_idea.md / backtest_strategy/ / final_report.md |

> ★ **研报提取是跨项目的公共能力，输出不在工程内，而在仓库根 `research_report/`。**
> 理由：一篇研报会被多个工程、多次引用（如银河「变盘指数」同时被 analysis_001 与
> strategy_001 引用），按工程各存一份会重复且无法统一检索；把它当"文献库"而不是
> "工程产物"更符合实际用法。
> 工程内**不再创建** `research_report/`（`create_project.py` 的 SUBDIRS 已移除）。
> 路径解析：优先 `.env` 的 `RESEARCH_REPORT_ROOT`；未设则取"最近的含 `.git` 的上级目录"
> 下的 `research_report/`。

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
# 输出根 DEFAULT_ROOT：优先 .env 的 RESEARCH_PROJECTS_ROOT（本技能专用，直接指向工程父目录）；
#   回退 REPLICATION_ROOT/research-projects；再回退 ~/research-projects。
python scripts/check_data.py {project_dir} --needs 沪深300,中证500  # 或 成分股/期货
```
- 数据满足 → 按方向进入**研报提取** / **数据分析** / **策略迭代**
- 不满足 → 反馈缺失清单 + 终止，提示用 skill-bigquant-sdk 拉取
- （研报提取不消费本地数据，也不需要数据检查，可直接建目录开工）

### 2. 研报提取（`<仓库根>/research_report/`，**与工程无关**）

把一份研报/论文/链接/文本转成**结构化的量化思想卡**。**只提取，不复现**。

**输入**：网页 URL / 本地 PDF / 粘贴文本。

**读 PDF（先跑这一步）**：
```bash
python scripts/pdf_extract.py <pdf> [--pages 3-22] [--dpi 150]
# auto 判定：有文本层 → 出 .txt（直接 Read）；
#           图片型/扫描件 → 逐页渲染 PNG（用 Read 工具看图，多模态而非 OCR，
#           好处是图表/净值曲线/公式都能看懂）
```
⚠ 本机没装 poppler 的 `pdftoppm`，**Read 工具无法直接打开 PDF** —— 图片型 PDF 必须先渲染。
券商研报多为图片型（实测银河证券某 25 页报告抽样平均仅 2 字符/页）。
免责声明页通常可跳过，用 `--pages` 限定可省 token。

**取简称（slug）**：`<关键思想英文>_<机构拼音>_<YYYYMMDD>`，纯小写英文+数字+下划线。
例：`llt_low_lag_trendline_dongbei_20240115`、`support_resistance_quantile_bohai_20230520`。

**提取 8 节**（模板 `templates/research_report_template.md`）：
元信息 / **研报背景** / **现象观察** / **量化思路** / **量化算法·指标** / **回测方法** /
**回测结果** / 可复现性评估 / 与本工程关联。

> 核心是**量化思路 · 量化指标 · 回测方法 · 回测结果**四节；其余为上下文。
> **不需要复现回测**——原文数字如实记为「原文口径，未复现验证」。

**落盘**：`<仓库根>/research_report/<slug>_main.md`（目录不存在则创建）。
**不要**写进任何工程的 `01_data_analysis/` 或工程根——研报是公共文献库。

**铁律**：① 只提取不复现 ② 严禁脑补（原文未明确写「原文未明确」）③ 现象与思路分开记
④ 公式照抄 + 变量逐个解释（给到"照着能写代码"的精度）。

**登记引用**：被后续分析/策略引用时，在 `04_delivery/final_report.md` 的「引用研报」节**追加**一行。

#### 2.1 行业研报提取（子能力，`<仓库根>/research_report/industry_research/`）

面向**行业/宏观类研报**（重观点与逻辑链，而非量化算法）。与研报提取的关系：
**输入 / 读 PDF / 取简称（slug）/ 落盘 / 铁律 / 引用登记、与其他能力衔接完全一致**，
仅三处不同——

- **输出目录**：`<仓库根>/research_report/industry_research/<slug>_main.md`（不存在则创建）
- **提取内容**（模板 `templates/industry_research_template.md`）：
  1. **研报背景**（含可选的观察现象）
  2. **核心观点**——常为多要点，每个要点按六要素提取：观点内容 / 逻辑依据 / 事实依据 /
     数据依据（均**忠实提取**）+ 观察指标及说明（可选）+ 观点解释（**分析者解读**，
     从经济学/产业规律角度，须与原文内容严格区分）
  3. **投资建议**——同多要点、同六要素模式，建议解释须结合对应观点
- **多要点拆分**：并列因素各算一个要点。例「地产行业三个关键因素：公积金利率、
  核心城市房价、人民币汇率」→ 拆 3 个要点分别提取与解释

### 3. 数据分析（01_data_analysis/analysis_XXX/）
每个分析一个 id（analysis_001, 002...），含 records.md / analysis.py / result_view.html：

- **比较**：新思路与已有分析相近 → 提示用户"更新"或"生成"
- **生成**：新思路 → 写 analysis.py + 运行 → 记录 records.md（main_idea + result）
- **更新**：按新思路更新算法 → 覆盖 analysis.py + result_view.html → records.md 追加更新条目（保留历史）
- **回滚**：按记录恢复到某次分析 → 覆盖代码/视图 → records.md 记录回滚点

### 4. 策略迭代（02_strategy_iteration/strategy_XXX/）
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

### 5. 最终报告
`04_delivery/final_report.md`：方向级数据分析/策略结果总结 + **引用研报清单** + 产物清单。
有任何分析/策略引用了研报，必须在该报告的「引用研报」节登记（模板见 `templates/final_report_template.md`）。

## References

- `references/data_sources.md`：数据规范（指数/成分股/期货覆盖）
- `references/workflow.md`：三类能力详解（研报提取 / 数据分析 / 策略迭代）

## Scripts

- `scripts/pdf_extract.py`：**PDF 提取**——auto 判定文本层/图片型；图片型逐页渲染 PNG 供 Read 看图
- `scripts/create_project.py`：建工程目录（`01_data_analysis` / `02_strategy_iteration` / `04_delivery`；**不含 `research_report`**——那是仓库根的公共库）
- `scripts/check_data.py`：数据检查
- `scripts/local_backtest.py` / `local_portfolio_backtest.py`：回测引擎（单标的 CTA / 组合）

## Templates

- `templates/research_report_template.md`：**研报提取**思想卡（8 节，含 slug 命名规则）
- `templates/industry_research_template.md`：**行业研报提取**观点卡（背景/核心观点/投资建议，多要点六要素）
- `templates/records_template.md`：数据分析记录（生成/更新/回滚）
- `templates/main_idea_template.md`：策略思路（时序/因子两模板）
- `templates/final_report_template.md`：综合报告（含「引用研报」节）
- `templates/portfolio_strategy.py`：组合策略 5 接口模板
