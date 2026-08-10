# BigQuant 数据表目录

所有表均通过 `DataSource('table_id').read(...)` 访问。SQL 表名用于 `dai.query()`。

---

## 期货数据

### bar1d_CN_FUTURE（期货日线行情）

SQL 表名：`cn_future_bar1d`

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 合约代码 |
| date | timestamp[ns] | 日期 |
| trading_code | string | 交易代码 |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| pre_close | double | 昨收盘 |
| pre_settle | double | 昨结算 |
| settle | double | 结算价 |
| volume | int64 | 成交量 |
| amount | double | 成交金额 |
| open_interest | int32 | 持仓量 |
| upper_limit | double | 涨停价 |
| lower_limit | double | 跌停价 |
| product_code | string | 品种代码 |

```python
# 拉取黄金期货日线
df = DataSource('bar1d_CN_FUTURE').read(
    instruments=['AU2506.SHF'],
    start_date='2024-01-01',
    end_date='2025-06-30'
)
```

### bar1d_CN_FUTURE_adjust（期货复权日线）

SQL 表名：`cn_future_bar1d_adjust`

在 `cn_future_bar1d` 基础上增加 `adjust_factor`（累积前复权因子）字段。

```python
df = DataSource('bar1d_CN_FUTURE_adjust').read(
    instruments=['AU_DOMINANT.SHF'],
    start_date='2024-01-01',
    end_date='2025-06-30'
)
```

---

## 股票数据

### bar1d_CN_STOCK_A（A股后复权日线）

SQL 表名：`cn_stock_bar1d`

起始：2005-01-04，每交易日更新。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 证券代码 |
| date | timestamp | 日期 |
| open | double | 开盘价（后复权） |
| high | double | 最高价（后复权） |
| low | double | 最低价（后复权） |
| close | double | 收盘价（后复权） |
| pre_close | double | 昨收盘价（后复权） |
| volume | int64 | 成交量 |
| amount | double | 成交金额 |
| turn | double | 换手率 |
| deal_number | int32 | 成交笔数 |
| change_ratio | double | 涨跌幅 |
| adjust_factor | double | 累计后复权因子 |
| upper_limit | double | 涨停价 |
| lower_limit | double | 跌停价 |
| name | string | 证券简称 |

```python
df = DataSource('bar1d_CN_STOCK_A').read(
    instruments=['000001.SZ', '600000.SH'],
    start_date='2024-01-01',
    end_date='2025-01-01',
    fields=['close', 'open', 'high', 'low', 'volume']
)
```

### bar1d_CN_STOCK_A_adjust（A股前复权日线）

含 `adjust_factor` 前复权因子，其他字段同上。

---

## 指数数据

### bar1d_CN_INDEX（指数日线）

```python
df = DataSource('bar1d_CN_INDEX').read(
    instruments=['000300.SH', '000905.SH'],  # 沪深300, 中证500
    start_date='2024-01-01',
    end_date='2025-06-30'
)
```

---

## 因子数据

### cn_stock_prefactors_community（预计算因子社区版）

```python
df = DataSource('cn_stock_prefactors_community').read(
    start_date='2024-01-01',
    end_date='2025-06-30'
)
```

---

## 期货合约代码速查

格式：`{品种代码}{年份}{月份}.{交易所}`

| 品种 | 代码 | 交易所 | 示例 |
|------|------|--------|------|
| 沪深300股指 | IF | CFFEX | IF2506.CFX |
| 上证50股指 | IH | CFFEX | IH2506.CFX |
| 中证500股指 | IC | CFFEX | IC2506.CFX |
| 中证1000股指 | IM | CFFEX | IM2506.CFX |
| 黄金 | AU | SHFE | AU2506.SHF |
| 螺纹钢 | RB/HC | SHFE | HC2506.SHF |
| 铁矿石 | I | DCE | I2506.DCE |
| 焦炭 | J | DCE | J2506.DCE |
| 原油 | SC | INE | SC2506.INE |
| 铜 | CU | SHFE | CU2506.SHF |
| 白银 | AG | SHFE | AG2506.SHF |

主力合约：`{品种}_DOMINANT.{交易所}`，如 `AU_DOMINANT.SHF`

## A股代码速查

格式：`{6位代码}.{交易所}`

| 交易所 | 后缀 | 示例 |
|--------|------|------|
| 深交所 | .SZ | 000001.SZ |
| 上交所 | .SH | 600000.SH |
| 北交所 | .BJ | 830799.BJ |
