# BigQuant SDK — 数据获取 + 本地仓库

两段式流水线：`dai.query(SQL)` 拉取行情 → Parquet 分区 + DuckDB 视图存本地。

## 快速开始

```bash
pip install bigquant pandas duckdb pyarrow
```

### 数据拉取

```python
from bigquant import dai

df = dai.query(
    "SELECT date, instrument, close, volume "
    "FROM cn_stock_bar1d "
    "WHERE instrument = '000001.SZ' AND date >= '2024-01-01'"
).df()
```

### CLI 工具

```bash
python scripts/call_api.py \
  --table cn_stock_bar1d \
  --instruments 000001.SZ \
  --start 2024-01-01 --end 2025-06-30 \
  --output ./stocks.parquet
```

### 本地仓库

```python
# 拉取 → 分区 Parquet → DuckDB 视图
import pandas as pd; from pathlib import Path; import duckdb

ROOT = Path("data_cache/bigquant_warehouse")
df["year"] = pd.to_datetime(df["date"]).dt.year
for year, grp in df.groupby("year"):
    (ROOT / f"stock_bar1d/year={year}").mkdir(parents=True, exist_ok=True)
    grp.to_parquet(ROOT / f"stock_bar1d/year={year}/part.parquet", index=False)

con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
con.execute("CREATE VIEW stock_bar1d AS SELECT * FROM read_parquet('.../year=*/part.parquet', hive_partitioning=true)")
```

## 目录结构

```
skill-bigquant-sdk/
  SKILL.md                     # AI agent 主指令
  README.md
  scripts/call_api.py          # CLI: SQL → fetch → Parquet/CSV
  references/
    data_tables.md             # 表结构目录（字段+类型+示例）
    sql_templates.md           # 常用 SQL 查询模板
    warehouse-playbook.md      # 仓库设计规范（分区/刷新/校验）
```

## 支持的数据表

| 表名 | 说明 |
|------|------|
| cn_stock_bar1d | A股后复权日线 |
| cn_future_bar1d | 期货日线 |
| cn_future_bar1d_adjust | 期货复权日线 |
| cn_fund_bar1d | 基金后复权日线 |
| cn_stock_bar1m_c | A股1分钟截面 |
| cn_future_bar1m_c | 期货1分钟截面 |
| all_trading_days | 交易日历 |

## 认证

AK/SK 密钥对，配置到 `~/.bigquant/config.json`：

```json
{"auth": {"ak": "your_key", "sk": "your_secret"}}
```

获取密钥：https://bigquant.com/account/settings

## License

GPL-3.0-only
