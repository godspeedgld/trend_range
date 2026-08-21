# Warehouse Playbook — BigQuant 本地仓库

本地 Parquet + DuckDB 仓库的设计约定和运行规范。

## 仓库布局

```text
{root}/                          # 默认 data_cache/bigquant_warehouse/
  _meta.json                     # 全局元数据
  bigquant_warehouse.duckdb      # DuckDB 视图库（只读视图，不存数据）
  trading_days/part.parquet      # 交易日历基准（全量覆盖）
  stock_bar1d/year=2024/part.parquet
  future_bar1d/year=2024/part.parquet
  future_bar1m_c/year=2024/month=01/part.parquet
  fund_bar1d/year=2024/part.parquet
  stock_chips/year=2024/part.parquet
```

分区键：日线 → `year`，分钟 → `year/month`。

## 元数据 `_meta.json`

```json
{
  "root": "data_cache/bigquant_warehouse",
  "trading_days": { "latest_date": "2026-08-07", "last_refresh_at": "..." },
  "tables": {
    "stock_bar1d": {
      "source_table": "cn_stock_bar1d",
      "partition_keys": ["year"],
      "primary_keys": ["instrument", "date"],
      "date_column": "date",
      "start_date": "2005-01-04", "end_date": "2026-08-07",
      "last_refresh_at": "...", "row_count": 12345678,
      "status": "ok"
    }
  }
}
```

## 交易日历基准

所有本地数据日期范围以 `all_trading_days` 为硬上限：

```python
from bigquant import dai
td = dai.query("SELECT date FROM all_trading_days ORDER BY date").df()
latest_trade_date = str(td["date"].max())[:10]  # "2026-08-07"
```

刷新前必须检查，本地 watermark 不得超出此日期。

## 增量刷新策略

### Append-stable（增量追加）
- 股票/期货/基金日线：历史后复权数据不变
- 分钟线：同上

### Full-replace（全量覆盖）
- 交易日历

### 刷新流程

```
1. 从 all_trading_days 获取 latest_trade_date
2. 读 _meta.json → 获取表 watermark (end_date)
3. 若 watermark >= latest_trade_date → 跳过
4. 拉取缺失区间 (watermark + 1day, latest_trade_date]
5. 按分区键写入 Parquet（追加合并去重）
6. 重建 DuckDB 视图
7. 更新 _meta.json watermarks
8. 校验
```

## DuckDB 视图

使用 `read_parquet` + `hive_partitioning=true`，不复制数据：

```sql
CREATE OR REPLACE VIEW stock_bar1d AS
SELECT * FROM read_parquet(
    'data_cache/bigquant_warehouse/stock_bar1d/**/*.parquet',
    hive_partitioning = true
);

CREATE OR REPLACE VIEW future_bar1d AS
SELECT * FROM read_parquet(
    'data_cache/bigquant_warehouse/future_bar1d/**/*.parquet',
    hive_partitioning = true
);
```

查询时直接 SQL：

```python
import duckdb
con = duckdb.connect("data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")
df = con.execute("SELECT * FROM stock_bar1d WHERE date >= '2024-01-01'").fetchdf()
```

## 校验清单

每次刷新后检查：

- [ ] Parquet 文件存在且非空
- [ ] 主键 `(instrument, date)` 分区内无重复
- [ ] 日期范围不超出交易日历最新日期
- [ ] 必填列无全空（open/high/low/close）
- [ ] 价格 > 0（日线级别）
- [ ] DuckDB 可查询视图，返回预期日期范围
- [ ] 抽样 3 品种 × 3 日期与 BigQuant 实时 API 对比

校验不过 → 标记 `partial` 或 `failed`，保留已有有效数据。

## 衍生数据分层规范（原始 / 视图 / 物化）

衍生指标（市值 = 价 × 股本、PE = 市值 / 利润、滚动均值等）按以下三层组织。**核心原则：单一事实源**——同一数据只存一份原始事实，一切派生量可随时重算。

### 层0 原始层（Parquet 落盘）

只存**不可推导的原始事实**：

| 数据 | 例 |
|------|-----|
| 行情 | OHLCV、复权因子（stock_bar1d） |
| 股本 | 总股本/流通股（stock_shares） |
| **数据源算好的通用指标** | `cn_stock_valuation` 的 pe_ttm/pb/ps_ttm 等日频列 |

> 数据源现成的通用指标（PE/PB/市值/股息率）**当原始事实拉取入库**，不要自己用财报重算——TTM 对齐/动态年化（1季报×4/1…）的报告期对齐逻辑复杂易错，数据源口径即权威。

### 层1 视图层（DuckDB VIEW，运行时生成）

**确定性派生**放视图——CREATE VIEW 只存 SQL 定义不存数据，每次查询现算：

```sql
-- 例：市值（仅当数据源没有现成列时才自建）
CREATE VIEW v_mkt_cap AS
SELECT b.date, b.instrument,
       r.close * s.total_shares AS total_market_cap,
       ln(r.close * s.total_shares) AS ln_cap
FROM stock_bar1d b
JOIN stock_shares s USING (instrument, date);
```

适用：join/乘除/滚动窗口（`AVG(x) OVER (... ROWS BETWEEN n PRECEDING AND CURRENT ROW)`）——DuckDB 列式引擎毫秒级，查询无感。

优点：零存储、改口径只改一处、永不与原始数据不一致。

### 层2 物化层（TABLE，仅计算昂贵时）

只当**重算成本高到影响使用**才物化（`CREATE TABLE t AS SELECT ...`）：

- 逐步回归系数（全样本迭代）
- 全市场截面排序因子（每日 rank）
- 复杂循环算法的输出（如转折点识别的信号序列）

> 判断口诀：**能 rolling/视图的别存，存只存算不动的**。

### 视图的生成时机

- **通用衍生**（多项目复用、口径行业标准）：预建为常备基础设施
- **策略特有中间量**（单策略用、口径自定义）：需求出现时建，用完**不删**（视图零存储成本）沉淀复用
- 沉淀标准：第二个项目用到同一视图时，升级为标准视图并在文档登记口径

### 口径警告

- **后复权价不能算估值**：市值/PE 必须用未复权真实价（如 `cn_stock_real_bar1d`），或确认数据源列的复权口径
- 视图命名带 `v_` 前缀与原始表区分；口径写进视图 SQL 注释

## 安全规则

- 删除操作前必须列出受影响的具体文件
- AK/SK 不得写入 metadata、Parquet、日志
- 分钟数据全市场量大（数 GB），必须指定 instruments
- API 失败时区分：认证/权限/网络/空数据/速率限制
- 增量刷新失败不影响已完成的 partition
