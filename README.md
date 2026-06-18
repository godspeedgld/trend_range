# trend_range — 期货趋势 / 震荡 / 综合策略实证

基于 [ssquant](https://github.com/songshuquant/ssquant)（中国期货 CTP 量化框架）的实证研究项目，三个目标：

1. **趋势跟踪策略**实证（主要期货）—— 见 [`trend_following/`](trend_following/)
2. **震荡行情**策略实证（规划中）
3. **综合策略**（规划中）

当前进度：趋势跟踪部分已完成"收益统计特征 + EMA 波动率 + TSMOM 面板回归"的实证管线。

---

## 快速开始

### 1. 克隆（含子模块）

```bash
git clone --recurse-submodules <repo-url>
cd trend_range

# 若已 clone 但没带子模块：
git submodule update --init --recursive
```

### 2. 配置取数凭证（必需）

本项目通过 ssquant 的远程 data_server 取行情，**需要自备 [quant789](https://quant789.com) 俱乐部账号**（非 CTP 交易账户）。

打开 [`ssquant/ssquant/config/trading_config.py`](ssquant/ssquant/config/trading_config.py)，填写：

```python
API_USERNAME = "你的俱乐部手机号或邮箱"
API_PASSWORD = "你的俱乐部密码"
```

> 没有账号也可改用 `data_source_mode='local'` 离线回测，但需自行导入历史数据（见 ssquant 的 `examples/A_工具_导入数据库DB示例.py`）。

### 3. 安装

建议 Python 3.10–3.14（ssquant 的 CTP 二进制覆盖 py39–py314；仅做研究不接 CTP 则任意 3.9+ 即可）。

```bash
# 先装子模块（ssquant 自带打包配置）
pip install -e ./ssquant

# 再装本项目（注册 shared / trend_following 为可导入包）
pip install -e .
```

**`pip install -e .` 会自动安装本项目声明的依赖**（见 [`pyproject.toml`](pyproject.toml) 的 `dependencies`）：

| 依赖 | 用途 |
|---|---|
| `pandas` / `numpy` | 数据处理、收益/波动率计算 |
| `requests` | ssquant 远程取数 |
| `statsmodels` | TSMOM 面板回归的 HAC（Newey-West）标准误 |
| `plotly` | `shared.data_viz` 交互式图表 |

> ssquant 还会传递依赖装上它自己需要的包（akshare 等）。

装完后，`import ssquant`、`from shared...`、`from trend_following...` 在任意目录、任意启动方式下都可用（与运行目录解耦）。

---

## 目录结构

```
trend_range/
├── ssquant/                  # git submodule，期货 CTP 量化框架（行情/回测/SIMNOW/实盘）
├── shared/                   # 跨策略复用工具
│   ├── data_fetcher.py       #   fetch_klines / list_varieties
│   ├── data_viz.py           #   plot_feature / plot_stats_table / plot_stats_bar / plot_stats_box / plot_tsmom_tstat
│   └── sector.py             #   CATEGORY_MAP 板块分类 / get_category
├── trend_following/          # 趋势跟踪实证
│   └── check_trend_valid.py  #   calc_log_return / calc_return_stats / ema_volatility / calc_volatility / tsmom_regression
├── data_cache/               # (gitignore) SQLite 数据与缓存：returns.db 等
├── results/                  # (gitignore) HTML 图表输出
├── pyproject.toml
├── .env.example              # AI 助手配置模板（可选）
└── README.md
```

---

## 核心用法

### 取数与品种

```python
from shared.data_fetcher import fetch_klines, list_varieties
from shared.sector import get_category, CATEGORY_MAP

# 全部 90 个期货品种清单（品种代码 rb/hc/au，非合约 rb888）
list_varieties()

# 取 K 线（品种自动补 888 主力连续、后复权）
df = fetch_klines("rb", period="日线", start_date="2022-01-01", end_date="2024-12-31")
#   period ∈ {日线, 60分钟, 30分钟, 15分钟, 5分钟}

# 品种 → 板块
get_category("rb")          # '黑色'
CATEGORY_MAP["化工"]        # 21 个化工品种
```

板块分类共 13 类（黑色/有色金属/化工/能源/轻工/油脂油料/谷物/软商品/农副产品/贵金属/股指/国债/集运），已与 ssquant 的 90 个品种对齐；低流动性/特殊品种（纤维板、动力煤、月均价期货等）在 `trend_following.check_trend_valid.no_use_symbols` 中忽略。

### 对数收益率 + 统计特征

```python
from trend_following.check_trend_valid import calc_log_return, calc_return_stats

# 算单品种对数收益并存表；period ∈ {mon, week, 1d, 1h, 30m}（月/周由日线重采样）
calc_log_return("rb", start_date="1999-01-01", period="1d")     # → 1d_return 表

# 按品种算统计特征（count/mean/std/分位/min/max/skew/kurt）存 return_stats 表
calc_return_stats("1d")
```

### 波动率（EMA，类 GARCH，AQR/Hurst TSMOM 口径）

```python
from trend_following.check_trend_valid import ema_volatility, calc_volatility

# 单值时序：指数加权事前波动率 σ_t（com=60 天重心，无前视）
vol = ema_volatility(returns, com=60, annualize=252)

# 把 σ_t 写回收益表的 volatility 列（配 r_t 用）
calc_volatility("rb", period="1d")
```

### TSMOM 面板回归（趋势是否存在）

```python
from trend_following.check_trend_valid import tsmom_regression

# 给定 h，全市场面板回归 r_{t→t+h}/σ_t ~ r_{t-h→t}，返回 β 的 t 统计量
t = tsmom_regression(period="1d", h=12)
# t>2 → 该 h 下动量（趋势）显著为正；t<-2 → 反转
```

### 可视化（输出 HTML 到 results/）

```python
from shared.data_viz import (
    plot_feature,          # 单品种收益折线
    plot_stats_table,      # 统计特征表（表头可点击排序）
    plot_stats_bar,        # 单特征柱状图（skew/kurt 带 y=0 参考线）
    plot_stats_box,        # 按板块箱线图
    plot_tsmom_tstat,      # 扫描 h 的 t 统计量柱状图（复刻 MOP 的 t-stat vs h）
)
plot_tsmom_tstat(period="1d", minh=1, maxh=120, steph=1)
```

---

## 数据存储说明

所有数据落在 `data_cache/`（已 gitignore）。

**`returns.db`** 的表：

| 表 | 字段 | 说明 |
|---|---|---|
| `1d_return` / `week_return` / `mon_return` / `1h_return` / `30m_return` | datetime, symbol, category, log_return, volatility | 各周期对数收益长表；volatility 为 σ_t（事前，配 r_t）|
| `return_stats` | symbol, category, period, start_date, end_date, count, mean, std, min, q25, q50, q75, max, skew, kurt | 按品种×周期的统计特征 |

写库用 UPSERT：重算收益不破坏已存的波动率，反之亦然。

---

## 已知限制

- **数据回溯仅到 2022-01-05**：ssquant 的 data_server 对几乎所有品种都只回溯到 2022 年初（与品种上市日无关，是 server 端上限）。短样本品种（股指/国债 2024 起、pd/pt 2025-11 起等）更短。需更长历史请换数据源（具体方案待定）。
- **结论受单一 regime 影响**：2022 至今偏下跌/震荡，TSMOM 的"反转"结论可能只反映这一段，不宜过度外推。

---

## 配置文件

- `.env.example`：AI 助手（Claude Code 等）的配置模板，含 `PYTHON_EXE` 指向解释器路径；普通运行脚本不需要它。
- `.vscode/`：本地 IDE 配置（已 gitignore，含机器特有的解释器路径）。
