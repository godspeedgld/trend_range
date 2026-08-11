# BigQuant 数据表目录

所有数据通过 `dai.query(sql).df()` 获取。SQL 表名 = 本文件各节标题。

---

## 通用数据

### all_trading_days（交易日历）

| 字段 | 类型 | 描述 |
|------|------|------|
| date | timestamp[ns] | 日期 |
| market_code | string | 市场代码（如 CN） |

本地仓库以此表的 date 范围为基准，确保不超出最新交易日。

---

## 股票数据

### cn_stock_bar1d（A股后复权日线）

起始 2005-01-04，每交易日更新。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 证券代码 |
| date | timestamp[ns] | 日期 |
| name | string | 证券简称 |
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

主键：`(instrument, date)`

### cn_stock_bar1m（A股1分钟K线）

适合逐只股票提取分钟数据。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 证券代码 |
| date | timestamp[ns] | 日期时间（分钟级） |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交金额 |
| adjust_factor | double | 累计后复权因子 |

主键：`(instrument, date)` | 起始：2005-01-04

### cn_stock_bar1m_c（A股1分钟K线截面）

**字段与 `cn_stock_bar1m` 完全相同**，区别在于存储方式：按时间截面（按月）存储，提取某段时间全市场分钟数据效率更高。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 证券代码 |
| date | timestamp[ns] | 日期时间（分钟级） |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交金额 |
| adjust_factor | double | 累计后复权因子 |

主键：`(instrument, date)` | 起始：2005-01-04

---

## 期货数据

### cn_future_bar1d（期货日线）

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 合约代码 |
| date | timestamp[ns] | 日期 |
| trading_code | string | 交易代码 |
| product_code | string | 品种代码（如 AU） |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| settle | double | 结算价 |
| volume | int64 | 成交量 |
| amount | double | 成交金额 |
| open_interest | int32 | 持仓量 |
| upper_limit | double | 涨停价 |
| lower_limit | double | 跌停价 |

主键：`(instrument, date)` | 注意：无 `pre_close`/`pre_settle`

### cn_future_bar1d_adjust（期货复权日线）

在 `cn_future_bar1d` 基础上增加 2 个字段：

| pre_close | double | 前收盘价 |
| adjust_factor | double | 累积前复权因子 |

### cn_future_bar1m（期货1分钟K线）

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 合约代码 |
| date | timestamp[ns] | 日期时间（分钟级） |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交额 |
| open_interest | int32 | 持仓量 |
| product_code | string | 品种代码 |

主键：`(instrument, date)` | 起始：2005-01-01
注意：无 `adjust_factor`（区别于股票分钟线）

### cn_future_bar1m_c（期货1分钟K线截面）

**字段与 `cn_future_bar1m` 完全相同**，按时间截面存储（多标的+短时间跨度场景效率更高）。

---

## 基金数据

### cn_fund_bar1d（基金后复权日线）

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 基金代码 |
| date | timestamp[ns] | 日期 |
| name | string | 基金名称 |
| open | double | 开盘价（后复权） |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价（后复权） |
| pre_close | double | 前收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交额 |
| turn | double | 换手率 |
| deal_number | int32 | 交易笔数 |
| change_ratio | double | 涨跌幅 |
| upper_limit | double | 涨停价 |
| lower_limit | double | 跌停价 |
| iopv | double | 参考净值 (IOPV) |
| adjust_factor | double | 累积后复权因子 |

主键：`(instrument, date)` | 区别于股票：多了 `iopv` 字段

### cn_fund_real_bar1d（基金未复权日线）

实际成交价（未复权），字段与 `cn_fund_bar1d` 相同但 `adjust_factor` 为原始值、价格不做复权调整。适用于需要真实成交价的场景（如回测按实际价格撮合）。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 基金代码（含交易所后缀，如 `510300.SH`） |
| date | timestamp[ns] | 日期 |
| name | string | 基金名称 |
| open | double | 开盘价（未复权） |
| high | double | 最高价（未复权） |
| low | double | 最低价（未复权） |
| close | double | 收盘价（未复权） |
| pre_close | double | 前收盘价（未复权） |
| volume | int64 | 成交量 |
| amount | double | 成交额 |
| turn | double | 换手率 |
| deal_number | int32 | 交易笔数 |
| change_ratio | double | 涨跌幅 |
| upper_limit | double | 涨停价 |
| lower_limit | double | 跌停价 |
| iopv | double | 参考净值 (IOPV) |
| adjust_factor | double | 复权因子 |

主键：`(instrument, date)` | 代码格式：`510300.SH`（需带交易所后缀）

### cn_fund_bar1m（基金分钟数据）

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 基金代码 |
| date | timestamp[ns] | 日期时间（分钟级） |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交额 |
| iopv | double | 实时净值 (IOPV) |
| adjust_factor | double | 累积后复权因子 |

主键：`(instrument, date)` | 区别于股票分钟：多了 `iopv`，少了 `name`/`turn` 等日线字段

---

## 其他表

### cn_stock_chips_distribution（筹码分布）

> ⚠️ 表结构待验证：BigQuant 文档页面未索引，无法抓取完整字段。
> 已知字段：`instrument`(string), `date`(timestamp[ns])。
> 使用前建议通过 `dai.query("SELECT * FROM cn_stock_chips_distribution LIMIT 1").df().columns` 确认。

### cn_stock_prefactors_community（预计算因子社区版）

包含常用技术指标因子（均线、MACD、RSI 等），具体字段见 BigQuant 文档。

---

## 合约代码速查

### 期货

格式：`{品种代码}{年份}{月份}.{交易所}`

| 品种 | 代码 | 交易所 | 后缀 | 示例 |
|------|------|--------|------|------|
| 沪深300股指 | IF | 中金所 | CFE | IF2506.CFX |
| 上证50股指 | IH | 中金所 | CFE | IH2506.CFX |
| 中证500股指 | IC | 中金所 | CFE | IC2506.CFX |
| 中证1000股指 | IM | 中金所 | CFE | IM2506.CFX |
| 黄金 | AU | 上期所 | SHF | AU2506.SHF |
| 螺纹钢 | HC | 上期所 | SHF | HC2506.SHF |
| 铜 | CU | 上期所 | SHF | CU2506.SHF |
| 白银 | AG | 上期所 | SHF | AG2506.SHF |
| 铁矿石 | I | 大商所 | DCE | I2506.DCE |
| 焦炭 | J | 大商所 | DCE | J2506.DCE |
| 原油 | SC | 上期能源 | INE | SC2506.INE |
| 棉花 | CF | 郑商所 | CZC | CF2506.CZC |
| 苹果 | AP | 郑商所 | CZC | AP2506.CZC |

交易所后缀速查：`SHF`(上期所) `DCE`(大商所) `CZC`(郑商所) `CFE`(中金所) `INE`(上期能源) `GFE`(广期所)

主力合约：`{品种}_DOMINANT.{交易所}`，如 `AU_DOMINANT.SHF`

### A股

格式：`{6位代码}.{交易所}`

| 交易所 | 后缀 | 示例 |
|--------|------|------|
| 深交所 | .SZ | 000001.SZ |
| 上交所 | .SH | 600000.SH |
| 北交所 | .BJ | 830799.BJ |
