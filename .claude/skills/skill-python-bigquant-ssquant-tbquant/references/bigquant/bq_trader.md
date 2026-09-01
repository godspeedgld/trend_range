# Bigtrader交易引擎API

> 来源：https://bigquant.com/wiki/doc/nxDOuIdhm2（本地 HTML 快照转换；远程为最新版本，如需更新访问链接）

Bigtrader交易引擎API


### 简介
BigTrader 是 BigQuant 推出的专业级量化交易引擎，主要用于策略在历史数据中回测撮合和实盘交易。采用 C++ 核心实现，提供 Python API 接口和回调函数。

#### 核心特性
- **全市场覆盖**：股票、基金、期货、可转债、指数、期权、两融等
- **多场景适配**：回测、模拟交易、仿真交易、实盘交易、绩效分析
- **多频率支持**：日频、分钟级、Tick 级、逐笔交易（Tick2）
- 同一套代码可用于回测、模拟和实盘，无需修改

### 交易引擎运行逻辑
BigQuant 回测引擎为时间+数据驱动回测引擎。设定好 K 线频率后，引擎按频率逐根读取数据。每根 K 线时间运行一次回调 handle_data，当前 K 线下单操作会在下一根 K 线开始撮合成交。

回测运行流程：

```
initialize()                    ← 仅启动时调用一次
│
└─ 每个交易日循环 ──────────────────
    │
    ├─ before_trading_start()   ← 每日盘前处理函数
    │
    ├─ handle_data/handle_tick  ← 每根K线或每个Tick触发
    │   ├─ handle_order()       ← 委托状态变化时触发
    │   └─ handle_trade()       ← 有成交时触发
    │
    └─ after_trading()          ← 盘后处理
```

