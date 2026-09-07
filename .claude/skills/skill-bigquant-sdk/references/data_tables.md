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

### cn_stock_shares（股本信息）

每日股本结构，配合收盘价可计算总市值（total_shares × close）。

| 字段 | 类型 | 描述 |
|------|------|------|
| date | timestamp[ns] | 日期 |
| instrument | string | 证券代码 |
| total_shares | double | 总股本 |
| a_float_shares | double | 流通 A 股 |
| free_float_shares | double | 自由流通股 |
| total_float_shares | double | 流通股合计 |

主键：`(instrument, date)`

### cn_stock_valuation（估值指标）

每日估值指标，数据源按 TTM/动态/静态口径现成算好，作为原始事实入库（勿自行用财报重算——报告期对齐逻辑复杂）。

| 字段 | 类型 | 公式 |
|------|------|------|
| total_market_cap | DOUBLE | 总市值 = 当日收盘价×当日总股本 |
| float_market_cap | DOUBLE | 流通市值 |
| dividend_yield_ratio | DOUBLE | 股息率 = 过去一年分红总额/当日总股本 |
| pe_ttm | DOUBLE | 市盈率TTM = 当日总市值/归母净利润TTM |
| pe_leading | DOUBLE | 动态市盈率 = 当日总市值/最新一期归母净利润×n（1季报n=4/1, 2季报=4/2, 3季报=4/3, 4季报=1） |
| pe_trailing | DOUBLE | 静态市盈率 = 当日总市值/最新一期年报归母净利润 |
| pb | DOUBLE | 市净率 = 当日总市值/最新一期所有者权益 |
| ps_ttm | DOUBLE | 市销率TTM |
| ps_leading | DOUBLE | 动态市销率 |
| ps_trailing | DOUBLE | 市销率（最新年报） |
| pcf_net_ttm | DOUBLE | 市现率(净额TTM) |
| pcf_net_leading | DOUBLE | 市现率(净额动态) |
| pcf_op_ttm | DOUBLE | 市现率(经营TTM) |
| pcf_op_leading | DOUBLE | 市现率(经营动态) |

主键：`(instrument, date)` | 频率：日级

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

### cn_stock_moneyflow（A股资金流向·逐日）

个股逐日资金流向（按挂单额分 超大单/大单/中单/小单 × 买卖方向 × 主动/被动），
用于主力资金动向、筹码博弈、资金流因子研究。

**档位划分（挂单额）**：超大单 >100 万元；大单 20万~100万元；中单 4万~20万元；小单 <4 万元。
**主/被动定义**：主动 = 以对手价成交（吃单，追价方）；被动 = 以本方挂单价成交（被吃，让价方）。

| 字段 | 类型 | 描述 |
|------|------|------|
| date | timestamp[ns] | 日期 |
| instrument | string | 证券代码 |
| active_buy_volume_large | double | 主动买入量（超大单） |
| passive_buy_volume_large | double | 被动买入量（超大单） |
| active_sell_volume_large | double | 主动卖出量（超大单） |
| passive_sell_volume_large | double | 被动卖出量（超大单） |
| active_buy_amount_large | double | 主动买入额（超大单） |
| passive_buy_amount_large | double | 被动买入额（超大单） |
| active_sell_amount_large | double | 主动卖出额（超大单） |
| passive_sell_amount_large | double | 被动卖出额（超大单） |
| active_buy_volume_big | double | 主动买入量（大单） |
| passive_buy_volume_big | double | 被动买入量（大单） |
| active_sell_volume_big | double | 主动卖出量（大单） |
| passive_sell_volume_big | double | 被动卖出量（大单） |
| active_buy_amount_big | double | 主动买入额（大单） |
| passive_buy_amount_big | double | 被动买入额（大单） |
| active_sell_amount_big | double | 主动卖出额（大单） |
| passive_sell_amount_big | double | 被动卖出额（大单） |
| active_buy_volume_mid | double | 主动买入量（中单） |
| passive_buy_volume_mid | double | 被动买入量（中单） |
| active_sell_volume_mid | double | 主动卖出量（中单） |
| passive_sell_volume_mid | double | 被动卖出量（中单） |
| active_buy_amount_mid | double | 主动买入额（中单） |
| passive_buy_amount_mid | double | 被动买入额（中单） |
| active_sell_amount_mid | double | 主动卖出额（中单） |
| passive_sell_amount_mid | double | 被动卖出额（中单） |
| active_buy_volume_small | double | 主动买入量（小单） |
| passive_buy_volume_small | double | 被动买入量（小单） |
| active_sell_volume_small | double | 主动卖出量（小单） |
| passive_sell_volume_small | double | 被动卖出量（小单） |
| active_buy_amount_small | double | 主动买入额（小单） |
| passive_buy_amount_small | double | 被动买入额（小单） |
| active_sell_amount_small | double | 主动卖出额（小单） |
| passive_sell_amount_small | double | 被动卖出额（小单） |

主键：`(date, instrument)` | 频率：日线 | 命名速记：`{主动/被动}_{买/卖}_{额/量}_{档}`

