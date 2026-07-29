# Output Contract（时序 CTA 研报复现）

每个复现项目都遵守本契约。**与因子版的差异**：无因子验证阶段；以"策略逻辑（开仓/止损/止盈）+ 回测 + 策略评估"取代。

## Directory

输出根平台自适应（`REPLICATION_ROOT` 环境变量 > 云环境 `/home/coder/project/...` > 本地 `~/report-replication`），可用 `--root` 覆盖。项目目录结构：

```text
{输出根}/{report_id}/
  01_translation/full_translation.md
  02_strategy_logic/strategy_summary.md
  02_strategy_logic/reference_implementation.py
  03_strategy_evaluation/evaluation_report.html
  03_strategy_evaluation/data/
  03_strategy_evaluation/data/direction_matrix_from_strategy.csv
  03_strategy_evaluation/data/portfolio_returns_dir_full.csv
  03_strategy_evaluation/data/benchmark_comparison.csv
  03_strategy_evaluation/data/backtest_alignment_audit.csv
  03_strategy_evaluation/data/yearly_performance.csv        (if data allows)
  03_strategy_evaluation/data/rolling_metrics.csv           (if data allows)
  03_strategy_evaluation/data/turnover_series.csv           (if data allows)
  03_strategy_evaluation/data/cost_sensitivity.csv          (if executed)
  03_strategy_evaluation/charts/
  03_strategy_evaluation/charts/01_nav.png
  03_strategy_evaluation/charts/02_drawdown.png
  03_strategy_evaluation/charts/03_regime_nav.png           (if regime defined)
  03_strategy_evaluation/charts/04_benchmark_nav.png
  03_strategy_evaluation/charts/05_yearly_return.png        (if data allows)
  03_strategy_evaluation/charts/06_rolling_sharpe.png       (if data allows)
  03_strategy_evaluation/charts/07_cost_sensitivity.png     (if executed)
  03_strategy_evaluation/charts/08_walkforward.png          (if executed)
  04_backtest_strategy/strategy.py
  04_backtest_strategy/config.json
  04_backtest_strategy/backtest_report.html
  04_backtest_strategy/backtest_report_raw.html (optional raw engine report)
  04_backtest_strategy/backtest_logs/signal_log.jsonl
  04_backtest_strategy/backtest_logs/equity_curve.csv
  04_backtest_strategy/backtest_logs/performance_metrics.csv
  04_backtest_strategy/backtest_logs/trades.csv
  04_backtest_strategy/backtest_logs/position_return_detail.csv
  06_delivery/final_delivery_summary.md
  failure_report.md
  manifest.json
```

## Language Requirements

- 用户可见产出全程中文：翻译、策略逻辑、评估报告 HTML、回测解释 HTML、交付摘要、生成代码的注释/docstring。
- 英文仅用于：公式、代码/API 名、指标缩写（Sharpe/Calmar/IC 等短标签）、原文标题、专有名词、CSV 列名、合约代码。
- 若回测引擎输出英文/乱码 HTML，保留为 `backtest_report_raw.html`，另做中文 `backtest_report.html` 解释页并引用原始件。
- 面向"聪明但不懂量化"的读者写解释；避免模板腔、未解释术语、夸大确定性。

## Chart Image Text Requirements

- `03_strategy_evaluation/charts/` 下图片**图内文字仅英文 ASCII**（标题/轴/图例/标注/色条）。
- 中文解释放在图周边的 HTML/Markdown，不进图内像素。
- 用 `DejaVu Sans`/`Arial` 等通用拉丁字体；**不要**设中文字体（SimHei/Microsoft YaHei/Noto CJK 等）。

## Data Source Requirements（关键）

- **数据源 = 外部本地路径**：通过 `local_backtest.py --market-data <用户提供的 CSV/Parquet>` 提供。**技能本身绝不下载行情数据。**
- 必须在 `manifest.json` 记录：数据提供方/文件源、本地路径、品种/宇宙、样本区间、频率、复权规则、可用时点假设、缺失值处理。
- 数据必须真实可溯源。**禁止用合成/mock/随机生成的行情数据证明策略有效。**
- 定种随机信号仅可作"阴性对照"基准，在同一份真实收益数据上运行，绝不可替代真实行情。
- 数据不足时：保留对应章节、中文写明卡点、结论标 `inconclusive`、必要时建 `failure_report.md`。

## `manifest.json`

含：`report_id`、`title`、`source`、`created_at`、`python`、`backtest_engine`、`backtest_entrypoint`、`backtest_command`、`data_sources`、`assumptions`、`parameters`、`code_hashes`、`run_history`、`artifacts`、`status`；若用了子代理记 `subagent_usage`。

## Subagent / Background Agent Policy

子代理可选，非必需。若使用：只能写隔离 scratch（如 `.agent_work/`）；不得直接改最终产物；产出由主代理复核后手动晋升；晋升后重跑相关校验脚本与 `quality_gate_check.py`。

## 1. Full Translation

文件：`01_translation/full_translation.md`

- 输入支持 🌐 网页 URL（WebFetch/webReader）与 📄 本地 PDF（Read，支持 OCR）。
- 保留原文结构/章节/图表注/公式解释。
- OCR/PDF 低置信区标 `待核验`。
- 不臆造缺失的表格值或公式项。

## 2. Strategy Logic（开仓 / 止损 / 止盈）

文件：`02_strategy_logic/strategy_summary.md` + `02_strategy_logic/reference_implementation.py`

