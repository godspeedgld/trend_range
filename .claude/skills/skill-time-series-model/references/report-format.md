# Report Format

`generate_model_report(...)` 产出如下结构（中文，结论先行）：

```markdown
# <title>

## 一句话结论

<模型类型、最优阶数、是否通过 + 原因>

## 1. 检测结果

- **建议模型**：`<recommendation>` — <reason>

### 1.1 ADF 平稳性

<statistic / pvalue / used_lag / is_stationary 表>

### 1.2 Ljung-Box 自相关

<滞后阶 / 统计量 / p 值 表>
> 存在自相关：`<bool>`

### 1.3 ARCH-LM 异方差效应

<滞后阶 / 统计量 / p 值 表>
> 存在 ARCH 效应：`<bool>`

### 1.4 方差比检验（随机游走，Lo-MacKinlay）

<持有期 q / VR(q) / z 统计量 / p 值 表>
> 未拒绝随机游走：`<bool>`

![检测图](<stem>_diagnostics.png)

## 2. 建模

### 2.1 模型与最优阶数
- 模型类型（含 `RandomWalk`）/ 最优阶数（AIC/BIC 选取，随机游走为 `(0,1,0)`）/ 样本量 / AIC / BIC

### 2.2 参数估计
<参数名 / 参数值 表>

### 2.3 建模后 Ljung-Box 检测
- RandomWalk / ARMA：残差 Ljung-Box 表
- GARCH 类：均值方程（标准化残差）+ 方差方程（标准化残差平方）两张表

### 2.4 结论
- 综合判定：通过 / 未通过
- 说明：<reason>

![预测图](<stem>_prediction.png)

## 3. 注意事项
- 作用在收益率/差分序列，不直接对价格建模。
- 检测对窗口/频率敏感，需复核。
- 仅用于研究方向判断，非下单依据。
```

当四项检测均不显著（无自相关、无 ARCH、方差比不拒绝）时，走随机游走分支
（`RandomWalk` / ARIMA(0,1,0) 漂移），仍会建模并出预测图。

检测图包含三联：收益率序列、ACF、收益率平方（直观展示波动聚集）。
预测图：实际序列 + 样本内拟合 + 向前预测同图。
