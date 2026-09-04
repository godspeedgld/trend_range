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