- **从模板起笔**：复制 `templates/strategy_summary_template.md` 与 `templates/reference_implementation_template.py` 后填空（模板已含三要素函数骨架与必填章节）。
- `strategy_summary.md` 含：研究问题、结论、资产池、样本周期/频率、数据源、**开仓规则**、**止损规则**、**止盈/退出规则**、参数、假设/风控（成本/滑点/保证金/杠杆）。
- `reference_implementation.py` 含可审计的信号生成函数：读 OHLC → 计算开仓/止损/止盈 → 产出 `direction`（1/-1/0）。函数级精度，含缺失值规则与参数。
- 必须明确三要素从研报何处抽取（引用原文公式/章节）。

## 3. Strategy Evaluation Report（TSCTA 口径）

文件：`03_strategy_evaluation/evaluation_report.html`

- 独立 HTML，无服务端可开。
- 中文正文，指标缩写/短英文标签仅作词典辅助。
- 图内文字仅英文 ASCII；中文解释在图下。
- 顶部 `阅读指南 / How To Read`：用大白话讲证据链——策略三要素 → 数据 → 回测净值 → 回撤 → 分 regime → 基准对照 → 结论。
- `指标字典` 至少解释：NAV、年化收益、年化波动、Sharpe、Sortino、Calmar、Max DD、胜率、盈亏比、换手、IS/OOS。
- 每图下含 5 段中文解释：`这张图回答什么问题`、`怎么看`、`我们看到了什么`、`这意味着什么`、`数据来源`。
- 明确区分：`01_nav.png` 是回测实际净值（来自 `equity_curve.csv`），不是理论曲线；若有理论/回测对账，用 `backtest_alignment_audit.csv` 说明口径差异。
- 红黄绿（RAG）打分卡：客观指标算出，至少覆盖 数据覆盖、三要素完整度、回测是否真跑、风险/收益（Sharpe/Calmar/Max DD）、成本稳健、基准对照。
- 基准对照章节：至少含 **买入持有** 与 **恒空仓/零收益**；条件允许加"单开仓无止损"、"单止损无止盈"等消融对照。数据存 `data/benchmark_comparison.csv`。
- 含：净值、回撤、逐年表现、换手、（条件允许）分 regime 净值、滚动 Sharpe、成本敏感性、walk-forward。
- 明确写出**已知局限**：日频 bar 口径、止损为 strategy.py emit direction 近似（非 intraday 原生）、gap/跳空风险等。
- 章节缺失因数据不足时，保留章节标题并中文写明卡点。

### HTML 标准章节

`evaluation_report.html` 含：0 阅读指南+RAG 打分卡；0.1 基准对照；0.2 口径/已知局限；1 报告头；2 策略逻辑（开仓/止损/止盈）；3 数据说明；4 净值；5 回撤；6 市场状态/regime；7 逐年表现与换手；8 基准对照；9 结论。

### 必需数据文件

| File | Content | Required |
| --- | --- | --- |
| `direction_matrix_from_strategy.csv` | date×symbol 方向 | yes |
| `portfolio_returns_dir_full.csv` | 策略方向全样本收益/净值 | yes |
| `benchmark_comparison.csv` | 策略与基准收益/指标 | yes |
| `backtest_alignment_audit.csv` | 口径对账（若有理论 vs 回测） | yes |
| `yearly_performance.csv` | 逐年/逐月表现 | if data allows |
| `rolling_metrics.csv` | 滚动收益/波动/Sharpe/回撤 | if data allows |
| `turnover_series.csv` | 换手序列 | if data allows |
| `cost_sensitivity.csv` | 成本敏感性 | if executed |

### 必需图表

图内文字仅英文 ASCII：

| File | Content | Required |
| --- | --- | --- |
| `01_nav.png` | 策略净值曲线 | yes |
| `02_drawdown.png` | 回撤 | yes |
| `03_regime_nav.png` | 分市场状态净值 | if regime defined |
| `04_benchmark_nav.png` | 基准对照净值 | yes |
| `05_yearly_return.png` | 逐年收益 | if data allows |
| `06_rolling_sharpe.png` | 滚动 Sharpe | if data allows |
| `07_cost_sensitivity.png` | 成本敏感性 | if executed |
| `08_walkforward.png` | Walk-forward | if executed |

## 4. BACKTEST Strategy And Backtest

文件：`04_backtest_strategy/strategy.py`、`config.json`、`backtest_report.html`、`backtest_report_raw.html`、`backtest_logs/`

- `strategy.py` 读外部 OHLC → 计算开仓/止损/止盈 → 写 `signal_log.jsonl`（一行一 JSON：`{"date":"YYYY-MM-DD","signals":{"SYM":{"factor":float,"direction":1|-1|0}}}`）。
- 参数集中在可见区。
- 用 `scripts/local_backtest.py` 跑；`backtest_report.html` 中文可读；引擎英文/乱码输出存 `backtest_report_raw.html`。
- 引擎输出含 `equity_curve.csv`、`performance_metrics.csv`、`trades.csv`、`position_return_detail.csv`。
- 失败时存失败日志。

## 5. Final Delivery Summary

文件：`06_delivery/final_delivery_summary.md`

- 决策导向简报：研报说了啥 / 三要素是否齐全 / 回测是否跑通 / 关键指标 / 产物路径 / 假设 / 风险 / 卡点 / 下一步。
- 某阶段失败则链 `failure_report.md`。

## Failure Report

文件：`failure_report.md`（任一必需阶段未完成时建）

含：失败阶段、执行的命令/动作、错误/traceback、已生成部分产物、可能原因、下一步修复。
