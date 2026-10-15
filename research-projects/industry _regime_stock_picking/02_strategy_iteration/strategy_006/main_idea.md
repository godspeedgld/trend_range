# 策略思路 — strategy_006

> **承接 strategy_002 的基线**（= 云端原版：变盘指数行业轮动 + 四因子恒反转选股）。
> 本迭代**只去掉一个部件**：稳定性空仓过滤（exposure ≡ 1.0）。**行业层 / 选股 / 缓冲 / 权重 / 成本全部不动**。
>
> 日期：2026-10-15 ｜ 类型：**结构消融**（不是加东西，是拆东西）｜ 结论：**被否 —— 稳定性过滤是基线最大的绩效来源**

## 因子策略模板

**模型训练**：不适用（规则型策略）。

**评分逻辑**：与基线**逐字相同**——行业内四因子（`turn_ratio / px_ma20 / mom_20 / liq_amount`，
方向恒 −1）复合百分位排名取前 2 + 老仓前 6 名缓冲（`shared/build_weekly_targets.py` 冻结件原样 import）。

**唯一差别**：

```python
# 基线（build_weekly_targets.py / strategy.py 接口④）
exposure = 1.0 if (prev_top3 is None or set(top3) == set(prev_top3)) else 0.0
# 本迭代
exposure = 1.0
```

即**去掉**「本周 top3 与上周不完全相同 → 空仓一周」的规则，每周满仓。

## 动机（用户 2026-10-15 指令）

1. analysis_009 显示基线 63.4% 的周空仓（494 周中 313 周），这个部件的**单独贡献**从未被量化过
   （云端「稳定性过滤贡献最大」的说法是历史对比，口径未存档）；
2. 若空仓过滤贡献小 → 去掉它可提升资金利用率，给后续反向量能闸门腾出空间；
3. 若贡献大 → 它就是「主线稳定用动量、不稳定用反转」框架的**执行载体**，
   后续一切行业层改造（含 analysis_009 反向闸门）必须与它**叠加**而不是替换。

## 本迭代要回答的问题

**稳定性空仓过滤到底值多少净值？**

## 产物

- `backtest_strategy/`：去空仓版（`shared/_cache/targets_daily_nostab_indpre.parquet`）
- `backtest_strategy_baseline/`：同目录对照 = 基线（复用冻结的 `targets_daily_baseline_indpre.parquet`）
- 指标**由 trades 推算**（引擎自带 `metrics_from_trades.csv` / `nav_from_trades.csv`）
