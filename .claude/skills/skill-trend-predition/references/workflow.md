# Workflow

本 skill 没有"顶层 dispatcher"。**流程选择与"用哪条"由调用方（agent/LLM）根据用户输入决定**。
下面是 4 条流程的组合方式与默认标签定义。

## 通用约定：标签（ground truth）
默认用 `indicator.trend_label(close, high, low, horizon=10, k=1.5)`：
- 未来 N 天收益 `fwd = close.shift(-horizon)/close - 1`；
- 阈值 `thr = k * ATR / close`（**相对 ATR，与 fwd 同量纲**）；
- `|fwd| > thr` → 按符号分 **上行(+1) / 下行(−1)**，否则 **震荡(0)**。
- 末尾 horizon 个点 NaN 丢弃。
- 用户给自定义标签 → 任意 `label_fn(df)->Series`。

## 流程 1：指标法（`predict_by_indicator`）
1. 用户给自然语言规则（如"ADX(14)>25 持续 3 天 且 Hurst>0.5 为趋势"）。
2. **你把规则翻译成代码**：用 `indicator` 库算所需指标 → 写 `rule(indicators_dict)->Series`。
3. 选/写 `label_fn`（默认 `trend_label`）。
4. 调 `predict_by_indicator(df, indicators=, rule=, label_fn=, output_dir=...)`。
5. 模板：对齐 `rule` 预测与 `label_fn` 真值 → accuracy/precision/recall/F1 + 混淆矩阵 + 着色图 + 报告。

## 流程 2：决策树法（`predict_by_tree`）
1. 用户给特征集 + 目标（分类或回归）。
2. **你构造 `features` DataFrame**（用 `indicator` 库；**必须滞后、无未来函数**）。
3. 选/写 `label_fn`（分类 0/1 或多类；回归则连续）。
4. 调 `predict_by_tree(df, features=, label_fn=, task="classification"|"regression", output_dir=...)`。
5. 模板固化流程：
   - ① **量纲统一**：每折 `StandardScaler` fit 于训练段（无泄漏）。
   - ② **相关性剔除**：在初始训练段上 `|corr|>0.9` 剔除冗余（保留靠前/重要者），剔除理由入报告。
   - ③ **滚动训练**（expanding window，`min_train/step/test_block` 可配）：每折 train→predict 下一块→滑动；聚合 OOS 预测。
   - ④ 评估：分类 accuracy/precision/recall/F1 + 混淆；回归 RMSE/MAE/R²。RF + XGBoost 对比。
6. 自动出报告 + 相关性热图 + 特征重要性 + OOS 着色图。

## 流程 3：马尔可夫（占位）`plan_markov()`
返回计划说明（HMM：观测=收益+ATR 标准化，3 状态 Viterbi 解码映射趋势/震荡）。待 `hmmlearn`。

## 流程 4：深度学习（占位）`plan_dl()`
返回计划说明（LSTM/Transformer：特征序列按 lookback 切窗，监督学习 label_fn）。待 `torch`。

## 无法判断走哪条 → `describe_data(df, hint=...)`
出数据描述报告（列/样本量/close 与收益统计/ADF/方法建议）。

## 组合模式要点
- **路由在 agent 层**：你读用户请求 → 选模板 → 翻译成代码 → 调用。
- **指标/特征/标签/模型不写死在模板里**；模板只提供骨架与子工具。
- **防泄漏**：特征只用 t 时刻已知量；标签是前瞻的，仅作 y；标准化按折 fit；相关性用初始训练段。
- **结论先行**，所有过程（指标值、筛选理由、每折指标）入报告。
