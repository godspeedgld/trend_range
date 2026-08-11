# Output Contract（时序 CTA 研报 AI 复现）

每个复现项目遵守本契约。**与 -factor 的差异**：去因子（无 IC/分位/多空/因子验证阶段）；新增 **02_approach 量化方法提取**（头条）；回测用**事件驱动引擎**（非 signal 驱动）。结构与用法参照 -factor 的 output_contract，按 cta-ts 调整。

## Directory

输出根平台自适应（`REPLICATION_ROOT`(.env/环境变量) > 云环境 `/home/coder/project/replication/report-replication` > 本地 `~/report-replication`），可用 `--root` 覆盖。

```text
{输出根}/{report_id}/
  01_translation/full_translation.md(+ images/)      # 非中文→中文（英文研报才需要）
  02_approach/
    main_approach.md            # 【仅】量化方法提取（分类+思路/原理/公式/推导/优缺点+衍生方法+参考资料+未来）← headline
  03_backtest_strategy/
    backtest_features.md         # 回测特征（regime/开仓/止盈止损/开平仓/风控，文字+可执行代码）
    reference_implementation.py  # 指标/信号可审计实现
    strategy.py                  # build_strategy(df)->spec，喂事件驱动引擎
    config.json                  # 成本/滑点/年化/品种等参数
    backtest_report.html         # 中文回测解释
    backtest_report_raw.html     # 引擎原始 JSON
    backtest_logs/
      equity_curve.csv           # date, net_return, nav, drawdown
      performance_metrics.csv    # 单行指标
      position_return_detail.csv # 逐根 date/symbol/ret/pos/direction
      signal_log.jsonl           # 引擎产出的【实现方向】（审计，非输入）
  04_delivery/
    final_report.md              # 综合"方法总结 + 回测结果"
  failure_report.md
  manifest.json
```

## Language Requirements

- 用户可见产出全程中文：translation、main_approach、backtest_features、backtest_report、final_report、代码注释/docstring。
- 英文仅用于：公式、代码/API 名、指标缩写（Sharpe/Calmar/ATR/IC 等短标签）、原文标题、专有名词、CSV 列名、合约代码。
- 引擎英文/数值输出存 `backtest_report_raw.html`，另做中文 `backtest_report.html` 解释页并引用原始件。
- 面向"聪明但不懂量化"的读者；避免模板腔、未解释术语、夸大确定性。

## Chart Image Text Requirements

- 图内文字仅英文 ASCII（标题/轴/图例/色条/标注）。中文解释放图周边 HTML/Markdown。
- 用 `DejaVu Sans`/`Arial` 等通用拉丁字体；**不要**设中文字体（SimHei/Microsoft YaHei/Noto CJK）。
- 原文名是中文时，图内画 ASCII 标签，中文原名放周边文字。

## Data Source Requirements（关键，详见 data_sources.md）

- **行情数据 = 外部本地路径**：`local_backtest.py --market-data <CSV/Parquet>`。**技能本身绝不下载行情**（可用配置指向本地/远程 API，技能读取）。
- **必做合法性检查**：NaN 处理、复权、正价格、时序升序、(date,symbol) 唯一、覆盖率、可用时点（防前视）。不合格则中文写明卡点、结论降级。
- 在 manifest.data_sources 记录：提供方/路径/品种/区间/频率/复权/缺失处理。
- 禁止合成/mock/随机行情证明策略有效；定种随机信号仅作阴性对照。

## `manifest.json` 字段

`report_id`、`title`、`source`、`created_at`、`python`、`backtest_engine`（事件驱动，含 numba 标记）、`backtest_entrypoint`、`backtest_command`、`data_sources`、`assumptions`、`parameters`、`code_hashes`、`run_history`、`artifacts`、`status`；用子代理则记 `subagent_usage`。

## Subagent Policy

子代理可选、非必需。若用：只写隔离 scratch（如 `.agent_work/`）；不得直接改最终产物；产出由主代理复核后晋升；晋升后重跑相关 check + `quality_gate_check.py`。

## 各步验收标准

### 1. Full Translation（仅非中文）
文件：`01_translation/full_translation.md`
- 保留原文结构/章节/表注/图注/公式解释；OCR 低置信标"待核验"；不臆造缺失表值/公式项。
- 英文研报才需要；中文研报可跳过此步。

