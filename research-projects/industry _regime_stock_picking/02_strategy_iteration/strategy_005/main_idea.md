# 策略思路 — strategy_005

> **承接 strategy_004**（六因子 = 方案 B）。本迭代**把六因子砍到四因子**：
> 去掉 `px_ma20` 与 `liq_amount`，留下 `turn_ratio` · `breakdown_5w_smooth`(R076) · R221 · R222。
> **其余（行业层 / 调仓 / 缓冲 / 仓位 / 稳定性过滤 / 复合方式 / 引擎）与迭代四一字不差。**
>
> 日期：2026-10-13 ｜ 类型：**因子策略**（行业轮动 + 行业内选股）｜ 结论：**被否**（见 final_report）

## 因子策略模板

**模型训练**：不适用（规则型策略，无监督学习环节）。

**评分逻辑**：行业内**四因子复合百分位排名**，每行业取前 2 只。复合方式与基线/迭代四**完全一致**
（`mean(rank_pct(因子ᵢ × 方向ᵢ))`、全 NaN 候选剔除、并列用 `instrument` 二级键）。

| 因子 | 计算 | 方向 | 相对迭代四 |
|---|---|---|---|
| `turn_ratio` | 5周均换手 / 60周均换手 | −1 | 不变 |
| `breakdown_5w_smooth`(R076) | `EMA3(1 − close/min(low 前5周))` | +1 | 不变 |
| `price_volume_corr_5w_confirm_volume`(R221) | `corr5(周涨跌幅, 周量变化) × volume/MA20(volume)` | −1 | 不变 |
| `obv_slope_5w_confirm_volume`(R222) | `(OBV 5周斜率/MA5(volume)) × volume/MA20(volume)` | −1 | 不变 |
| ~~`px_ma20`~~ | ~~close / MA20 − 1~~ | — | **去掉** |
| ~~`liq_amount`~~ | ~~20周均成交额~~ | — | **去掉** |

**去掉的两个及理由**：
- **`px_ma20`**：与 R076 池内 **|ρ|=0.69**，同一信号重复下注；留更强的那个（R076 IC 0.0659 / t 7.74
  vs px_ma20 0.0605 / 6.50）
- **`liq_amount`**：全组最弱（IC 0.0290 / t 3.25）

**本迭代要回答的问题**（承迭代四的否结论）：既然**加/换**因子在组合层不成立，那**精简**
（去掉重复的 + 去掉最弱的）会不会更好？

## 产物

- `backtest_strategy/`：4 因子版（权重引擎）
- `backtest_strategy_baseline/`：同目录对照 = 基线四因子（复用冻结的 `targets_daily_baseline_indpre.parquet`）
- 选股扩展：`shared/build_weekly_targets_b4.py`（**新增文件**，不改 `build_weekly_targets.py` / `_b6`）
- 指标**由 trades 推算**
