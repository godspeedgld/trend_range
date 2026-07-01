# Workflow

两阶段检测驱动的时序建模流程。

1. **准备序列**：建模对象是**收益率或差分序列**，不要直接对非平稳价格建模。
   - 期货/股票日频：`returns = log(price).diff()`。
   - 价格若非平稳，先差分到平稳。
2. **ADF 前提**：`run_diagnostics` 先跑 ADF；非平稳直接抛 `NonStationaryError`（应传入收益率）。
3. **均值方程检测**：Ljung-Box（短期自相关）+ GPH（长记忆 d）+ ACF/PACF（辅助）：
   - 无自相关（Ljung-Box）→ `Constant`
   - 否则长记忆（GPH `|d|>0.1` 且 p<0.05）→ `ARFIMA`
   - 否则 → `ARMA`
4. **方差方程检测**：ARCH-LM（波动聚集）+ Engle-Ng 符号偏差（杠杆）：
   - 无 ARCH → `Constant`
   - 有 ARCH 且有杠杆（Engle-Ng 任一 p<0.05）→ `GJR-GARCH`
   - 有 ARCH 无杠杆 → `GARCH`
5. **流程归类**（`classify_model(mean_eq, var_eq)`，9 种组合全覆盖）：
   - Constant + Constant → `flow_d`（拟合常数模型 μ、σ²，基线）
   - 均值方程 + Constant → `flow_a`（ARMA / ARFIMA）
   - Constant + 方差方程 → `flow_b`（GARCH / GJR-GARCH）
   - 均值方程 + 方差方程 → `flow_c`（迭代两步联合）
6. **拟合**：`fit_model(diag, series, ...)`，或直接调 `flow_d` / `flow_a` / `flow_b` / `flow_c`。
7. **flow_d 流程**：拟合常数均值 μ + 方差 σ²（等价价格随机游走带漂移）→ 残差 = r − μ →
   残差 Ljung-Box → 判定（残差无自相关即通过；μ 即趋势 drift）。
8. **flow_a 流程**（严格）：AIC/BIC 选均值阶 → 估计（ARMA；ARFIMA 先分数差分再 ARMA）→
   残差（创新）→ 残差 Ljung-Box → 判定。
9. **flow_b 流程**：常数均值取残差 → 残差上选 GARCH/GJR 阶并拟合 → 标准化残差 →
   均值方程 LB（标准化残差）+ 方差方程 LB（标准化残差平方）→ 综合判定。
10. **flow_c 流程**（迭代两步法）：
   ① 先定均值方程 (p,q)（假设常方差）→ 计算初始残差；
   ② 初始残差上定方差方程 (P,Q)；
   ③ 固定 (P,Q)，按 `mean_AIC+var_AIC` 重选均值 (p,q)（迭代至稳定）；
   ④ 用最佳 (p,q)+(P,Q) 最终拟合（均值取残差 → 残差上 GARCH/GJR）；
   ⑤ 标准化残差双 LB。
11. **报告**：`generate_model_report(...)` 写出 Markdown + 检测图 + 预测图。
12. **结论先行**：先给流程、均值/方差方程、模型类型、最优阶数、是否通过；再列参数与检测证据。
13. 全程把输出表述为研究方向判断，不作为下单依据。
