# 回测特征提取规范（strategy_feature.md）

本文件是 **Step 4 回测特征提取**的依据，产出 `03_backtest_strategy/backtest_features.md` + `reference_implementation.py`。

## 提取原则（优先级从高到低）

1. **优先从原文实证分析提取**：如果研报的"实证分析"章节给出了确切明白的入场逻辑、离场逻辑、交易规则，直接取。这是最权威的来源——实证里写的就是报告实际跑的策略。
2. **实现不明时查方法提取**：实证有确切规则但实现细节不明确（如参数值、计算口径），查看 `02_approach/main_approach.md`（Step 3 产出）对应小节获取详细公式和推导。
3. **仍不明时查原文**：`main_approach.md` 也无法解决时，回到研报原文对应章节确认。
4. **实证不明确时从 main_approach.md 推导**：如果实证章节完全没有给出三个逻辑，则从 `main_approach.md` 的核心方法中取最贴近实证描述的版本。
5. **提取前必须先读 main_approach.md**：理解 Step 3 已提取的完整方法链条，避免重复扫原文。
6. **逐条标注来源和偏差**：每条特征追溯到原文章节（实证 §X 或 main_approach §Y）。每个与原文的差异在 backtest_features.md §4 逐条列出并说明原因（可跑性/v1简化/数据不足）。

## 三特征模型

只提取三个特征，每项**文字描述 + 可执行代码**：

### 1. 入场逻辑

研报实证中**什么条件下开仓**，把 regime 门控、信号触发、方向判断统一描述为一个完整入场规则。

- 范例："收盘上穿自适应均线 AND regime=趋势上行 → 做多；下穿 AND 趋势下行 → 做空"
- 若研报用 regime 门控，则入场逻辑统一描述"regime 条件 + 信号条件"的 AND 组合
- 代码：`entry_signal(df) -> (entry_long, entry_short)` 布尔事件数组

### 2. 离场逻辑

研报实证中**什么条件下平仓**，覆盖止损、止盈、时间退出、信号反转等所有离场路径。

- 范例："ATR(14) 吊灯移动止损 k=2.0，持仓中 high/low 命中即平仓；无主动止盈；不反手"
- 若有多层退出（技术止损 + 逻辑证伪 + 时间退出），逐一列出，并标注实证中实际启用了哪几层
- 代码：止损规格 `{"type":"atr_chandelier","atr_period":14,"k":2.0}`，引擎据此状态机触发

### 3. 交易规则

研报实证中的**仓位、风控、成本、品种、频率等约束**。

- 范例："满仓（信号 ±1 即满仓多/空）" / "vol-target 15%，vol_window=20"
- 包含：仓位法、手续费、滑点、保证金、年化天数、是否允许做空、单品种最大权重
- 代码：`sizing` spec + 引擎 CLI 参数

## 数据与参数

额外记录：
- 品种、区间、频率、数据来源
- 所有策略参数（窗口、阈值、乘数）

## 默认值（研报未明确时）

| 要素 | 默认值 |
|------|--------|
| 入场 | 双均线交叉（5/20） |
| 离场 | ATR 吊灯（k=2.0, period=14） |
| 交易规则 | 满仓，成本 2bps + 滑点 1bps，年化 252 |

## reference_implementation.py

`03_backtest_strategy/reference_implementation.py` 必须以"教材式"可审计风格实现入场/离场/交易规则的相关函数：
- `entry_signal(df) -> (entry_long, entry_short)` — 入场
- `stop_spec() -> dict` — 离场（止损规格）
- 参数集中放在 `PARAMS` 字典

`strategy.py` 直接 import 这些函数，暴露 `build_strategy(df)->spec` 喂引擎。

## check_strategy.py 检查

门禁检查 backtest_features.md 含：**入场逻辑/离场逻辑/交易规则** 三节关键词，且每节有文字+代码引用。reference_implementation.py 有函数定义。
