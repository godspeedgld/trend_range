---
name: report-replication-ts
description: 'Reproduce time-series CTA research reports and papers end to end: full Chinese
  translation, strategy-logic extraction (entry / stop-loss / take-profit), standalone
  beginner-readable HTML evaluation report, BACKTEST strategy generation and local
  backtest execution, Chinese backtest explanation report, and final delivery summary.
  Use when the user provides a time-series CTA / trend-following / momentum paper,
  PDF, webpage, or text and asks for report replication, strategy replication, entry/stop/target
  extraction, BACKTEST strategy code, or a beginner-readable replication package. Not
  for cross-sectional factor reports (use skill-report-replication-factor instead).'
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  project_type: skill
  category: replication
  tags:
  - report-replication
  - time-series-cta
  - trend-following
  - backtest
  - html-report
  - chinese
  platforms:
  - claude-code
  - codex
  - openclaw
  - cursor
  status: stable
  validation_level: runnable
  summary_zh: 把一篇时序 CTA / 趋势跟踪研报、论文、PDF、网页或文本，转化为完整复现交付包：全文翻译
    → 策略逻辑抽取（开仓/止损/止盈）→ 回测代码 → 真实本地回测 → 中文评估报告 → 交付摘要。
  summary_en: Time-series CTA report replication skill — paper to Chinese translation,
    entry/stop/target reconstruction, backtest strategy, and Chinese evaluation report.
---

# Report Replication — 时序 CTA（Time-Series CTA）

## Purpose

把一篇**时序 CTA / 趋势跟踪**研报、论文、PDF、网页或文本，转化为完整的研究复现交付包（位于 `/home/coder/project/replication/report-replication/{report_id}`）：

1. 全文中文翻译。
2. **策略逻辑抽取**：开仓 / 止损 / 止盈 + 参数 + 假设（`strategy_summary.md` + `reference_implementation.py`）。
3. **回测策略代码**：读外部 OHLC → 计算开仓/止损/止盈 → 写 `signal_log.jsonl`。
4. **本地回测**：用内置引擎跑，产出净值/回撤/Sharpe/Calmar/换手等 + 中文回测报告。
5. **中文策略评估报告**（独立 HTML）：净值/回撤/分 regime/基准对照/RAG 打分，小白可读。
6. 中文最终交付摘要。

**与 `skill-report-replication-factor` 的差异**：本技能**无因子验证阶段**（不做 IC/分位/多空截面分析）。时序 CTA 三要素——开仓 / 止损 / 止盈——必须从研报里抽取并编码。截面因子研报请用 `-factor` 技能。

## Language And Readability Rules

- 所有用户可见产出全程中文：`full_translation.md`、`strategy_summary.md`、`evaluation_report.html`、`backtest_report.html`、`final_delivery_summary.md`、生成代码的注释/docstring。
- 英文仅用于：原文标题、专有名词、公式、代码标识符、CSV 列名、API 名、合约代码、指标缩写（Sharpe/Calmar 等短标签）。
- 不得交付英文叙事段、纯英文报告或乱码中文。工具产出英文/乱码 HTML 时，包裹/改写成中文读者可见产物，原始件另存审计。
- 交付前人工抽查主要可读文件的中文可读性，不只用自动门禁。
- 面向"聪明但不懂量化"的读者解释概念；克制、具体、证据导向。

## Chart Image Text Rules

- 生成的图表图片**图内文字仅英文 ASCII**（标题/副标题/轴/图例/色条/标注/热力图标签/水印）。
- 中文解释放在图周边的 HTML/Markdown，不进图内像素。
- 用 `DejaVu Sans`/`Arial` 等通用拉丁字体；**不要**设中文字体（SimHei/SimSun/Microsoft YaHei/Noto Sans CJK/Source Han Sans）。
- 优先用英文图标签（如 `Strategy NAV`、`Drawdown`、`Benchmark NAV Comparison`）。原文名是中文时，图内画 ASCII 安全标签，中文原名放周边文字。

## Data Source Rules（关键）

- **数据源 = 外部本地路径**：`local_backtest.py --market-data <用户提供的 CSV/Parquet>`。**本技能本身绝不下载行情数据。**
- 必须在 `manifest.json` 记录来源/路径/品种/区间/频率/复权/可用时点/缺失处理。
- 禁止用合成/mock/随机行情证明策略有效；定种随机信号仅作阴性对照基准。
- 数据不足时保留章节、中文写明卡点、结论标 `inconclusive`。详见 `references/data_sources.md`。

## Required Output Contract

每个报告一个项目目录。完整结构见 `references/output_contract.md`，要点：

```text
{report_id}/
  01_translation/full_translation.md
  02_strategy_logic/{strategy_summary.md, reference_implementation.py}
  03_strategy_evaluation/{evaluation_report.html, data/, charts/}
  04_backtest_strategy/{strategy.py, config.json, backtest_report.html, backtest_logs/}
  06_delivery/final_delivery_summary.md
  failure_report.md
  manifest.json
```

## Honesty Rules

- 实事求是：没跑的步骤就说明没跑。
- 禁止伪造 walk-forward、成本敏感、净值、图表、回测日志。
- 回测跑不动或数据不足，记录卡点并把结论标 `inconclusive`。
- HTML 报告里每个图表/指标必须可追溯到 `03_strategy_evaluation/data/`、`charts/` 或回测产物。
- 每个图表和关键指标必须用大白话解释：含义、怎么看、当前结果说明什么、来自哪个数据/产物。

## Subagent Governance