### 交易所代码后缀
| **交易所** | **代码后缀** | **示例** | **说明** |
|---|---|---|---|
| 上交所 SSE | SH | [600000.SH](http://600000.sh/)、[510050.SH](http://510050.sh/)、[000001.SH](http://000001.sh/) | 股票、基金、可转债、指数 |
| 深交所 SZSE | SZ | [000001.SZ](http://000001.sz/)、[159919.SZ](http://159919.sz/)、[399001.SZ](http://399001.sz/) | 股票、基金、可转债、指数 |
| 上交所 SSE | SHO | 10000001.SHO | ETF期权 |
| 深交所 SZSE | SZO | 90000001.SZO | ETF期权 |
| 北交所 BSE | BJ | [920099.BJ](http://920099.bj/) | 股票、指数 |
| 中金所 CFFEX | CFE | IF2501.CFE、T2503.CFE、IO2501-C-4300.CFE | 股指期货、国债期货、股指期权 |
| 上期所 SHFE | SHF | rb2505.SHF、cu2503.SHF、cu2503C65000.SHF | 期货和期货期权，小写+2位年+2位月 |
| 上能所 INE | INE | sc2505.INE、sc2505P400.INE | 期货和期货期权，小写+2位年+2位月 |
| 大商所 DCE | DCE | a2505.DCE、a2505-C-3400.DCE | 期货和期货期权，小写+2位年+2位月 |
| 郑商所 CZCE | CZC | SR505.CZC、SR505P5000.CZC | 期货和期货期权，大写+1位年+2位月 |
| 广期所 GFEX | GFE | si2505.GFE、si2505-C-10000.GFE | 期货和期货期权，小写+2位年+2位月 |

### 一个简单但完整的策略
```
from bigquant import bigtrader

def initialize(context: bigtrader.IContext):
    """策略初始函数，每次启动时调用一次"""
    context.security = context.instruments[0]

    # 设置股票交易费率
    context.set_commission(bigtrader.PerOrder(buy_cost=0.0003, sell_cost=0.0003, min_cost=5.0, tax_ratio=0.0005))

    # 设置期货交易费率
    context.set_commission(futures_commission=bigtrader.PerContract(cost={"rb": (2, 2, 1), "IF": (0.000023, 0.00015, 0.000023)}))

    # 设置期货保证金率
    context.set_margin_ratio("IF", 0.12)

    # 设置交易滑点
    context.set_slippage_value(slippage_type=2, slippage_value=0.001)

def before_trading_start(context: bigtrader.IContext, data: bigtrader.IBarData):
    """每日盘前处理函数"""
    # 高频回测时订阅Tick：context.subscribe(instruments)
    # 订阅Bar：context.subscribe_bar(instruments)
    pass

def handle_data(context: bigtrader.IContext, data: bigtrader.IBarData):
    """K线处理函数，每根K线时间调用一次"""
    if context.security not in context.portfolio.positions:
        rv = context.order(context.security, 1000)
        if rv < 0:
            context.logger.warning(f"{data.current_dt} order failed rv={rv},{context.get_error_msg(rv)}")
    else:
        rv = context.order(context.security, -800)
        if rv < 0:
            context.logger.warning(f"{data.current_dt} order failed rv={rv},{context.get_error_msg(rv)}")

def handle_trade(context: bigtrader.IContext, trade: bigtrader.ITradeData):
    """成交回报处理函数"""
    pass

performance = bigtrader.run(
    market=bigtrader.Market.CN_STOCK,
    frequency=bigtrader.Frequency.DAILY,
    start_date="2025-08-15",
    end_date="2025-10-15",
    capital_base=100000,
    instruments=["000001.SZ"],
    benchmark="000300.SH",
    initialize=initialize,
    before_trading_start=before_trading_start,
    handle_data=handle_data,
    handle_trade=handle_trade,
)
```

一个完整的策略，最主要就是在 handle_data 里实现调仓逻辑。若对某个对象或函数不了解，可使用 help(context) 或 help(pos_data) 等查看文档。

### bigtrader.run() 启动函数
```
performance = bigtrader.run(
    market=Market.CN_STOCK,            # Market 枚举，交易市场
    frequency=Frequency.DAILY,         # Frequency 枚举，K线频率
    start_date="2025-01-01",           # str，回测开始日期 "YYYY-MM-DD"
    end_date="2025-06-01",             # str，回测结束日期 "YYYY-MM-DD"
    capital_base=100000,               # float，初始资金
    instruments=None,                  # list[str]，标的代码列表
    initialize=initialize,             # 初始化回调函数
    before_trading_start=before_trading_start,  # 盘前回调函数
    handle_data=handle_data,           # K线回调函数
    handle_tick=handle_tick,           # L2Snapshot Tick快照行情回调函数
    handle_l2trade=handle_l2trade,     # L2Trade 逐笔成交行情回调函数
    handle_l2order=handle_l2order,     # L2Order 逐笔委托行情回调函数
    handle_order=handle_order,         # 委托回报回调函数
    handle_trade=handle_trade,         # 成交回报回调函数
    after_trading=after_trading,       # 盘后回调函数
    benchmark="000300.SH",             # str，基准代码
    account_type=AccountType.NONE,     # AccountType 枚举，账户类型（两融回测必须指定 AccountType.CREDIT）
    volume_limit=0.025,                # float，Bar撮合时单笔最大成交比例（分钟级回测建议设置为1.0）
    data=None,                         # any，用户数据，可在 context.data 中访问
    user_data=None,                    # Dict，用户自定义行情数据回测
    order_price_field_buy="open",      # str，Bar撮合买入成交参考价字段：open / close / vwap
    order_price_field_sell="close",    # str，Bar撮合卖出成交参考价字段：open / close / vwap
)
```

返回值：`performance`为回测绩效结果对象，包含收益曲线、交易记录等。

### 策略回调函数
#### initialize(context: bigtrader.IContext)
策略初始化函数，只触发一次。可在此函数中初始化变量、读取配置、设置交易费率、设置滑点等。

参数：context — 策略上下文对象

#### before_trading_start(context: bigtrader.IContext, data: bigtrader.IBarData)
盘前交易函数，每日盘前触发一次。可在此处理当日交易前的准备，如高频回测时订阅行情等。

参数：context — 策略上下文对象，data — 数据对象

#### handle_data(context: bigtrader.IContext, data: bigtrader.IBarData)
K 线行情通知函数，频率支持日线和N分钟。注册多个合约时，handle_data 会等待所有合约数据到齐后统一触发一次。

参数：context — 策略上下文对象，data — 数据对象（IBarData）

#### handle_tick(context: bigtrader.IContext, tick: bigtrader.ITickData)
Tick 快照行情通知函数，每个标的的行情有变化时触发。此函数的触发依赖于交易所实时行情推送。

参数：context — 策略上下文对象，tick — TickData 数据对象

#### handle_l2order(context: bigtrader.IContext, l2order: bigtrader.IL2OrderData)
L2Order 逐笔委托行情通知函数，每个标的的逐笔委托行情有变化时触发。

参数：context — 策略上下文对象，l2order — L2OrderData 数据对象

#### handle_l2trade(context: bigtrader.IContext, l2trade: bigtrader.IL2TradeData)
L2Trade 逐笔成交行情通知函数，每个标的的逐笔成交行情有变化时触发。

参数：context — 策略上下文对象，l2trade — L2TradeData 数据对象

#### handle_order(context: bigtrader.IContext, order: bigtrader.IOrderData)
委托回报通知函数，每个订单状态有变化时触发。

参数：context — 策略上下文对象，order — 委托数据对象（OrderData）

#### handle_trade(context: bigtrader.IContext, trade: bigtrader.ITradeData)
成交回报通知函数，有成交时触发。

参数：context — 策略上下文对象，trade — 成交数据对象（TradeData）

#### after_trading(context: bigtrader.IContext, data: bigtrader.IBarData)
盘后处理函数，每日盘后运行一次。适用于日终汇总与清理任务。

参数：context — 策略上下文对象，data — 数据对象

### context: bigtrader.IContext 对象
context 是策略的运行时上下文对象，每个回调函数都会接收 context 作为第一个参数。通过 context 提供的属性或接口，可以访问交易数据、下单、查询账户/持仓/委托/成交等。

#### context 的属性
| **属性** | **类型** | **说明** |
|---|---|---|
| instruments | list[str] | 策略标的代码列表（来自 bigtrader.run 的 instruments 参数） |
| portfolio | Portfolio | 组合对象，包含 cash、positions 等属性 |
| portfolio.cash | float | 可用现金 |
| portfolio.positions | dict[str, PositionData] | 当前持仓字典，key 为 instrument 代码 |
| user_store | dict | 持久化变量存储（模拟/实盘跨日保存） |
| logger | object | Python 日志对象 |
| data | object | 用户传入的自定义数据（bigtrader.run 时传入的 data 参数） |

#### 下单交易接口
所有下单函数返回 int 类型，小于 0 时表示下单失败，可使用 context.get_error_msg(ret_code) 获取错误信息。

##### context.order(instrument, order_qty, limit_price=None, order_type=None) -> int
标准下单接口。order_qty 为正买入，为负卖出。当指定 limit_price 时表示下限价单，报上交所股票市价单时，limit_price 为保护价并指定 order_type=bigtrader.OrderType.Market。

| **参数** | **类型** | **说明** |
|---|---|---|
| instrument | str | 标的代码，如 000001.SZ |
| order_qty | int | 委托数量，正数买入，负数卖出 |
| limit_price | float, optional | 限价，None 为市价 |
| order_type | OrderType, optional | 委托价格类型 |

##### context.order_target(instrument, target, limit_price=None, order_type=None) -> int
按目标数量下单。

##### context.order_target_percent(instrument, percent, limit_price=None, order_type=None) -> int
按目标百分比仓位下单。

##### context.order_target_value(instrument, value, limit_price=None, order_type=None) -> int
按目标市值下单。

##### context.order_value(instrument, value, limit_price=None, order_type=None) -> int
按金额下单。

##### context.order_percent(instrument, percent, limit_price=None, order_type=None) -> int
按账户百分比下单。

#### 期货/期权专用开平仓下单接口
| **函数** | **说明** |
|---|---|
| buy_open(instrument, order_qty, limit_price=None, order_type=None) | 买入开仓 |
| sell_open(instrument, order_qty, limit_price=None, order_type=None) | 卖出开仓 |
| buy_close(instrument, order_qty, limit_price=None, order_type=None) | 买入平仓 |
| sell_close(instrument, order_qty, limit_price=None, order_type=None) | 卖出平仓 |

注意：order_qty 应该为正，因为接口本身已包含买卖方向。

#### 两融专用交易接口
| **函数** | **说明** |
|---|---|
| margin_trade(instrument, order_qty, limit_price=None, order_type=None) | 两融交易 |
| margincash_open(instrument, order_qty, limit_price=None, order_type=None) | 融资买入 |
| margincash_close(instrument, order_qty, limit_price=None, order_type=None) | 卖券还款 |
| marginsec_open(instrument, order_qty, limit_price=None, order_type=None) | 融券卖出 |
| marginsec_close(instrument, order_qty, limit_price=None, order_type=None) | 买券还券 |
| marginsec_direct_refund(instrument, order_qty) | 直接还券 |
| margincash_direct_refund(value) | 直接还款 |

#### 撤单接口
##### context.cancel_order(order_param) -> int
撤销委托。order_param 可以是 order 对象、order_key 字符串或撤单请求。

##### context.cancel_all(instrument="") -> int
撤销所有委托。instrument 不为空时只撤销此 instrument 相关的所有委托。

#### 其它委托接口
##### context.exercise(instrument, order_qty) -> int
期权行权委托。

#### 查询类接口
| **函数** | **返回类型** | **说明** |
|---|---|---|
| get_trading_account() | FundData | 获取资金账户数据 |
| get_marginasset_data() | dict | 获取两融负债资产数据 |
| get_balance() | float | 总资金（可用资金 + 冻结资金） |
| get_available_cash() | float | 可用资金 |
| get_portfolio_value() | float | 总资产 |
| get_position(instrument, direction=None) | PositionData | 获取单个持仓 |
| get_positions() | dict[instrument, PositionData] | 获取全部持仓 |
| get_long_positions() | dict[instrument, PositionData] | 获取全部多头持仓 |
| get_short_positions() | dict[instrument, PositionData] | 获取全部空头持仓 |
| get_orders(instrument="") | list[OrderData] | 获取当日委托 |
| get_open_orders(instrument="") | list[OrderData] | 获取未成交委托 |
| get_trades(instrument="") | list[TradeData] | 获取当日成交 |
| get_last_price(instrument) | float | 获取最新价 |
| get_contract(instrument) | ContractData | 获取合约信息 |
| get_trading_day() | str | 获取当前交易日 (YYYYmmdd) |

注意：获取期货多头/空头持仓时，应使用 context.get_position(instr, PosiDirection.LONG) 或 .SHORT，否则获取出来的是包括多空持仓的复合对象。

#### 配置类接口
##### set_commission — 设置费率
设置股票费率（回测基金时可将 tax_ratio 设置为 0 表示无印花税）：

```
context.set_commission(PerOrder(buy_cost=0.0003, sell_cost=0.0003, min_cost=5, tax_ratio=0.0005))
```

设置期货费率：

```
context.set_commission(futures_commission=PerContract(cost={"rb": (2, 2, 1), "IF": (0.000023, 0.00015, 0.000023)}))
```

- 股票使用`PerOrder`：`buy_cost`买入费率，`sell_cost`卖出费率，`min_cost`最少费用，`tax_ratio`印花税率
- 期货使用`PerContract`：字典 Key 为品种代码，值为 Tuple (开仓费率, 平仓费率, 平今费率)，费率 < 0.1 时按金额收取，否则按手数收取设置保证金比例：

```
context.set_margin_ratio("rb", 0.1)
```

##### add_account — 添加更多回测账号
用于多资产回测，如股票 + 期货、ETF期权 + 股票 组合回测：

| **场景** | **使用** | **说明** |
|---|---|---|
| 股票+期货 | add_account(AccountType.FUTURE, capital_base=1e6) | run() 指定 market=Market.CN_STOCK，策略中再添加期货账号 |
| 期权+股票 | add_account(AccountType.STOCK, capital_base=1e6) | run() 指定 market=Market.CN_STOCK_OPTION，策略中再添加股票账号 |

注意：交易期货+期货期权或股指期权时，不需要额外账号，只需在 run() 中指定 market=Market.CN_FUTURE_OPTION。

##### set_slippage — 设置撮合滑点
```
# 固定价格撮合模型，无条件按策略指定的价格成交，一般用于交割单回测

context.set_slippage_name("fixed")

# 固定滑点值

context.set_slippage_value(slippage_type=1, slippage_value=1.0)

# 设置百分比滑点

context.set_slippage_value(slippage_type=2, slippage_value=0.005)
```

- `slippage_type=1`：固定滑点
- `slippage_type=2`：滑点百分比

##### is_backtest_mode() -> bool
判断是否为回测模式。

##### get_error_msg(error_id: int) -> str
传入错误 ID 获取错误信息。

#### 行情订阅接口
高频回测时一定要在每日盘前处理函数中订阅当日要交易的代码列表，包括策略新选出来的代码和持仓代码列表。Tick 回测时调用 subscribe，分钟回测调用 subscribe_bar。

订阅 Level2 逐笔数据时，需要将 subscribe_flags 使用 XOR 指定多个标志位，比如：

```
subscribe_flags=SubscribeFlag.L2Snapshot | SubscribeFlag.L2Trade | SubscribeFlag.L2Order
```

| **函数** | **说明** |
|---|---|
| subscribe(instruments, subscribe_flags=SubscribeFlag.DEFAULT) | 订阅 Tick 数据 |
| subscribe_bar(instruments, period="1m") | 订阅分钟 Bar 数据 |
| unsubscribe(instruments) | 取消订阅 |

### data: bigtrader.IBarData 数据对象
在 handle_data 回调中通过 data 参数访问 K 线数据。注意，data 不是一个 K 线数据，而是一个可以访问 K 线数据的对象。

#### data 属性
| **属性** | **类型** | **说明** |
|---|---|---|
| current_dt | datetime | 当前 Bar 的日期时间 |
| trading_day_dt | datetime | 当前交易日 |

#### data 接口
##### data.current(instrument, field) -> float | int | str
获取当前 Bar 某字段值。

| **参数** | **类型** | **说明** |
|---|---|---|
| instrument | str | 标的代码，如 000001.SZ |
| field | str | K 线字段：open, close, high, low, volume, amount, name 等 |

##### data.history(instrument, fields, count, frequency, expect_ndarray=True)
获取历史 N 根 Bar 的值。

| **参数** | **类型** | **说明** |
|---|---|---|
| instrument | str | 标的代码 |
| fields | str 或 list[str] | 字段名或字段列表 |
| count | int | 历史 Bar 数量 |
| frequency | str | 频率：1d（日线）或 1m（分钟线） |
| expect_ndarray | bool | True 时返回 numpy array |

##### data.get_daily_value(instrument, field) -> float | int | str
获取日 K 线的值（一般用于高频回测时需要访问日K线数据的场景）。

| **参数** | **类型** | **说明** |
|---|---|---|
| instrument | str | 标的代码 |
| field | str | K 线字段：open, close, volume 等 |

### 一些交易说明
- 高频回测需要在每日盘前处理函数中使用`context.subscribe`或`context.subscribe_bar`订阅当日要交易的代码列表，订阅的代码列表中，除了你新选出的股票外，若持仓里的股票要交易，也需要一并订阅
- 不要在策略函数中阻塞等待接口执行结果，如下单后等待成交或撤单后等待订单状态发生变更。因为底层只有一个事件队列，在策略函数回调完成后再从队列中处理下一个事件
- 实验选项：设置股票T+0交易：`context.set_stock_t1(0)`

#### 融资融券回测
- run 的参数中`market=Market.CN_STOCK`，额外再指定`account_type=AccountType.CREDIT`
- 当日融的券当日不能还
- 直接还券时，可以使用当日买入的券还（不受T+1限制）
- 系统为简便处理，每日直接扣除负债的利息

#### 期权回测
- run 的参数中`market=Market.CN_STOCK_OPTION`或`CN_FUTURE_OPTION`
- run 的参数中`instruments`需指定期权的标的代码，而不是期权交易代码
- ETF期权需要单独的资金账号，股指期权和期货期权则使用期货账号交易

#### 自定义数据回测
- run 的参数中指定`user_data`
- 其中 key 可以是`"trading_days"`,`"basic_info"`,`"bar1d"`,`"bar1m"`,`"tick"`
- 其中 val 则是 pandas DataFrame 格式，df 中各字段名参考 dai 数据平台中的各表的字段

#### 合约代码到期处理
- **股票退市**：按退市价格自动平仓，释放资金=持仓市值，生成一条成交记录，成交类型=`TradeType.ExpireClose`
- **期货退市**：按退市价格自动平仓，释放资金=保证金，生成一条成交记录，成交类型=`TradeType.ExpireClose`
- **期权退市**：权利仓实值时自动行权否则放弃，义务仓实值时自动被行权否则放弃并释放保证金

#### 分红送股处理
按 cn_stock_dividend 表的分红送信息对持仓进行处理。对于配股时则使用 adjust_factor 变化比例对持仓进行处理。

股息红利税的计算：回测时简便处理，直接按 20% 的税率计算。注意，转股因为不属于利润分配，因此无需缴红利税，而送股作为股息红利所得，因此需要缴纳。

#### 变量持久化对象 context.user_store 使用说明
- 建议在`initialize()`函数里使用`context.user_store.init_once(**kwargs)`进行变量初始化，因为回测时`initialize`只会被调用一次，而模拟盘每天运行时都会调用一次，`init_once`能保证变量只初始化一次
- user_store 对象可以像字典一样使用
- user_store 对象里存储的 kv 必须是可被 jsonalize 的，且存储大小有限

#### 获取上一次委托请求时的本地唯一编号
使用 context.get_last_order_key() -> str

因为下单接口返回的是 int 类型表示是否发单成功（发单成功不代表委托成功，只代表订单正常发送出去），可以使用此接口唯一编号，便于和未来的委托回报和成交回报关联。

---

### 数据结构定义
#### FundData（资金数据）
| **字段** | **类型** | **说明** |
|---|---|---|
| account_id | str | 资金账户 |
| account_type | AccountType | 账户类型 |
| balance | float | 总资金 |
| available | float | 可用资金 |
| frozen_cash | float | 冻结资金 |
| portfolio_value | float | 总资产 |
| total_market_value | float | 总市值 |
| total_margin | float | 总保证金 |
| commission | float | 当日总交易费用 |
| positions_pnl | float | 持仓盈亏 |

#### PositionData（持仓数据）
| **字段** | **类型** | **说明** |
|---|---|---|
| account_id | str | 资金账户 |
| instrument | str | 内部代码 |
| posi_direction | PosiDirection | 持仓方向：'1'-LONG多头，'2'-SHORT空头 |
| current_qty | int | 持仓数量 |
| avail_qty | int | 可用数量 |
| today_qty | int | 今仓数量 |
| cost_price | float | 持仓均价 |
| last_price | float | 最新价 |
| market_value | float | 市值 |
| margin | float | 保证金占用 |
| position_pnl | float | 持仓盈亏（按持仓均价计算） |
| open_date | int | 开仓日期 (YYYYmmdd) |
| open_price | float | 开仓均价 |
| liability | float | 两融负债 |
| financing_qty | int | 融资持仓数量 |
| financing_avail_qty | int | 融资持仓可平数量 |

#### OrderData（委托数据）
| **字段** | **类型** | **说明** |
|---|---|---|
| account_id | str | 资金账户 |
| instrument | str | 内部代码 |
| direction | Direction | 方向：'1'-BUY，'2'-SELL |
| offset_flag | OffsetFlag | 开平标志：'0'-OPEN，'1'-CLOSE，'2'-CLOSETODAY |
| order_type | OrderType | 委托价格类型：'0'-限价，'U'-市价五档即成剩撤 |
| order_qty | int | 委托数量 |
| filled_qty | int | 成交数量 |
| order_price | float | 委托价格 |
| order_status | OrderStatus | 委托状态 |
| order_sysid | str | 系统报单编号 |
| order_key | str | 本地唯一标识 |
| insert_date | int | 报单日期 (YYYYmmdd) |
| order_time | int | 报单时间 (HHMMSSmmm) |
| trading_day | int | 交易日 (YYYYmmdd) |
| status_msg | str | 报单状态消息 |

#### TradeData（成交数据）
| **字段** | **类型** | **说明** |
|---|---|---|
| account_id | str | 资金账户 |
| instrument | str | 内部代码 |
| direction | Direction | 方向 |
| offset_flag | OffsetFlag | 开平标志 |
| trade_type | TradeType | 成交类型 |
| filled_qty | int | 成交数量 |
| filled_price | float | 成交价格 |
| filled_money | float | 成交金额 |
| trade_id | str | 成交编号 |
| trade_key | str | 本地唯一成交编号 |
| order_key | str | 本地唯一单号 |
| trade_date | int | 成交日期 (YYYYmmdd) |
| trade_time | int | 成交时间 (HHMMSSmmm) |
| trading_day | int | 交易日 (YYYYmmdd) |

**TradeType 值说明：**

| **值** | **常量** | **说明** |
|---|---|---|
| '0' | TradeType.Common | 普通成交 |
| '1' | TradeType.OptionsExecution | 期权行权成交 |
| 'C' | TradeType.Cancelled | 撤单成交 |
| 'D' | TradeType.DR | 除权除息 |
| 'E' | TradeType.ExpireClose | 退市平仓 |
| 'F' | TradeType.ForceClose | 强平 |
| 'R' | TradeType.MTDirectRefund | 直接还款还券 |
| 'S' | TradeType.StopProfitLoss | 止盈止损成交 |

#### TickData 快照行情数据
| **字段** | **类型** | **说明** |
|---|---|---|
| instrument | str | 内部代码 |
| datetime | datetime | 日期时间 |
| time | int | tick 时间 (HHMMSSmmm) |
| action_day | int | tick 自然日期 (YYYYmmdd) |
| trading_day | int | tick 交易日 (YYYYmmdd) |
| last_price | float | 最新价 |
| open_price | float | 开盘价 |
| high_price | float | 最高价 |
| low_price | float | 最低价 |
| volume | int | 成交量 |
| amount | float | 成交额 |
| open_interest | int | 持仓量 |
| pre_close | float | 昨收盘 |
| upper_limit | float | 涨停价 |
| lower_limit | float | 跌停价 |
| ask_price1~10 | float | 卖1~10价 |
| ask_volume1~10 | int | 卖1~10量 |
| bid_price1~10 | float | 买1~10价 |
| bid_volume1~10 | int | 买1~10量 |

#### L2OrderData 逐笔委托行情数据
| **字段** | **类型** | **说明** |
|---|---|---|
| instrument | str | 内部代码 |
| datetime | datetime | 日期时间 |
| time | int | tick 时间 (HHMMSSmmm) |
| channel_no | int | 频道号 |
| volume | int | 委托数量 |
| price | float | 委托价格 |
| seq_num | int | 委托序号 |
| bs_flag | L2BSFlag | 买卖标志：78-未知，66-买入，83-卖出 |
| ord_type | L2OrdType | 价格类型：SH(65-新增，68-撤单)，SZ(49-市价，50-限价，51-本方最优) |

#### L2TradeData 逐笔成交行情数据
| **字段** | **类型** | **说明** |
|---|---|---|
| instrument | str | 内部代码 |
| datetime | datetime | 日期时间 |
| channel_no | int | 频道号 |
| volume | int | 成交数量 |
| price | float | 成交价格 |
| money | float | 成交金额 |
| seq_num | int | 成交序号 |
| bid_seq_num | int | 买方委托序号 |
| ask_seq_num | int | 卖方委托序号 |
| exec_type | L2ExecType | SZ成交类型：70-正常成交，52-撤单成交 |
| bs_flag | L2BSFlag | 买卖标志：78-未知，66-买入，83-卖出 |

#### ContractData（合约数据）
| **字段** | **类型** | **说明** |
|---|---|---|
| instrument | str | 内部代码 |
| product_code | str | 产品代码 |
| product_type | ProductType | 产品类型：股票 / 基金 / 可转债 / 期货 |
| multiplier | float | 合约乘数 |
| price_tick | float | 最小变动价格 |
| name | str | 合约名称 |
| day_trading | bool | 日内回转交易 |
| buy_unit | int | 买数量单位 |
| sell_unit | int | 卖数量单位 |
| underlying | str | 标的代码 |
| option_cp | OptionCP | 期权类型（认购 / 认沽） |
| strike_price | float | 期权行权价格 |

### 枚举类型
所有枚举和辅助类均从 bigquant.bigtrader 导入：

```
from bigquant.bigtrader import (
    Market, Frequency, AccountType,
    Direction, OffsetFlag, OrderType, OrderStatus,
    PosiDirection, TradeType, OptionCP,
    PerOrder, PerContract,
)
```

#### Market（交易市场）
| **值** | **常量** | **说明** |
|---|---|---|
| 'cn_stock' | Market.CN_STOCK | A股 |
| 'cn_fund' | Market.CN_FUND | 基金 |
| 'cn_cbond' | Market.CN_CBOND | 可转债 |
| 'cn_future' | Market.CN_FUTURE | 期货 |
| 'cn_future_option' | Market.CN_FUTURE_OPTION | 期货期权 |
| 'cn_stock_option' | Market.CN_STOCK_OPTION | ETF期权 |
| 'hk_stock' | Market.HK_STOCK | 港股 |

#### Frequency（交易频率）
| **值** | **常量** | **说明** |
|---|---|---|
| '1d' | Frequency.DAILY | 日频 |
| '1m' | Frequency.MINUTE | 分钟频 |
| '5m' | Frequency.MINUTE5 | 5分钟频 |
| '15m' | Frequency.MINUTE15 | 15分钟频 |
| '30m' | Frequency.MINUTE30 | 30分钟频 |
| '60m' | Frequency.MINUTE60 | 60分钟频 |
| 'tick' | Frequency.TICK | Tick频（Level1快照） |
| 'tick2' | Frequency.TICK2 | Tick2频（Level2快照） |

#### AccountType（账户类型）
| **值** | **常量** | **说明** |
|---|---|---|
| '0' | AccountType.STOCK | 股票（现货）账户 |
| '1' | AccountType.FUTURE | 期货账户，可交易期货期权和股指期权 |
| '2' | AccountType.OPTION | 股票期权账户 |
| '3' | AccountType.CREDIT | 融资融券账户 |

#### PosiDirection（持仓方向）
| **值** | **常量** | **说明** |
|---|---|---|
| '1' | PosiDirection.LONG | 多头方向（买） |
| '2' | PosiDirection.SHORT | 空头方向（卖） |

#### Direction（买卖方向）
| **值** | **常量** | **说明** |
|---|---|---|
| '1' | Direction.BUY | 买入 |
| '2' | Direction.SELL | 卖出 |
| '3' | Direction.FinancingBuy | 融资买入 |
| '4' | Direction.SellRepay | 卖券还款 |
| '5' | Direction.LoanSell | 融券卖出 |
| '6' | Direction.BuyRedeliver | 买券还券 |
| '7' | Direction.CashDirectRefund | 直接还款 |
| '8' | Direction.SecDirectRefund | 直接还券 |

#### OffsetFlag（开平标志）
| **值** | **常量** | **说明** |
|---|---|---|
| '0' | OffsetFlag.OPEN | 开仓 |
| '1' | OffsetFlag.CLOSE | 平仓 |
| '2' | OffsetFlag.CLOSETODAY | 平今 |
| '3' | OffsetFlag.CLOSEYESTERDAY | 平昨 |

#### OrderType（委托价格类型）
| **值** | **常量** | **说明** |
|---|---|---|
| '0' | OrderType.LIMIT | 限价 |
| 'U' | OrderType.MARKET | 市价五档即成剩撤 |
| 'S' | OrderType.MKT2LMT | 市价五档即时成交剩余转限价（实盘时仅上交所支持） |
| 'T' | OrderType.MARKET_FAK | 市价即时成交剩余撤单（实盘时仅深交所支持） |
| 'V' | OrderType.MARKET_FOK | 市价全额成交或撤单（实盘时仅深交所支持） |

#### OrderStatus（委托状态）
| **值** | **常量** | **说明** |
|---|---|---|
| 0 | NOTTRADED | 未成交 |
| 1 | PARTTRADED | 部分成交 |
| 2 | ALLTRADED | 全部成交 |
| 3 | PARTCANCELLED | 部分撤单 |
| 4 | CANCELLED | 全部撤单 |
| 5 | REJECTED | 废单 |
| 6 | UNKNOWN | 未知 |
| 10 | NOTPLACE | 未报 |
| 11 | PLACING | 正报 |
| 12 | PENDINGPLACE | 待报 |
| 15 | PARTPENDINGPLACE | 部分待撤 |
| 16 | PENDINGCANCEL | 待撤销 |

#### SubscribeFlag（订阅行情标志位）
| **值** | **常量** | **说明** |
|---|---|---|
| 0 | DEFAULT | 默认值 |
| 2 | L2Snapshot | Level2 快照 |
| 4 | L2Trade | Level2 逐笔成交 |
| 8 | L2Order | Level2 逐笔委托 |
| 16 | L2OrderQueue | Level2 委托队列 |
| 32 | BarData | Level2 K线数据 |
| 64 | MDIndex | Level2 指数快照 |

### 撮合规则
#### 通用规则
- 日频/分钟频回测时使用K线数据撮合，Tick回测时则使用盘口多档行情撮合
- 未成交/部分成交的委托可撤单
- 日内收市后未成交的委托自动作废
- 市价委托未成交部分自动撤销
- 设置固定价格滑点时，成交价格 ± 固定滑点值；设置百分比滑点时，成交价格 × (1 + 百分比滑点值)

#### 基于 Bar 行情撮合
- 成交规则：市价时 Bar 的`volume > 0`或 买入限价 >`low`或 卖出限价 <`high`
- 成交价格 = Bar 的`open`/`close`/`vwap`价格 或 限价价格
- 成交数量 = 当次 Bar 的成交量 × 成交比例`volume_limit`
- 未成交部分，市价单自动撤单，限价单则继续在下根K线撮合，直至收盘后作废

#### 基于 Tick 快照行情撮合
- 以对手盘口价格一档开始撮合，取决于盘口深度，最多五或十档
- 发出订单后立即撮合，限价单未成部分在后续Tick中继续撮合
- 涨停/跌停按规则处理排队/成交

#### 关于成交滑点
- 设置固定价格滑点时：买入价格 + 滑点值，卖出价格 - 滑点值
- 设置百分比滑点时：买入价格 × (1 + 滑点值)，卖出价格 × (1 - 滑点值)
