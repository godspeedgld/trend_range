---
name: bigquant-sdk
description: BigQuant SDK data acquisition and local warehouse skill. Use when the user
  asks to fetch market data from BigQuant, query BigQuant data tables, download OHLCV
  data, cache BigQuant data locally as Parquet with DuckDB views, or write Python
  code that calls BigQuant dai.query APIs.
license: GPL-3.0-only
metadata:
  project_type: skill
  category: data-api
  tags: [bigquant, market-data, python-sdk, futures, stock, warehouse, duckdb, parquet]
  status: dev
  validation_level: runnable
  summary_zh: BigQuant 数据获取 + 本地仓库：dai.query() SQL 拉取行情，Parquet 分区存储，DuckDB 视图查询。
---

# BigQuant SDK — 数据获取 + 本地仓库

两段式流水线：① `dai.query(SQL)` 拉数据 → ② Parquet 分区 + DuckDB 视图本地存库。

---

# Part 1：数据获取

## 认证（AK/SK）

去 https://bigquant.com/account/settings 获取密钥，配置到 `~/.bigquant/config.json`：

```json
{
  "auth": {
    "ak": "your_access_key",
    "sk": "your_secret_key"
  }
}
```

## dai.query() — 统一 SQL 接口

BigQuant 所有行情数据通过一个接口获取：`dai.query(sql)` → `result.df()`。

```python
from bigquant import dai

# 股票日线
df = dai.query(
    "SELECT date, instrument, open, high, low, close, volume "
    "FROM cn_stock_bar1d "
    "WHERE instrument = '000001.SZ' AND date >= '2024-01-01'"
).df()

# 期货日线（需要账号有期货数据权限）
df = dai.query(
    "SELECT * FROM cn_future_bar1d "
    "WHERE instrument IN ('AU2506.SHF', 'IF2506.CFX') "
    "AND date >= '2024-01-01' AND date <= '2025-06-30' "
    "ORDER BY date, instrument"
).df()

# 交易日历
td = dai.query("SELECT date, market_code FROM all_trading_days").df()
```

## 表名速查

| SQL 表名 | 说明 | 主键 |
|----------|------|------|
| `cn_stock_bar1d` | A股后复权日线 | (instrument, date) |
| `cn_stock_bar1m_c` | A股1分钟截面 | (instrument, date) |
| `cn_future_bar1d` | 期货日线 | (instrument, date) |
| `cn_future_bar1m_c` | 期货1分钟截面 | (instrument, date) |
| `cn_fund_bar1d` | 基金后复权日线 | (instrument, date) |
| `cn_stock_chips_distribution` | 筹码分布 | (instrument, date) |
| `all_trading_days` | 交易日历 | (date, market_code) |

完整字段见 `references/data_tables.md`，SQL 模板见 `references/sql_templates.md`。

## 安装

```bash
pip install bigquant pandas pyarrow duckdb
```

---

# Part 2：本地仓库

## 仓库布局

```text
data_cache/bigquant_warehouse/
  _meta.json                     # 全局元数据（watermark + 状态）
  bigquant_warehouse.duckdb      # DuckDB 视图库
  trading_days/part.parquet      # 交易日历基准（全量覆盖）
  stock_bar1d/year=2024/part.parquet
  future_bar1d/year=2024/part.parquet
  future_bar1m_c/year=2024/month=01/part.parquet
  fund_bar1d/year=2024/part.parquet
  stock_chips/year=2024/part.parquet
```

分区键：日线 → `year`，分钟 → `year/month`。

## 拉取 + 入库（核心流水线）

```python
from pathlib import Path
from datetime import datetime
import pandas as pd
import duckdb
from bigquant import dai

ROOT = Path("data_cache/bigquant_warehouse")
TABLE = "stock_bar1d"                # 仓库表名
SOURCE = "cn_stock_bar1d"            # BigQuant SQL 表名
START, END = "2024-01-01", "2025-06-30"

# 1. 拉取
sql = f"SELECT * FROM {SOURCE} WHERE date >= '{START}' AND date <= '{END}'"
df = dai.query(sql).df()

# 2. 按年分区写 Parquet
df["year"] = pd.to_datetime(df["date"]).dt.year
table_dir = ROOT / TABLE
for year, grp in df.groupby("year"):
    part_dir = table_dir / f"year={year}"
    part_dir.mkdir(parents=True, exist_ok=True)
    out = part_dir / "part.parquet"
    if out.exists():
        existing = pd.read_parquet(out)
        grp = pd.concat([existing, grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
    grp.to_parquet(out, index=False)

# 3. DuckDB 视图（一次性创建，后续刷新后重建）
db = ROOT / "bigquant_warehouse.duckdb"
con = duckdb.connect(str(db))
con.execute(f"""
    CREATE OR REPLACE VIEW {TABLE} AS
    SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)
""")
con.close()

print(f"入库完成: {len(df)} 行 → {table_dir}")
```

## DuckDB 查询

```python
import duckdb
con = duckdb.connect("data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")

df = con.execute("""
    SELECT date, instrument, close, volume
    FROM stock_bar1d
    WHERE instrument = '000001.SZ' AND date >= '2024-01-01'
    ORDER BY date
""").fetchdf()
```

## 增量刷新

```python
# 读 watermark → 只拉缺失区间
import json
meta = json.loads((ROOT / "_meta.json").read_text())
wm = meta["tables"][TABLE].get("end_date", "2005-01-01")
latest = str(pd.to_datetime("today").date())  # 或从 trading_days 取

if wm < latest:
    # 拉取 (wm, latest] + 原样入库
    ...
    # 更新 watermark
    meta["tables"][TABLE]["end_date"] = latest
    (ROOT / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
```

## 核心约定

- **交易日对齐**：本地日期范围不超出 `all_trading_days` 最新日期
- **增量追加**：历史数据不变，只拉 `(watermark, latest]` 区间
- **主键去重**：`(instrument, date)`，写入前合并去重
- **后复权数据**：历史稳定，可安全增量追加
- **分钟数据**：量大（数 GB），必须指定 instruments 缩小范围

详见 `references/warehouse-playbook.md`。

---

## CLI 工具

`scripts/call_api.py` — 快速拉取 + 保存，不走仓库：

```bash
python scripts/call_api.py \
  --table cn_stock_bar1d \
  --instruments 000001.SZ,600000.SH \
  --start 2024-01-01 --end 2025-06-30 \
  --output ./data/stocks.parquet
```

## 与 Pandadata 的差异

| 维度 | BigQuant | Pandadata |
|------|----------|-----------|
| 数据接口 | `dai.query(sql)` 统一 SQL | 185 个 `get_*` 方法 |
| 日期格式 | `yyyy-mm-dd` | `YYYYMMDD` |
| 期货主键列 | `instrument` | `symbol` |
| 期货代码 | `AU2506.SHF`（具体合约） | `AU_DOMINANT.SHF`（主力） |
| 认证 | AK/SK 密钥对 | username/password |

## Reference Files

- `references/data_tables.md`：完整表结构（字段+类型+示例）
- `references/sql_templates.md`：常用 SQL 查询模板
- `references/warehouse-playbook.md`：仓库设计规范（分区/刷新/校验/安全）

## Agent Usage Rules

- 查表结构 → `references/data_tables.md`
- 写 SQL → `references/sql_templates.md` 抄模板
- 建仓库 → `references/warehouse-playbook.md` + 本文件 Part 2
- 代码必须可直接运行，包含 import
- 拉取后报告：行数、日期范围、品种数
- 免费账号期货表可能无权限，提示升级
