# 回测特征提取规范（strategy_feature.md）

本文件是 **Step 4 回测特征提取**的依据，产出 `03_backtest_strategy/backtest_features.md` + `reference_implementation.py`。
**关键要求（5.2.6）**：每项特征都要有**文字描述 + 可执行指标代码**两份。

## 一、需提取的回测特征（5.2）

### 5.2.1 regime 判断（默认：无）
- 文字：是否做市场状态识别？方法（TSI/ρ、Hurst…）、状态划分、门控作用（仅趋势态开趋势仓？震荡态切反转？）。
- 代码：`regime_state(df) -> pd.Series[bool/enum]`。

### 5.2.2 开仓信号判断（默认：双均线）
- 文字：具体指标（动量/均线/Kalman…）、指标融合方法（共振/打分/ML）、触发条件、参数。
- 代码：`entry_signal(df) -> (entry_long, entry_short)` 布尔事件数组。

### 5.2.3 止盈止损判断（默认：ATR 吊灯）
- 文字：止损类型（固定%/ATR静态/ATR移动吊灯/逻辑证伪/时间退出）、止盈类型、参数（ATR 周期、倍数 k、最大持有）。
- 代码：止损规格 `{"stop": {"type":"atr_chandelier","atr_period":14,"k":2.0}}`，引擎据此用 high/low 命中价即时触发。

### 5.2.4 开仓平仓逻辑
- 文字：空仓遇信号如何处理（进场）；多仓遇反向信号如何处理（反手/忽略）；止损触发后是否同根再进。
- 代码：在 `build_strategy` 里以 entry_long/entry_short 事件 + stop 规格表达（引擎负责状态机）。

### 5.2.5 风险控制 / 仓位（默认：满仓）
- 文字：仓位法（满仓/vol-target/等手数/风险平价）、目标波动、单品种最大权重、保证金、成本/滑点。
- 代码：`{"sizing":{"type":"vol_target","target_vol":0.15,"vol_window":20}}` 或 `{"type":"full"}`。

## 二、reference_implementation.py（可审计实现）

`03_backtest_strategy/reference_implementation.py` 必须含可审计的指标/信号函数，函数级精度，含缺失值规则与参数。它和 `strategy.py` 的关系：
- `reference_implementation.py` = 方法可审计的"教材式"实现（强调可读、可追公式）。
- `strategy.py` = 引擎可跑版本，暴露 `build_strategy(df)->spec` 喂事件驱动引擎（见 backtest_engine.md）。
- 二者口径一致；strategy.py 可直接 import reference_implementation 的函数。

## 三、抽取默认值（研报未明确时填默认，并在文档标"默认值"）

| 要素 | 默认值 |
|------|--------|
| regime 判断 | 无（不门控） |
| 开仓 | 双均线交叉（5/20） |
| 止盈止损 | ATR 吊灯（k=2.0） |
| 仓位控制 | 满仓 |
| 参数优化 | 网格 + IS/OOS |

## 四、check_strategy.py 检查

门禁检查 backtest_features.md 含：regime、开仓、止盈止损、开平仓逻辑、风控/仓位 关键词；reference_implementation.py 有函数定义 + 方向/参数逻辑。