> ⚠ **该表实际字段远超本节列出的 32 个基础列**（还含 全量 all / 主力 main 档、净额 net、
> 流入流出净流 inflow/outflow/netflow、比率 rate、占比 proportion 等 288+ 资金列）。
> **拉取时必须显式 SELECT 本节列出的 34 列**，禁止 `SELECT *`（按单元格计费白烧配额）。
> 列清单即本节 34 行；如需 all/main/rate 等扩展列，另行在 SQL 中显式点名并补记本节。

---

### hf_alpha_fzzq（方正证券高频因子）

方正证券研究的高频 alpha 因子（花隐林间系列），个股逐日。按注释区分"最终因子"与"中间因子"
（中间因子为构造最终因子的分步产出）。字段名为 alpha_91xxx；带 `:1` 后缀的同名因子为另一口径/变体。

⚠ 拉取时显式 SELECT 需用的 alpha 列（此表列较多，实际含 5x+ 因子列），禁 `SELECT *`——先查
本表所需因子清单再拉（见 SKILL.md 列拉取铁律）。

| 字段 | 类型 | 描述 |
|------|------|------|
| date | timestamp[ns] | 日期 |
| instrument | string | 股票代码 |
| alpha_91001 | double | 花隐林间【最终因子】 |
| alpha_91002 | double | 朝没晨雾【中间因子】 |
| alpha_91003 | double | 午蔽古木【中间因子】 |
| alpha_91004 | double | 夜眠霜露【中间因子】 |
| alpha_91005 | double | 日度朝没晨雾【中间因子】 |
| alpha_91006 | double | 日度午蔽古木【中间因子】 |
| alpha_91007 | double | 适度冒险【最终因子】 |
| alpha_91008 | double | 月耀眼波动【中间因子】 |
| alpha_91009 | double | 月耀眼收益【中间因子】 |
| alpha_91010 | double | 适度日耀眼波动率【中间因子】 |
| alpha_91011 | double | 适度日耀眼收益率【中间因子】 |
| alpha_91012 | double | 云开雾散【最终因子】 |
| alpha_91013 | double | 修正模糊价差【中间因子】 |
| alpha_91014 | double | 月模糊关联度【中间因子】 |
| alpha_91015 | double | 月模糊金额比【中间因子】 |
| alpha_91016 | double | 日模糊关联度【中间因子】 |
| alpha_91017 | double | 日模糊金额比【中间因子】 |
| alpha_91018 | double | 勇攀高峰【最终因子】 |
| alpha_91019 | double | 灾后重建【最终因子】 |
| alpha_91020 | double | 日勇攀高峰【中间因子】 |
| alpha_91021 | double | 日灾后重建【中间因子】 |
| alpha_91022 | double | 球队硬币【最终因子】 |
| alpha_91023 | double | 修正隔夜翻转【中间因子】 |
| alpha_91024 | double | 修正日间翻转【中间因子】 |
| alpha_91025 | double | 修正日内翻转【中间因子】 |
| alpha_91026 | double | （描述缺失） |
| alpha_91027 | double | 飞蛾扑火【最终因子】 |
| alpha_91028 | double | 月跳跃度【中间因子】 |
| alpha_91038 | double | 成交量博弈【中间因子】 |
| alpha_91039 | double | 相对位置博弈【中间因子】 |
| alpha_91040 | double | 波动率博弈【中间因子】 |
| alpha_91041 | double | 多空博弈【最终因子】 |
| alpha_91042 | double | （描述缺失） |
| alpha_91043 | double | （描述缺失） |
| alpha_91044 | double | （描述缺失） |
| alpha_91028:1 | double | （:1 = 同名因子另一变体） |
| alpha_91038:1 | double | 同上 |
| alpha_91039:1 | double | 同上 |
| alpha_91040:1 | double | 同上 |
| alpha_91041:1 | double | 同上 |

主键：`(date, instrument)` | 频率：日线

---

### cn_stock_index_component（指数成分股）

各宽基指数的成分股列表，用于成分股数据研究（如按指数成分股批量拉取行情）。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 指数代码 |
| name | string | 指数简称 |
| member_code | string | 成分股代码 |
| member_name | string | 成分股简称 |
| date | timestamp[ns] | 日期 |

### cn_stock_index_bar1d（股票指数日线）

宽基指数日线行情，可用于指数择时、regime 判断、大类资产配置研究。

| 字段 | 类型 | 描述 |
|------|------|------|
| instrument | string | 指数代码 |
| name | string | 指数简称 |
| pre_close | double | 昨收盘价 |
| open | double | 开盘价 |
| high | double | 最高价 |
| low | double | 最低价 |
| close | double | 收盘价 |
| volume | int64 | 成交量 |
| amount | double | 成交额 |
| change | double | 涨跌 |
| change_ratio | double | 涨跌幅 |
| date | timestamp[ns] | 日期 |
| turn | double | 换手率 |

主键：`(instrument, date)` | 频率：日线

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