### 2. Quant Method Extraction（头条）
文件：`02_approach/main_approach.md`（从 `templates/main_approach_template.md` 起笔）
- 按 taxonomy 分类（regime 判断 / 指标分析与比较 / 多指标融合 / 止盈止损 / 风险控制），原文未涉及的类注明"原文未涉及"。
- 每个提取方法含 5 部分：①文中思路总结（可引原文+章节）②方法原理解释分析 ③公式指标提取 ④必要推导（可选）⑤优缺点（具体，如均线延迟/Kalman 抗噪但参数敏感）。
- 文档末尾三节：**衍生方法**（提及未用 + 用/不用原因）、**参考资料**（引用文献清单）、**未来探索**（原文展望归纳）。
- 含文字、公式、（原图截图引用）；不臆造。门禁 `check_approach.py`。

### 3. Backtest Features
文件：`03_backtest_strategy/backtest_features.md` + `reference_implementation.py`（从 `templates/backtest_features_template.md` 起笔）
- backtest_features.md 从研报**实证分析**提取三特征，每项**文字描述 + 可执行代码**：入场逻辑、离场逻辑、交易规则。
- 实证未明确则从核心方法总结推导；填默认值标注。
- reference_implementation.py 含可审计函数（指标/信号/止损），函数级精度 + 缺失值规则 + 参数；与 strategy.py 口径一致。门禁 `check_strategy.py`。

### 4. Backtest（事件驱动引擎）
文件：`03_backtest_strategy/strategy.py` + `backtest_report.html` + `backtest_logs/`
- strategy.py 暴露 `build_strategy(df)->spec`（从 `templates/strategy.py` 起笔）；引擎按 spec 跑事件驱动状态机。
- 跑 `scripts/local_backtest.py {project_dir} --market-data <外部 OHLC>`，产 equity/metrics/signal_log（实现方向）+ 中文 backtest_report.html。
- 指标口径（复用 -factor compute_metrics）：final_nav、total/annual_return、annual/downside_volatility、Sharpe、Sortino、Calmar、max_drawdown、win_rate、profit_factor。**不含**因子 IC/分位/多空。
- 报告写明已知局限：日频 bar 事件驱动、gap 近似、signal_log 为产出非输入。

#### 回测必需产物（backtest_logs/）

| File | Content | Required |
| --- | --- | --- |
| `equity_curve.csv` | date/net_return/nav/drawdown | yes |
| `performance_metrics.csv` | 单行核心指标 | yes |
| `position_return_detail.csv` | 逐根 date/symbol/ret/pos/direction | yes |
| `trades.csv` | 推导的买卖点（date/symbol/action/side/price） | yes |
| `signal_log.jsonl` | 引擎产出实现方向（审计） | yes |

`backtest_report.html` 由**引擎按固定模板生成**（每次格式一致）：核心绩效（% 口径）+ 净值曲线 + 回撤 + K 线带买卖点（▲开仓/▽平仓）。`config.json` 亦由引擎自动落运行参数。LLM 不得手写覆盖该 HTML。

### 5. Final Report
文件：`04_delivery/final_report.md`（从 `templates/final_report_template.md` 起笔）
- 决策导向简报：一句话结论 / 研报观点摘要 / 回测结果 / 方法与回测一致性 / 假设风险局限 / 产物路径 / 下一步。
- 综合方法提取（02）+ 回测（03）。某阶段未完成则结论标 inconclusive 并链 failure_report.md。

## 产出物清单（质量门禁检测项）

`quality_gate_check.py` 逐项检测下列产出物存在且非空（缺失→FAIL；详见脚本 `required_files`）：

| 产出物 | 路径 | 来源步骤 |
| --- | --- | --- |
| 方法提取（头条） | `02_approach/main_approach.md` | Step 2 |
| 回测特征 | `03_backtest_strategy/backtest_features.md` | Step 3 |
| 可审计实现 | `03_backtest_strategy/reference_implementation.py` | Step 3 |
| 策略 | `03_backtest_strategy/strategy.py` | Step 4 |
| 配置 | `03_backtest_strategy/config.json` | Step 4 |
| 回测报告 | `03_backtest_strategy/backtest_report.html` | Step 4 |
| 权益曲线 | `03_backtest_strategy/backtest_logs/equity_curve.csv` | Step 4 |
| 指标 | `03_backtest_strategy/backtest_logs/performance_metrics.csv` | Step 4 |
| 实现方向 | `03_backtest_strategy/backtest_logs/signal_log.jsonl` | Step 4 |
| manifest | `manifest.json` | Step 1 |
| 交付总结 | `04_delivery/final_report.md` 或 `failure_report.md` | Step 5 |

门禁另检查：4 目录结构、manifest 必需键（report_id/title/data_sources/run_history/artifacts）、signal_log JSON 格式（date+signals）。`check_approach.py` / `check_strategy.py` / `check_translation.py` 为各步前置门禁。

## Failure Report

文件：`failure_report.md`（任一必需阶段未完成时建）
含：失败阶段、执行的命令/动作、错误/traceback、已生成部分产物、可能原因、下一步修复。
