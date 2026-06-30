# Workflow

检测驱动的时序建模流程。

1. **准备序列**：建模对象是**收益率或差分序列**，不要直接对非平稳价格建模。
   - 期货/股票日频：`returns = log(price).diff()`。
   - 价格若非平稳，先差分到平稳（见 ADF）。
2. **四项检测**：调用 `run_diagnostics(returns)` 一次拿到 ADF / Ljung-Box / ARCH-LM / 方差比(VR)。
3. **模型路由**（`recommend_model`）：
   - 无自相关 + 无 ARCH 效应 + VR 不拒绝 → `RandomWalk`（ARIMA(0,1,0) 漂移）
   - 有自相关 + 无 ARCH 效应 → `ARMA`
   - 有自相关 + 有 ARCH 效应 → `ARMA+GARCH`
   - 无自相关 + 有 ARCH 效应 → `AR+GARCH`
4. **拟合**：`fit_model(recommendation, returns, ...)`，或直接调
   `fit_random_walk` / `fit_arma` / `fit_ar_garch` / `fit_arma_garch`。
5. **随机游走流程**：在收益率空间估计常数漂移 μ（等价于价格 ARIMA(0,1,0) with drift）→
   残差 = 收益 - μ → 残差 Ljung-Box（应通过）→ 判定。
6. **ARMA 流程**（严格）：AIC/BIC 选阶 → 参数估计 → 残差 → 残差 Ljung-Box → 判定 p 值是否通过。
7. **GARCH 类流程**（严格）：AIC/BIC 选 AR/ARMA 阶 → 构建 +GARCH 并拟合 → 标准化残差 →
   均值方程 Ljung-Box（标准化残差）→ 方差方程 Ljung-Box（标准化残差平方）→ 综合判定。
8. **报告**：`generate_model_report(...)` 写出 Markdown + 检测图 + 预测图。
9. **结论先行**：先给模型类型、最优阶数、是否通过；再列参数与检测证据。
10. 全程把输出表述为研究方向判断，不作为下单依据。
