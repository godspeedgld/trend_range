# 回测特征（backtest_features.md）— 模板

> 先读完 `02_approach/main_approach.md`，再逐条映射到入场/离场/交易规则。
> 每条特征标注来源：main_approach.md 的具体小节。
> 默认值：入场=双均线 / 离场=ATR吊灯 / 交易规则=满仓。

## 0. 数据
- 品种：`<HC>`　区间：`<2019-至今>`　频率：`<日频>`
- 数据路径：`<外部 CSV>`　复权：`<前复权>`　缺失：`<dropna>`

## 1. 入场逻辑

> 来源：main_approach.md §`<1.1 regime + 1.2 指标分析>`

从研报实证提取完整入场链条，逐条列出每一步（不要合并/跳过），每步标注是否实现：

| # | 原文步骤 | 实现 | 说明 |
|---|---------|------|------|
| 1 | `<步骤描述>` | ✅/⚠️简化/❌ | `<说明>` |

- **文字**：逐条描述入场逻辑
- **代码**：`reference_implementation.entry_signal(df) -> (entry_long, entry_short)`

## 2. 离场逻辑

> 来源：main_approach.md §`<1.4 止盈止损>`

同样逐条列出原文离场层级，标注实证启用哪些、本复现实现哪些。

- **文字**：`<ATR(14) 吊灯移动止损，k=2.0>`
- **代码**：`reference_implementation.stop_spec() -> spec`

## 3. 交易规则

> 来源：main_approach.md §`<1.5 风险控制>`

- **文字**：`<满仓 / vol-target 15% / 成本 2bps + 滑点 1bps>`
- **代码**：spec.sizing + 引擎 CLI 参数

## 4. 与原文的偏差

逐条列出所有差异（含 Step 3 提到但 Step 4 未实现的），标注原因：可跑性/v1简化/数据不足/无法复现。
