# Regime Label Master — 监督学习式 regime 算法迭代优化

## Purpose

以**监督学习**方式从投研复现库（思路库）中迭代优化出合适的 regime 划分算法：

1. **标注基准**：人工标注（如有）或 Zig-Zag+Binseg 算法生成趋势/震荡标注
2. **迭代闭环**（核心）：算法输出 vs 标注 → 差异归因 → 结合思路库改进 → 重跑 → 区分度评估
3. **交叉验证**：最终算法在黄金 ETF / 国债 ETF 上检验泛化
4. **最终报告**：迭代历程 + 交叉验证 + 优缺点总结

**与 skill-regime-Identifier 的差异**：Identifier 是"单次提取研报方法"，本技能是"多轮迭代优化自己的算法"，标注即监督信号。

## 数据输入（本技能不下载任何数据）

默认使用本地 warehouse `data_cache/bigquant_warehouse`（DuckDB `fund_bar1d` 表）：

| 品种 | 代码 | 角色 | 起点 |
|------|------|------|------|
| 沪深300 ETF | 510300.SH | **核心数据**（迭代优化用） | 2012-05-28 |
| 黄金 ETF | 518880.SH | 验证数据（长周期趋势属性） | 2013-07-29 |
| 国债 ETF | 511010.SH | 验证数据（高自相关低波动） | 2013-03-25 |

用 `scripts/load_market.py` 读取。后续迭代也以这三个数据为主。

## 铁律

- **无未来数据**：t 日只能用 t 日之前的数据；输出 regime 状态只能是 t 日当天的状态
- **迭代改进禁止纯参数调优**：必须基于错误归因的逻辑推理与理论分析
- **简单指标用默认窗口**；HMM/机器学习用滚动训练（`split_rolling.py`：2年训练 + 半年验证 + 半年测试）
- **停止条件**：区分度 > 85% **或** 迭代次数 > 3

## Workflow（5 步）

### 1. 初始化
```bash
python scripts/create_project.py --title "<标题>" --report-id <id> [--root <根>]
python scripts/zigzag_label.py {project_dir} --market-data <510300.csv> [--manual-label <人工标注md>]
python scripts/build_idea_library.py {project_dir} [--replication-root <REPLICATION_ROOT>]
```
- 建工程目录（01_initial / 02_iteration / 03_cross_validation / 04_delivery + manifest.json）
- 标注：有 `--manual-label` 转换人工标注；无则 Zig-Zag(转折10%/年化20%/63天)+Binseg 算法标注 → `01_initial/regime_label.md` + `regime_label_view.html`
- 思路库：扫 REPLICATION_ROOT 文档全齐的复现目录，按 4 方面（核心思路/解决问题/理论优缺点/实证结果）提取 → `01_initial/reference_idea.md`

### 2. 迭代（核心闭环）
每次迭代建 `02_iteration/iter_XXX/`：
1. **比较分析**（iter_001 除外）：上轮算法输出 vs 标注，对差异时间段错误归因
2. **改进方案**：结合思路库（reference_idea.md）推出改动方案
3. 写 `main_idea.md` 归因表格：

   | 差异时间段 | 错误 | 算法输出归因 | 导致算法错误逻辑原因 | 改进思路 |
   |-----------|------|-------------|---------------------|---------|
   | 20年5月-12月 | 趋势判断成震荡 | abs(ma5-ma20)变化太大 | 高波动行情单特征无效 | 多特征+机器学习 |

4. 实现算法改动（迭代算法脚本放 `iter_XXX/regime_backtest/`）→ 跑核心数据
5. 输出 `regime_change.md`（算法改动）+ `regime_segments.md`（划分+关键算法结果列）+ `regime_view.html`
6. 评估：
```bash
python scripts/evaluate_regime.py {project_dir} --algo <算法输出csv> --iter iter_001 [--warmup 250]
```
区分度 = 与标注相同天数 / 总天数（去掉开头参数暖机期）
7. 区分度 > 85% 或迭代 > 3 次 → 停止

### 3. 交叉验证
最终算法跑黄金 + 国债 ETF → `03_cross_validation/`（segments + view）
**性能衰减率** = (沪深300区分度 − 验证品种区分度) / 沪深300区分度 × 100%

### 4. 最终报告
`04_delivery/final_report.md`：每次迭代改动与结果、交叉验证结论、最终算法优点与局限、产物清单

### 5. 质量控制
```bash
python scripts/quality_gate_check.py {project_dir}
```

## References

- `references/workflow.md`：迭代规范详解（归因/停止条件/滚动划分）
- `references/labeling.md`：Zig-Zag+Binseg 标注规范
- `references/idea_library.md`：思路库提取规范

## Templates

- `templates/main_idea_template.md`：迭代归因表格模板
- `templates/regime_segments_template.md`：划分结果（含关键算法结果列）
- `templates/regime_change_template.md` / `regime_label_template.md` / `final_report_template.md`
