# Interpretation

## 组合方法学（最重要）
本 skill 的核心是 **"agent 把用户自然语言翻译成代码，再套模板"**：
1. 用户给规则（"ADX>25 且 MACD 金叉"）或特征集。
2. agent 用 `indicator` 库把规则落成 `rule` 函数 / `features` DataFrame + `label_fn`。
3. 调 `predict_by_indicator` / `predict_by_tree`，模板自动出报告。

模板不写死指标/规则/特征/标签——它们是参数。这样任意规则、任意特征集都能跑。

## 指标法

### ADX（Average Directional Index，Wilder）
- 衡量趋势**强度**（不分方向）。+DI/−DI 之差占和的比，再做 Wilder 平滑。
- 经验：**ADX>25 有趋势**，<20 无趋势（震荡）；本 skill 默认阈值 25，可改。
- 用 `indicator.adx(high, low, close, 14)`。

### Hurst（R/S 法）
- 衡量**持续性**：>0.5 持续/趋势，≈0.5 随机，<0.5 反持久（来回震荡）。
- `hurst_rs(series)` 全段标量；`hurst_rolling(series, 200)` 滚动（特征用）。
- 注意：R/S 对短窗噪声敏感；建议窗口 ≥100。

### MACD
- `macd_line = EMA(fast)−EMA(slow)`，`signal = EMA(macd, signal)`，`hist = macd−signal`。
- 金叉（macd 上穿 signal）/死叉作方向信号；hist 符号也可定方向。

### HMA（Hull MA）
- `WMA(2·WMA(n/2) − WMA(n), √n)`，低滞后、平滑。`close/hma−1` 作偏离特征。

### 默认 ground-truth 标签 `trend_label`
- 未来 horizon 天收益 |r| > k×**相对 ATR**(ATR/close) → 上行(+1)/下行(−1)，否则震荡(0)。
- 阈值用**相对 ATR** 是关键（与收益比率同量纲；若误用绝对 ATR 会全判 0）。
- horizon=10、k=1.5 为默认；用户要更严/更松就改 k，要更长视野就改 horizon。

## 决策树法

### 流程（模板固化）
1. **特征量纲统一**：每折 `StandardScaler` fit 于训练段——**绝不用全量 fit**（会泄漏未来统计）。
2. **相关性剔除**：初始训练段上算 |corr|，>0.9 的成对特征剔其一（保留靠前者），剔除理由入报告。
3. **滚动训练（expanding window）**：`train=[0,t] → test=[t,t+test_block]`，t 按 step 递增。
   - 分类：`RandomForestClassifier` + `XGBClassifier`；回归：`RandomForestRegressor` + `XGBRegressor`。
   - XGBoost 标签需 0..k-1，模板自动 remap。
4. **OOS 评估**：聚合各折 test 预测 → accuracy/precision/recall/F1（分类）或 RMSE/MAE/R²（回归）+ 混淆矩阵。

### 防过拟合 / 防泄漏（务必）
- 特征只用 t 时刻已知量（`close.shift(-k)` 这类**禁止**出现）。
- 标签是前瞻的，只能当 y；不能进特征。
- 标准化按折 fit；相关性筛选用初始训练段。
- 树深受限（max_depth 6–8）、加 subsample/colsample 抑制过拟合。
- OOS 才是可信指标；训练集指标无意义。

### 标签处理
- 分类：多类（如 ±1/0 三类）或二类（0/1 是否趋势）—— `label_fn` 决定，`task="classification"`。
- 回归：标签连续化（如未来 N 天收益率），`task="regression"`，模板自动切到 Regressor + RMSE/MAE/R²。

## 马尔可夫（占位，计划）
- HMM：观测序列 = [标准化对数收益, 标准化 ATR%]；`GaussianHMM(n_components=3)`；
- Viterbi 解码逐 bar 隐状态 → 按状态均值/方差映射「上行趋势/下行趋势/震荡」；
- 与 `trend_label` 对齐评估 precision/recall。依赖 `hmmlearn`（未装）。

## 深度学习（占位，计划）
- 特征序列按 `lookback` 切窗，监督标签 = `label_fn`；
- LSTM(seq→hidden→3类) 或轻量 Transformer Encoder；walk-forward 训练；
- 输出逐 bar 概率与分类。依赖 `torch`（未装）。

## 通过/未通过怎么看
- 指标法：accuracy 与 weighted F1 高于"全猜多数类"才算有用；重点看 **趋势类 recall**（别漏趋势）。
- 决策树法：只看 **OOS**；训练集高、OOS 低 = 过拟合，需减特征/降树深/加正则。
- 3 类都难；若 range 占多数，accuracy 易虚高，务必看 weighted-F1 与逐类 recall。
