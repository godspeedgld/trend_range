---
name: bigquant-sdk
description: BigQuant SDK data acquisition skill. Use when the user asks to fetch market
  data from BigQuant platform, query BigQuant data tables (futures/stock daily bars,
  minutes, factors, etc.), download historical OHLCV data, cache BigQuant data locally
  as CSV/Parquet, or write Python code that calls BigQuant DataSource/dai APIs.
license: GPL-3.0-only
metadata:
  project_type: skill
  category: data-api
  tags:
  - bigquant
  - market-data
  - python-sdk
  - futures
  - stock
  status: dev
  validation_level: runnable
  summary_zh: 调用 BigQuant SDK 获取期货/股票行情数据并保存本地（Parquet/CSV），支持 DSL 自然语言转 API 调用。
---

# BigQuant SDK — 数据获取与本地存储

把自然语言数据需求路由到 BigQuant DataSource / dai API，拉取行情数据并保存到本地。

## 核心能力

1. **数据获取**：通过 `DataSource().read()` 拉取期货/股票日线、分钟线、因子等数据
2. **本地存储**：保存为 Parquet / CSV，支持分区（按品种/年份）
3. **SQL 查询**（可选）：通过 `dai.query()` 在 BigQuant 云端执行 SQL

## 安装与初始化

```bash
# 安装 BigQuant SDK
pip install bigquant -U

# 验证安装
python -c "import bigquant; print('bigquant SDK OK')"
```

## 认证（AK/SK 密钥对）

BigQuant SDK 使用 **AK/SK 密钥对**认证，不是浏览器 OAuth。

### 获取密钥

访问 BigQuant 控制台生成：https://bigquant.com/account/settings → API 密钥

### 配置方式（三选一）

**方式 1：配置文件（推荐）** — `~/.bigquant/config.json`

```json
{
  "auth": {
    "ak": "your_access_key",
    "sk": "your_secret_key"
  }
}
```

SDK 自动读取，无需手动调登录函数。

**方式 2：环境变量**

```bash
export BIGQUANT_AK=your_access_key
export BIGQUANT_SK=your_secret_key
```

**方式 3：代码中显式设置**

```python
import bigquant
bigquant.set_token(ak="your_ak", sk="your_sk")
```

## 数据获取模式

### dai.query() SQL 接口（推荐）

直接写 SQL 从 BigQuant 云端查询，返回 DataFrame。

```python
from bigquant import dai

result = dai.query(
    "SELECT date, instrument, open, high, low, close, volume "
    "FROM cn_future_bar1d "
    "WHERE date >= '2024-01-01' AND date <= '2025-06-30' "
    "AND instrument IN ('AU2506.SHF', 'IF2506.CFX') "
    "ORDER BY date, instrument"
)
df = result.df()  # -> pd.DataFrame
```

```python
# A股日线
result = dai.query(
    "SELECT date, instrument, close, volume "
    "FROM cn_stock_bar1d "
    "WHERE instrument = '000001.SZ' AND date >= '2024-01-01'"
)
df = result.df()
```

## 常用数据表（详见 references/data_tables.md）

| 表 ID / SQL 表名 | 说明 | 频率 |
|---|---|---|
| `bar1d_CN_FUTURE` / `cn_future_bar1d` | 期货日线行情 | 日 |
| `bar1d_CN_STOCK_A` / `cn_stock_bar1d` | A股后复权日线 | 日 |
| `bar1d_CN_STOCK_A_adjust` | A股前复权日线 | 日 |
| `bar1d_CN_INDEX` | 指数日线 | 日 |
| `cn_stock_prefactors_community` | 预计算因子（社区版） | 日 |

## 核心约定

- 日期格式 `yyyy-mm-dd`（区别于 Pandadata 的 `YYYYMMDD`）
- 期货合约代码格式：`IF2506.CFX`、`AU2506.SHF`、`HC2506.SHF`
- A股代码格式：`000001.SZ`、`600000.SH`（与 Pandadata 一致）
- 指数代码格式：`000300.SH`、`000905.SH`
- `fields=[]` 或省略 → 返回所有字段
- `instruments` 省略 → 返回全市场（数据量大，慎用）

## 脚本工具

### call_api.py — 通用数据拉取 + 本地保存

```bash
PYTHON_BIN="${BIGQUANT_PYTHON:-python}"
"$PYTHON_BIN" scripts/call_api.py \
  --table bar1d_CN_FUTURE \
  --instruments IF2506.CFX,IC2506.CFX \
  --start 2024-01-01 \
  --end 2025-06-30 \
  --output ./data/futures_daily.parquet \
  --format parquet
```

参数表：
| 参数 | 说明 |
|---|---|
| `--table` | 数据表 ID |
| `--instruments` | 合约代码（逗号分隔），省略=全市场 |
| `--start` / `--end` | 日期范围 yyyy-mm-dd |
| `--fields` | 字段（逗号分隔），省略=全字段 |
| `--output` | 输出文件路径（.parquet / .csv） |
| `--format` | 输出格式 parquet / csv |

行为：
- 若 `bigquant` SDK 未安装 → 报错提示安装 `pip install bigquant`
- 若未登录 → SDK 自动弹出浏览器授权
- 数据为空 → 报 warning 但不报错
- 输出目录自动创建

## 与 Pandadata 的差异

| 维度 | BigQuant | Pandadata |
|---|---|---|
| 日期格式 | `yyyy-mm-dd` | `YYYYMMDD` |
| 期货代码 | `IF2506.CFX` | 主力: `IF_DOMINANT.CFX` |
| 认证 | AK/SK 密钥对 | username/password |
| 数据源概念 | `DataSource('table_id')` | `panda_data.get_*()` |
| 股指期货 | 支持 IF/IH/IC/IM | 仓库 `future_daily` 无 |

## Reference Files

- `references/data_tables.md`：可用数据表目录（字段+代码示例）
- `references/api_reference.md`：API 详细文档

## Agent Usage Rules

- 查询数据表结构前先看 `references/data_tables.md`
- 生成代码用 `DataSource().read()` 模式（更简洁）
- 代码必须可直接运行，包含 import 和登录引导
- 首次使用提示用户：SDK 会弹出浏览器授权
- 数据拉取后报告：行数、列、日期范围、内存占用
