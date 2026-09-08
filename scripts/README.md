# scripts — 平台突破（阻力线）算法版本库

沪深300 平台突破研究的阻力带算法主线（自 replication/research-projects/hs300-enh-2017-2021/shared/ 同步的独立副本）。
仅依赖 numpy/pandas，脱离项目数据可独立运行（算法本身不读外部数据，需自行喂 date/open/high/low/close）。

## 版本演进

| 版本 | 范式 | 状态 | 说明 |
|---|---|---|---|
| **plateau_algo.py** (v1) | 252 窗 HSAR 分箱聚集 | 冻结 | 窗口切片边界效应、台阶式新高无聚集 |
| **plateau_algo_v2.py** (v2.x) | OLS 斜趋势线 + 通道带 | **v2.7 锁定** | 平台重锚定/待定突破/close_rate 提前成线/速率断线 |
| **plateau_algo_v3.py** | 水平阻力带（转折点价±5%聚类）| **锁定** | 带重叠递归合并、degree=带计数、收盘>带上界=突破；高低点分流（H→阻力/L→支撑）|
| **plateau_algo_v4.py** | v3 + 阻力带生命周期 | 锁定（09-04）| 死带=累计90日 close>line×1.10 或单日 close>line×1.30；支撑带对称（×0.90 累计 / ×0.70 单日）。突破只由当期活带发 |

## 用法

```python
from plateau_algo_v3 import run_band_breakout     # v3：返回 (events, bands, state_machine)
from plateau_algo_v4 import run_band_breakout_v4  # v4：活带突破事件 + 带生命周期
# events: break_up（v3/v4 阻力侧）/ break_down（支撑侧）
# bands_all (v4): 含 kind(R/S)/dead/dead_date/d_last，供可视化
```

v3/v4 事件级回测与统计详见 replication/research-projects/hs300-enh-2017-2021/
01_data_analysis/analysis_007（v3 更新五~八）与 analysis_012（v4 生命周期/回测/分布）。

## 同步说明

改算法时：先在此副本改并验证，再同步回 replication shared（或反向），保持两份一致。

## 另一范式：分位数回归压力/支撑线（quantreg_sr_algo.py）

| 模块 | 算法 | 状态 | 要点 |
|---|---|---|---|
| **quantreg_sr_algo.py** | 局部极值 + 分位数回归趋势线（Lang et al. 2012 路线，渤海证券 2022-09 复现） | 锁定（09-08）| w=5 极值 → N=120 窗分位回归（高点 τ=0.9/低点 τ=0.1，首日归一 100）→ (p1,p2) 斜率分类 6 持续+5 通道形态 → 上穿突破事件。**causal/faithful 双口径**：中心极值含未来 w 日确认（忠实口径有前视：复现实测突破后 20 日 +0.63%→因果 -0.17%），实盘一律 causal=True |

与 plateau 家族（水平带）为不同范式：本算法产出**有斜率的趋势线**。依赖 statsmodels。
复现包：replication/渤海证券-指数技术择时之一-压力线与支撑线的识别算法及应用/（门禁 25/25）。
