# Report Format

`generate_report(...)` 按 `result["branch"]` 产出如下结构（中文，结论先行）。

## 指标法（branch = indicator）
```markdown
# <series> 趋势预测报告（指标法）

## 一句话结论
<准确率 / 加权F1 + 有效样本数>

## 1. 评判规则（调用方翻译生成的代码）
```python
<rule 函数源码>```

## 2. 用到的指标
`adx`, `macd_line`, `hurst200`, ...

## 3. 预测分布
| 预测类别 | 数量 |

## 4. 评估指标
| 指标 | 值 |          (accuracy / precision(w) / recall(w) / f1(w))
### 逐类（per-class）  | 类别 | precision | recall | f1 |
### 完整 classification_report  （文本块）

![混淆矩阵](<stem>_confusion.png)
![close 着色](<stem>_close.png)
![K线着色](<stem>_kline.png)

## 5. 注意
- 指标/规则/标签由调用方动态生成；评估依赖前瞻 ground-truth，仅回测。
```

## 决策树法（branch = tree）
```markdown
# <series> 趋势预测报告（决策树法·classification|regression）

## 一句话结论
<特征数 / 剔除数 / 模型 / OOS 指标>

## 1. 特征工程
**保留特征（N）**：`adx`, `macd`, ...
**剔除特征（高相关>0.9）**：| 被剔除 | 原因 |
![相关性热图](<stem>_corr.png)
![特征重要性](<stem>_importance.png)

## 2. 滚动训练设置
| 任务 | min_train | step | test_block | models |
### 各折（最近）  | fold | train_end | test_size | <model>(acc|rmse) ... |

## 3. 样本外(OOS)汇总
分类：| 模型 | accuracy | precision(w) | recall(w) | f1(w) |
回归：| 模型 | RMSE | MAE | R² |

![混淆矩阵-<model>](<stem>_confusion_<model>.png)   （仅分类）
![OOS 判定](<stem>_close.png)

## 4. 标签函数（调用方提供）
```python
<label_fn 源码>```

## 5. 注意
- 特征/标签/模型由调用方动态生成；标准化按折 fit；相关性用初始训练段；仅回测。
```

## 马尔可夫 / 深度学习（branch = markov | dl）
```markdown
# 趋势预测报告（<方法>法 · 占位）
> 状态：not_implemented
## 计划方案
<HMM / LSTM-Transformer 实施方案说明>
```

## 默认（branch = default）
```markdown
# <series> 数据描述报告
> 提示：未匹配到具体预测流程（hint=...）。
## 基本信息 | 列 / 行数 / ADF p值
## close 摘要 | min/max/first/last
## 对数收益摘要 | mean/std
## 建议   传 method 选具体流程（由 agent 判定走 indicator / tree）
```

---
通用：
- 趋势段着色 = **红**，震荡段 = **绿**（close 图与 K 线图同配色）。
- 结论先行；过程（规则源码/筛选理由/每折指标）随后；图放相应小节末尾。
