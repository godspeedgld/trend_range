# Regime Identifier — 市场状态划分方法提取与验证

## Purpose

从研报/论文中提取**市场状态划分方法**，产出两类价值：
1. **方法提取（头条）**：把研报的市场状态划分方法分类提取，沉淀为可复用参考（`02_approach/main_approach.md`）。
2. **回测验证**：严格按研报的模型/指标/参数，在给定数据源（默认研报中的数据）上分析市场状态并输出结果。

**核心原则：市场状态的划分严格按研报/论文来。** 不同研报可能有不同的状态划分（震荡/趋势、牛市/熊市、高波/低波…），**不预设**固定的状态集合。

**与 skill-report-replication-cta-ts 的差异**：本技能只关注市场状态划分，不做策略回测（无 Sharpe/Calmar/NAV），输出是 regime 划分结果而非策略盈亏。

输出根平台自适应（`REPLICATION_ROOT`(.env) > 云环境 > `~/regime-replication`），可用 `--root` 覆盖。

## 数据与外部输入

1. **研报/论文输入**（Step 2）：🌐 网页 URL / 📄 本地 PDF / 📝 文本。中文研报可跳过翻译。
2. **行情数据输入**（Step 4）：`--market-data <CSV/Parquet OHLCV>`。**默认使用研报中的数据**（品种/区间/频率按研报实证），用户提供外部路径覆盖。引擎需 `date,symbol,open,high,low,close`。
3. **输出位置**：复现产物写到输出根。

## Language / Honesty Rules

- 用户可见产出全程中文；英文仅用于公式/代码/指标缩写。
- 图内文字仅英文 ASCII。
- 实事求是：没跑的步骤说明没跑；禁止伪造。

## Workflow（6 步）

### 1. Initialize
```bash
python scripts/create_project.py --title "<标题>" --source "<URL/PDF>" [--root <根>]
```
4 目录 + manifest。

### 2. Translate（仅非中文）
网页 URL / 本地 PDF / 文本 → `01_translation/full_translation.md`。门禁 `check_translation.py`。

### 3. Extract Core Methods（头条）
按 taxonomy 分类提取 → `02_approach/main_approach.md`。**taxonomy 仅一类：regime 判断**（市场状态识别）。不含止盈止损/风险控制/指标比较/多指标融合。

每方法 5 部分（思路/原理/公式/推导/优缺点）+ 衍生方法 + 参考资料 + 未来。读 `references/approach.md`。门禁 `check_approach.py`。

### 4. Regime Verification（回测验证）
**严格按照研报/论文的方法**，提取模型/指标和参数 → 根据给定数据源分析市场状态 → 输出结果。

**4a. 提取方法与参数**：
- 有确切的划分方法 → 严格按方法提取
- 有指标公式/模型 → 严格按指标/模型及**参数**提取
- 有多种方法 → **每种都提取**
- 状态定义**严格按原文**（如研报只分趋势/震荡两类，就两类；如分四类，就四类）

产出 `03_regime_analysis/regime_methods.md` + `regime_impl.py` + `data_params.json`。读 `references/regime_extraction.md`。门禁 `check_regime_methods.py`。

**4b. 运行与输出**：
```bash
python scripts/generate_regime_view.py {project_dir} --market-data <OHLC CSV/Parquet>
```
`regime_impl.py` 暴露 `classify_regime(df) -> {'methods': {...}, 'params': {...}, 'state_labels': {...}}`。

**输出三件套**：
1. **表格化时间段划分** `regime_segments.md` — 每种方法各时间段的起始/结束/状态/天数
2. **统计分析** `regime_stats.json` — 各状态天数/占比
3. **可视化** `regime_view.html` — close 曲线 + 不同市场状态不同背景色（如趋势上升浅红、趋势下降浅绿、震荡浅蓝；其他状态用预留色板）

### 5. Final Report
`04_delivery/final_report.md`：方法总结 + 回测验证结果的总结。

### 6. Quality Gate
```bash
python scripts/quality_gate_check.py {project_dir}
```

## Manual Skip

可手动跳过任一步。在 manifest 记录跳过原因；门禁报错时用 `failure_report.md` 说明。

## References

- `references/approach.md`：方法提取 taxonomy（仅 regime 判断）+ 每方法 5 部分。
- `references/regime_extraction.md`：regime 方法提取 + 验证规范。
- `references/data_sources.md`：外部数据 + 合法性检查。
- `references/output_contract.md`：4 目录 + 验收。
- `references/replication_lessons_learned.md`：历史经验。
