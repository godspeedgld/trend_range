---
name: report-replication-cta-ts
description: 'AI 复现 CTA 研报/论文：把一篇时序 CTA / 趋势研报或论文转化为完整复现包。
  核心价值两部分——(1) 量化方法提取（按 regime/指标分析/多指标融合/止盈止损/风控 分类，每方法
  含思路/原理/公式/推导/优缺点 + 衍生方法 + 参考资料 + 未来），沉淀为可复用参考；(2) 实证回测
  验证（事件驱动引擎：开仓+止盈止损+策略逻辑即时触发，ATR 吊灯止损用 high/low 命中价成交）。
  产出中文方法报告 + 可跑策略 + 本地回测 + 中文回测报告 + 综合总结。输入支持网页 URL / 本地 PDF
  / 文本；数据由外部本地路径提供（技能不下载）。用于：CTA 研报复现、量化方法提取、策略实证验证、
  回测代码生成。不含截面因子验证（用 skill-report-replication-factor）。'
license: GPL-3.0-only
metadata:
  project_type: skill
  category: replication
  tags: [report-replication, time-series-cta, method-extraction, event-driven-backtest, chinese]
  status: stable
  summary_zh: AI 复现 CTA 研报——量化方法提取（头条）+ 事件驱动实证回测验证，输出中文方法报告/策略/回测/总结。
---

# Report Replication — 时序 CTA（AI 复现：方法提取 + 实证回测）

## Purpose

用 AI 复现一篇 CTA 研报/论文，产出两类价值：
1. **量化方法提取（headline）**：把研报的量化观点/思路/方法分类提取，沉淀为可复用参考（`02_approach/main_approach.md`）。**比回测更重要**——可迁移、可组合。
2. **实证回测验证**：把研报实证策略做成事件驱动回测（`03_backtest_strategy/`），验证有效性。

输出根平台自适应（`REPLICATION_ROOT`(.env) > 云环境 `/home/coder/project` > `~/report-replication`），可用 `--root` 覆盖。

**与 -factor 的差异**：去因子（无 IC/分位/多空/因子验证）；新增方法提取；回测用**事件驱动引擎**（非 signal 驱动）。

## 数据与外部输入（如何取数）

本技能**只消费外部输入，本身不下载任何数据**。两类输入：

1. **研报/论文输入**（Step 2 翻译用）：🌐 网页 URL（WebFetch/webReader 抓取）/ 📄 本地 PDF（Read，含 OCR）/ 📝 文本。中文研报可跳过翻译。
2. **行情数据输入**（Step 4 回测用）：用户以**外部本地路径**提供 `local_backtest.py --market-data <CSV/Parquet OHLCV>`。可用配置文件指向本地文件或远程数据 API，技能读取。引擎需 `date,symbol,open,high,low,close`（+volume 可选）——止损/止盈判断用 high/low。
   - **必做合法性检查**（`references/data_sources.md`）：NaN、复权、正价格、时序升序、(date,symbol) 唯一、覆盖率、可用时点（防前视）。不合格→中文写明卡点、结论降级 `inconclusive`。
   - 全部来源记入 `manifest.json` 的 `data_sources`（提供方/路径/品种/区间/频率/复权/缺失处理）。
3. **输出位置**：复现产物写到输出根（`REPLICATION_ROOT`(.env) > 云环境 > `~/report-replication`，可 `--root` 覆盖）。

## Language / Chart / Honesty Rules

- 用户可见产出全程中文；英文仅用于公式/代码/指标缩写（Sharpe/Calmar/ATR）/原文标题/合约代码/CSV 列名。
- 图内文字仅英文 ASCII（用 DejaVu Sans/Arial，不设中文字体）；中文解释放图周边。
- 实事求是：没跑的步骤说明没跑；禁止伪造净值/回撤/指标；数据不足标 `inconclusive`。每个图表/指标可追溯到 data/charts/回测产物。

## Workflow（7 步）

### 1. Initialize
```bash
python scripts/check_dependencies.py --install
python scripts/create_project.py --title "<标题>" --source "<URL/PDF>" [--root <根>]
```
4 目录 + manifest（记数据源/引擎/参数/哈希/运行历史）。

### 2. Translate（仅非中文）
网页 URL（WebFetch/webReader）/ 本地 PDF（Read, OCR）/ 文本 → `01_translation/full_translation.md`，保留图片、结构、公式；OCR 低置信标"待核验"。门禁 `check_translation.py`。

### 3. Extract Quant Methods（头条）
按 taxonomy 分类提取 → `02_approach/main_approach.md`。从 `templates/main_approach_template.md` 起笔。每方法 5 部分（思路/原理/公式/推导/优缺点）+ 衍生方法 + 参考资料 + 未来。读 `references/approach.md`。门禁 `check_approach.py`。

**taxonomy**：regime 判断 / 指标分析与比较 / 多指标融合 / 止盈止损 / 风险控制。

### 4. Extract Backtest Features
提取实证策略特征 → `03_backtest_strategy/backtest_features.md` + `reference_implementation.py`。从 `templates/backtest_features_template.md` 起笔。每项"文字+可执行代码"。读 `references/strategy_feature.md`。门禁 `check_strategy.py`。

**抽取默认值**（研报未明确时填默认并标注）：regime=无 / 开仓=双均线 / 止盈止损=ATR 吊灯 / 仓位=满仓 / 优化=网格。

### 5. Backtest（事件驱动引擎）
`03_backtest_strategy/strategy.py` 暴露 `build_strategy(df)->spec`（从 `templates/strategy.py` 起笔）。跑：
```bash
python scripts/local_backtest.py {project_dir} --market-data <外部 OHLC CSV/Parquet>
```
引擎逐根事件驱动（入场事件即时进场、ATR 吊灯止损用 high/low 命中价即时触发、收益 close-to-close、含成本、numba 加速）。产 equity/metrics/signal_log（实现方向，审计）+ 中文 `backtest_report.html`。读 `references/backtest_engine.md`。

**数据合法性检查**（必做，`references/data_sources.md`）：NaN/复权/正价格/时序/覆盖。

### 6. Final Report
`04_delivery/final_report.md` 综合"方法总结 + 回测结果"，决策导向。从 `templates/final_report_template.md` 起笔。某阶段未完成则结论标 inconclusive 并链 `failure_report.md`。

### 7. Quality Gate
```bash
python scripts/quality_gate_check.py {project_dir}
```
未过则修复重跑，或 `failure_report.md` 声明阻塞。

## Manual Skip（可跳过步骤）

工作流是给 agent 的指导，非代码锁。可手动跳过任一步（如报告已中文→跳过 Step 2；无数据→跳过 Step 5 降级 inconclusive）。在 manifest 记录跳过原因；门禁对跳过步骤报错时用 `failure_report.md` 说明。

## References

- `references/approach.md`：方法提取 taxonomy + 每方法 5 部分规范。
- `references/strategy_feature.md`：回测特征提取规范（文字+代码）。
- `references/backtest_engine.md`：事件驱动引擎接口与执行语义。
- `references/output_contract.md`：4 目录 + 验收。
- `references/data_sources.md`：外部数据 + 合法性检查。
- `references/replication_lessons_learned.md`：历史经验。
