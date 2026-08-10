# BigQuant SDK API Reference

## DataSource 统一接口（推荐）

```python
from bigquant.dai import DataSource

DataSource('table_id').read(
    instruments=None,    # list[str] 合约代码列表，None=全市场
    start_date=None,     # str yyyy-mm-dd 开始日期
    end_date=None,       # str yyyy-mm-dd 结束日期
    fields=None,         # list[str] 字段列表，None=全字段
) -> pd.DataFrame
```

## dai.query SQL 接口

```python
import bigquant

result = bigquant.dai.query(
    sql="SELECT ... FROM table WHERE ...",
    udf_list=[],           # list[DaiUDF] 自定义函数
    full_db_scan=False,    # bool 是否允许全表扫描
    filters={},            # dict 分区过滤 {"column": ["val1"]}
    bind_relations=None,   # dict 绑定本地 DataFrame
    params=None,           # dict 查询参数
    compression=False,     # bool 字符串压缩
    resource_spec_id="D0", # str 资源规格 (D0=免费1C6G)
    space_id=None,         # str AIStudio 空间 ID
)
df = result.df()  # -> pd.DataFrame
```

### 资源规格

| 规格 | CPU | 内存 | 说明 |
|------|-----|------|------|
| D0 | 1C | 6G | 免费（默认，适合小数据量） |
| D1 | 2C | 12G | 付费 |
| D2 | 4C | 24G | 付费 |

## daiUDF 自定义函数

```python
from bigquant.dai import DaiUDF

def my_func(values):
    return values * 1.5

result = bigquant.dai.query(
    sql="SELECT date, instrument, my_func(close) as custom_val FROM cn_stock_bar1d ...",
    udf_list=[DaiUDF(name="my_func", function=my_func, return_type="DOUBLE")]
)
```

## DataSource 数据源读写（BDB 格式）

### 读取

```python
ds = bigquant.dai.DataSource("datasource_id")
df = ds.read_bdb(
    as_type=pd.DataFrame,
    partition_filter={"date": ("2024-01-01", "2024-12-31")},
    columns=["date", "instrument", "close"]
)
```

### 写入

```python
ds = bigquant.dai.DataSource.write_bdb(
    data=df,
    id="my_datasource",
    partitioning=["date"],
    indexes=["instrument"],
    unique_together=["date", "instrument"],
    on_duplicates="last",
    overwrite=True
)
```

## 模拟交易数据查询

```python
import bigquant

# 策略列表
result = bigquant.papertrading.list(page=1, size=10)

# 获取策略
strategy = bigquant.papertrading.get("strategy_id")

# 持仓
positions = strategy.get_positions()

# 绩效
perf = strategy.get_performances(
    fields=["trading_day", "cumulative_return", "max_drawdown"]
)
```

## 参考链接

- DAI 数据管理 API：https://eu.bigquant.com/wiki/doc/obft7eKPjB
- 数据接口文档：https://bigquant.com/wiki/doc/OuCI5yqk9u
- 期货日线数据表：https://bigquant.com/data/datasources/cn_future_bar1d
- 股票日线数据表：https://bigquant.com/data/datasources/cn_stock_bar1d