默认单主代理工作流。若用子代理：主代理对正确性与交付负全责；子代理产出仅为草稿，不得未经复核写入最终产物；子代理只写隔离 scratch 目录；主代理必须独立复核公式、数据溯源、防泄漏、CSV、图表、回测报告、结论，晋升后再跑相关门禁与 `quality_gate_check.py`。任一阶段失败建 `failure_report.md`。

## Workflow

### 1. Initialize

校验依赖并建项目：

```bash
python scripts/check_dependencies.py --install
python scripts/create_project.py --title "<报告标题>" --source "<URL 或 PDF 路径>" [--root <输出根>]
```

默认根 `/home/coder/project/replication/report-replication`（Windows 本地用 `--root` 覆盖）。在 `manifest.json` 记录：原始输入路径/URL、报告标题、运行日期、Python 环境、回测引擎入口（`scripts/local_backtest.py`）、数据源/假设/参数/代码哈希/运行历史。

### 2. Extract And Translate

输入支持 🌐 网页 URL（WebFetch / webReader）与 📄 本地 PDF（Read，含 OCR）。产出 `01_translation/full_translation.md`：

- 全文中文翻译（不是只摘英文）。
- 保留原文结构、页码、章节、表注、图注、公式解释。
- OCR/PDF 低置信区标 `待核验`。
- 不臆造缺失公式/表值/图注。

完成后跑：

```bash
python scripts/check_step2_translation.py {project_dir}
```

未过门禁则记录卡点，不进入 Step 3。

### 3. Extract Strategy Logic（开仓 / 止损 / 止盈）

产出 `02_strategy_logic/strategy_summary.md` + `02_strategy_logic/reference_implementation.py`。

`strategy_summary.md` 必须含：研究问题、结论、资产池、样本周期/频率、数据源、**开仓规则**、**止损规则**、**止盈/退出规则**、参数、假设/风控。每项标注从研报何处抽取（引用原文公式/章节）。

`reference_implementation.py` 必须含可审计的信号生成函数：读 OHLC → 计算开仓/止损/止盈 → 产出 `direction`（1/-1/0）。函数级精度，含缺失值规则与参数。

读 `references/tscta_evaluation.md` 的"三要素抽取清单"与"评估指标"再动手。

完成后跑：

```bash
python scripts/check_strategy_logic.py {project_dir}
```

未过则记录卡点，不进入回测。

### 4. Generate And Run Backtest

仅在策略三要素抽取完成后生成回测代码。读 `references/backtest_engine.md` 再动手。

`04_backtest_strategy/strategy.py` 必须：

- 读外部行情（含 OHLC）→ 计算开仓/止损/止盈 → 写 `backtest_logs/signal_log.jsonl`（`{"date":"YYYY-MM-DD","signals":{"SYM":{"factor":float,"direction":1|-1|0}}}`）。
- 参数集中可见：品种、频率、窗口、rebalance 时点、入场/出场规则、风控、手续费、滑点、保证金、资金约束。
- **止损/止盈落在此处**：触发时 `direction=0`（引擎不内置 ATR 止损）。

跑内置引擎（行情由用户外部提供）：

```bash
python scripts/local_backtest.py {project_dir} --market-data /path/to/market_data.csv
```

保留引擎原始输出为 `backtest_report_raw.html`；交付 `backtest_report.html` 为中文回测解释（策略逻辑、数据、产物、信号日志、与评估口径的关系、已知差异）。引擎另写 `equity_curve.csv`、`performance_metrics.csv`、`trades.csv`、`position_return_detail.csv`。

完成后跑：

```bash
python scripts/check_step5_strategy.py {project_dir}
```

### 5. Strategy Evaluation Report

产出 `03_strategy_evaluation/evaluation_report.html`（中文）。读 `references/tscta_evaluation.md` 与 `references/output_contract.md` 再动手。至少含：

- 净值曲线、回撤、年化收益/波动、Sharpe、Sortino、Calmar、Max DD、胜率、盈亏比、换手、逐年/逐月表现。
- IS/OOS、walk-forward（数据允许时）；分 regime 净值（研报定义市场状态时）；滚动 Sharpe；成本敏感性。
- 基准对照：买入持有 + 恒空仓/零收益（必需），条件允许加单开仓/单止损等消融对照、定种随机阴性对照。数据存 `data/benchmark_comparison.csv`。
- 顶部"阅读指南"+ 指标字典；每图 5 段中文释义；RAG 红黄绿打分卡（客观指标）；"已知局限"节（日频 bar、止损 direction 近似、gap 风险）。
- 最终结论：effective / weakly effective / ineffective / regime-dependent / inconclusive。

### 6. Final Delivery Summary

产出 `06_delivery/final_delivery_summary.md`（决策导向简报）：研报说了啥 / 三要素是否齐全 / 回测是否跑通 / 关键指标 / 产物路径 / 假设 / 风险 / 卡点 / 下一步。任一阶段失败另建 `failure_report.md`。

### 7. Run Quality Gate

```bash
python scripts/quality_gate_check.py {project_dir}
```

报错则不得交付为完成；修复重跑，或提供 `failure_report.md` 并声明项目阻塞。

## References

- `references/output_contract.md`：必需文件与验收标准。
- `references/tscta_evaluation.md`：TSCTA 评估指标 + 开仓/止损/止盈三要素抽取清单。
- `references/backtest_engine.md`：回测策略生成与执行规则。
- `references/data_sources.md`：数据源与溯源规则（外部路径、不下载）。
- `references/replication_lessons_learned.md`：历史失败案例与护栏。
