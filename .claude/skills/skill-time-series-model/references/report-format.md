# Report Format

`generate_model_report(...)` 产出如下结构（中文，结论先行）：

```markdown
# <title>

## 一句话结论

<流程、均值/方差方程、模型类型、最优阶数、是否通过 + 原因>

## 1. 检测结果

> <reason：均值方程=…（LB/GPH），方差方程=…（ARCH-LM/Engle-Ng）>

### 1.1 ADF 平稳性（前提）
<statistic / pvalue / used_lag / is_stationary 表>

### 1.2 Ljung-Box 自相关（均值方程·短期）
<滞后阶 / 统计量 / p 值 表>
> 存在自相关：`<bool>`

### 1.3 GPH 长记忆检验（均值方程·分数积分 d）
<d_hat / se / tstat / pvalue / bandwidth / has_long_memory 表>
> 长记忆：`<bool>`

### 1.4 ARCH-LM 异方差效应（方差方程·波动聚集）
<滞后阶 / 统计量 / p 值 表>
> 存在 ARCH 效应：`<bool>`

### 1.5 Engle-Ng 符号偏差检验（方差方程·杠杆/非对称）
<sign_p / negative_p / positive_p / joint_p / has_asymmetry 表>
> 存在非对称（杠杆）：`<bool>`

### 1.6 ACF / PACF（辅助证据）
<滞后阶 / ACF / PACF 表，`*` 标记显著阶>

### 均值方程判定
**`<Constant/ARMA/ARFIMA>`**

### 方差方程判定
**`<Constant/GARCH/GJR>`**

![检测图](<stem>_diagnostics.png)

## 2. 建模

[白噪声] 判定为**白噪声**（常数均值 + 不变方差），无可建模结构，未进行拟合。

[建模] 
### 2.1 模型与最优阶数
- 流程：`<flow_a/b/c>`（均值方程 `<…>` + 方差方程 `<…>`）
- 模型类型 / 最优阶数（AIC/BIC；ARFIMA 含 d）/ 样本量 / AIC / BIC

### 2.2 参数估计
<参数名 / 参数值 表>（GJR 含 vol_gamma[1] 杠杆系数）

### 2.3 建模后 Ljung-Box 检测
- flow_a：均值方程残差（创新）Ljung-Box 表
- flow_b / flow_c：均值方程（标准化残差）+ 方差方程（标准化残差平方）两张表

### 2.4 结论
- 综合判定：通过 / 未通过
- 说明：<reason>

![预测图](<stem>_prediction.png)

## 3. 注意事项
- 作用在收益率/差分序列，不直接对价格建模。
- ARFIMA 两步法；GJR-GARCH 捕捉 Engle-Ng 杠杆。
- 检测对窗口/频率敏感，需复核。
- 仅用于研究方向判断，非下单依据。
```

- **白噪声**（均值=Constant 且 方差=Constant）时不建模，仅出检测报告与一句话结论。
- 检测图三联：收益率序列、ACF、收益率平方（直观展示波动聚集）。
- 预测图：实际序列 + 样本内拟合（ARFIMA 前若干边界点为 NaN，自然只画有效段）+ 向前预测同图。
