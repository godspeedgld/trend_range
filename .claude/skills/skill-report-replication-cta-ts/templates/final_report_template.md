# 复现总结报告（final_report.md）— 模板

> 复制到 `04_delivery/final_report.md` 后填空。综合"量化方法提取 + 实证回测"，决策导向，简洁。
> 面向：想快速知道"这篇研报讲了什么、方法是否可复用、回测是否有效"的读者。

---

## 0. 报告信息
- 标题：`<原文标题>`　来源：`<URL/PDF>`　研究员：`<...>`　复现日期：`<...>`
- report_id：`<...>`

## 1. 一句话结论
`<研报核心观点 + 我们复现的判断，如"研报用 TSI/ρ 识别趋势态 + ATR 吊灯退出，方法可复现；HC 回测卡玛比 X，方向有效/regime 依赖/无效">`

## 2. 研报讲了什么（量化观点摘要）
- **核心立论**：`<如 价格=趋势μ+惯性ρ+噪声σ>`
- **关键方法**（来自 02_approach/main_approach.md）：
  - regime：`<TSI 信噪比 + ρ>`
  - 开仓：`<双均线/突破>`
  - 止盈止损：`<ATR 吊灯>`
  - 风控：`<vol-target>`
- **可复用价值**：`<哪些方法/观点值得沉淀复用>`

## 3. 实证回测结果（来自 03_backtest_strategy）
- 策略：`<双均线+ATR吊灯，满仓，HC 日频 2019-至今>`
- 关键指标：final_nav `<X>`、年化 `<X>`、Sharpe `<X>`、Calmar `<X>`、MaxDD `<X>`、胜率 `<X>`、盈亏比 `<X>`、换手 `<X>`
- 基准对照：vs 买入持有 `<...>`、vs 恒空仓 `<...>`
- 结论：`<有效 / 弱有效 / 无效 / regime 依赖 / inconclusive>`

## 4. 方法提取与回测的一致性
- 复现的策略是否忠实反映研报方法？`<是 / 有偏差（说明）>`
- 研报未明确的要素用了什么默认值？`<如 止盈止损用 ATR 吊灯默认>`

## 5. 假设、风险与已知局限
- 数据：`<外部路径、复权、缺失处理>`
- 假设：`<成本/滑点/保证金/执行口径>`
- 已知局限：`<日频 bar 事件驱动、gap 近似、样本单一>`

## 6. 产物路径
- 方法提取：`02_approach/main_approach.md`
- 回测特征/实现：`03_backtest_strategy/{backtest_features.md, reference_implementation.py, strategy.py}`
- 回测结果：`03_backtest_strategy/backtest_report.html` + `backtest_logs/`
- 翻译（若有）：`01_translation/full_translation.md`

## 7. 下一步（可选）
`<如：多品种组合、intraday 引擎、接入外生指标降低 regime 时滞>`

---

> 若某阶段未完成（如无数据未回测），把 §3 改为"回测未执行（原因）"，结论标 inconclusive，并链接 failure_report.md。
