# 回测特征（backtest_features.md）— 模板

> 复制到 `03_backtest_strategy/backtest_features.md` 后填空。每项需**文字描述 + 可执行代码**。
> 默认值（研报未明确时）：regime=无 / 开仓=双均线 / 止盈止损=ATR吊灯 / 仓位=满仓 / 优化=网格。
> `check_strategy.py` 检查：regime/开仓/止盈止损/开平仓逻辑/风控 + 文字+代码。

## 0. 数据
- 品种：`<HC>`　区间：`<2019-至今>`　频率：`<日频>`
- 数据路径：`<外部 CSV>`　复权：`<前复权>`　缺失：`<dropna>`

## 1. regime 判断（默认：无）
- **文字**：`<不做 / TSI+ρ 门控：仅趋势态开趋势仓>`
- **代码**：见 reference_implementation.py 的 `regime_state(df)`

## 2. 开仓信号（默认：双均线）
- **文字**：`<快线(5)上穿慢线(20)做多；下穿做空>`
- **代码**：`entry_signal(df) -> (entry_long, entry_short)`

## 3. 止盈止损（默认：ATR 吊灯）
- **文字**：`<ATR(14) 吊灯移动止损，k=2.0；TR 不截尾>`
- **代码**：spec.stop = {"type":"atr_chandelier","atr_period":14,"k":2.0}

## 4. 开仓平仓逻辑
- **文字**：`<空仓遇入场事件→进场；持仓中止损触发→平仓；不反手（趋势单），等新事件>`
- **代码**：由引擎状态机处理（entry 事件 + stop 规格）

## 5. 风控 / 仓位（默认：满仓）
- **文字**：`<满仓 / vol-target 15%>`
- **代码**：spec.sizing = {"type":"full"} 或 {"type":"vol_target","target_vol":0.15}

## 6. 参数与成本
- 手续费 `<2bps>`、滑点 `<1bps>`、保证金 `<...>`、年化 `<252>`
