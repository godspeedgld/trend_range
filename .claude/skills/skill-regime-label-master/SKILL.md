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
- **简单指标用默认窗口**；HMM/机器学习用**递增+上限窗口训练**（`split_rolling.py`：初始 3 年递增至最大 3 年后滑动。如 2015 起：15-17训→测18，16-18训→测19，17-19训→测20，18-20训→测21，…）——始终用最近 3 年训练，时效性优先
- **停止条件**：区分度 > 85% **或** 迭代次数 > 3（不含初始算法，共 4 次分析）

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
- **思路分类总结表**（思路库结尾，供迭代导航）：agent 按方法方向归纳一张表，格式：

  | 方向 | 优点 | 缺点 | 实证经验 | 可能改进思路 |
  |------|------|------|---------|------------|
  | HMM | 无监督参数适应、捕捉非线性趋势、状态自定义 | 碎片严重 | 单资产单变量碎片严重 | 多资产组合/多变量 |
  | 机器学习 | 捕捉非线性、自下而上 | 标注主观性 | 状态含义靠均值排序 | 多特征组合 |

### 2. 迭代（核心闭环）
**初始算法**（iter_001 起点）：
- **用户指定优先**：若用户指定初始算法（如某篇研报的思路），以该指定思路作为 iter_001，其划分结果为迭代起点
- **未指定时从思想库选取**（不得独立创造）：按思路分类总结表选定一个方向，依据其"实证经验+可能改进思路"列设计。若 reference_idea.md 描述不清楚，回到 REPLICATION_ROOT 下对应研报/论文复现目录查原文细节

**迭代改进**（iter_002 起，每次迭代建 `02_iteration/iter_XXX/`）：
1. **比较分析**：上轮算法输出 vs 标注，对差异时间段错误归因
2. **改进方案**：根据分析结果 + 思想库的优缺点/实证经验**综合分析**改进。有如下角度可以参考，每个角度不代表是每次迭代的出发点：
   - **2.1 原理角度**：从模型/特征的原理角度分析改进——分析现有特征特性、模型原理，添加/减少/修改特征，或更换更合适的模型。例：决策树更适合相关性高且单调性好的特征，可依据单调性/相关性去掉低相关特征、保留或构造高相关单调特征。**顺序：模型与特征之间，先改进特征，特征迭代结束后再考虑模型修改**（如先做单调性/相关性分析筛选/构造特征，特征到瓶颈后再换模型）
   - **2.2 统计角度**：分析召回率、准确率、泛化误差等机器学习指标，判断模型是否合适、如何改进。例：分析偏差/误差观察是否需要集成学习
   - **2.3 启发角度**：借鉴其他思路改进。例：当前决策树+特征，思想库中 HMM 等思路有可借鉴的点可放进迭代
3. **不轻易放弃方向**（与改进方案平行的独立规则）：选定方向（如决策树+多特征）后，后续迭代都基于该方向改进——添加思路或削减冗余，而非推倒重来
4. 写 `main_idea.md` 归因表格：

   | 差异时间段 | 错误 | 算法输出归因 | 导致算法错误逻辑原因 | 改进思路 |
   |-----------|------|-------------|---------------------|---------|
   | 20年5月-12月 | 趋势判断成震荡 | abs(ma5-ma20)变化太大 | 高波动行情单特征无效 | 多特征+机器学习 |

5. 实现算法改动（迭代算法脚本放 `iter_XXX/regime_backtest/`）→ 跑核心数据
6. 输出 `regime_change.md`（算法改动）+ `regime_segments.md`（划分+关键算法结果列）+ `regime_view.html`
7. 评估：
```bash
python scripts/evaluate_regime.py {project_dir} --algo <算法输出csv> --iter iter_001 [--warmup 250]
```
区分度 = 与标注相同天数 / 总天数（去掉开头参数暖机期）
8. **停止条件**：区分度 > 85% 或迭代 > 3 次。**迭代 3 次不含初始算法**（iter_001 为初始，iter_002~004 为 3 次迭代，共 4 次分析）

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
