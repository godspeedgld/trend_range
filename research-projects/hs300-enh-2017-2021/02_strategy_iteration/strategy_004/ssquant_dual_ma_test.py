"""
双均线策略 - 高性能版本（IndicatorCache 注册式 / v2）

与同目录下 `B_双均线策略.py` 行为完全一致，只是把策略写法升级到方式一：

  原版：每根 Bar 都跑 `close.rolling(N).mean()` 全量计算
  本版：在 initialize 钩子里一次性注册 sma_fast / sma_slow，
        主循环只做 `api.get_indicator(name)` O(1) 查表

实测加速（profiling/bench_indicator_cache.py 数据）：
  - 策略段加速 4-19× （N 越小、用户层占比越高，加速越明显）
  - 总耗时加速 1.2-2.6×
  - trades 序列与原版逐位完全一致（笔数、价格、方向、时间戳）

═══════════════════════════════════════════════════════════════════
v2 起：三档全路径可用（回测 + SIMNOW + 实盘）
═══════════════════════════════════════════════════════════════════

【一份策略代码，三种运行模式都能跑】这是 v2 的核心承诺。

  回测 (BACKTEST)
    • DataSource.set_data() 一次性预计算全量
    • 主循环 O(1) 查表

  SIMNOW / 实盘 (REAL_TRADING)
    • LiveDataSource 在每根新 K 线写入入口（on_ws_history /
      on_ws_kline / update_kline_with_tick / _preload_historical_data）
      自动触发全量重算（O(maxlen)，maxlen<=1000，~ms 级）
    • 数值与回测路径**逐位等价**（profiling/audit_live_indicator_v2.py 已验证）
    • 策略代码完全不需要为实盘做任何改动

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低）
═══════════════════════════════════════════════════════════════════

  方式一（推荐）— IndicatorCache 注册式
    • initialize 阶段 api.register_indicator(name, func)，引擎自动预计算 + 保持最新
    • 主循环 api.get_indicator(name) → 标量，O(1) 查表
    • 性能等级：与内置指标相同
    • 适合：指标公式固定、在策略中多次使用的场景  ← 本文件采用

  方式二 — NumPy 数组手动计算
    • api.get_close_array(window=N) 直接拿 ndarray，自己 mean()/std()/...
    • 比 Pandas 快 10-30×，但每根 Bar 仍要算一次
    • 适合：公式简单、每 Bar 计算量小的场景

  方式三 — 兼容老写法
    • api.get_close().rolling(N).mean() 等 Pandas 写法
    • 慢但向后兼容，所有现有策略零改动可继续运行

═══════════════════════════════════════════════════════════════════
"""

import pandas as pd

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import RunMode, UnifiedStrategyRunner
from ssquant.config.trading_config import get_config

def initialize(api: StrategyAPI):
    """策略初始化 — 在数据已加载、主循环开始前调用一次。

    关键：在这里 api.register_indicator(name, func) 注册的指标，引擎会立即
    对全量数据做一次预计算，存成 ndarray。主循环里 get_indicator 是 O(1) 查表。
    """
    api.log("双均线交叉策略初始化（高性能版 / IndicatorCache）")
    fast_ma = api.get_param('fast_ma', 2)
    slow_ma = api.get_param('slow_ma', 5)
    verbose = api.get_param('verbose_kline', False)
    api.log(f"参数设置 - 快线: {fast_ma}, 慢线: {slow_ma}, 打印K线: {verbose}")

    # ====== 注册自定义指标（一次预计算，主循环 O(1) 查表） ======
    # 函数协议：func(close, open, high, low, volume) -> np.ndarray
    # 全部都是 numpy 一维数组，长度 == 数据长度。
    # 这里直接用 pandas rolling 做预计算，结果数值与原版完全等价；如需更快，
    # 可换成 numpy/numba 自实现，本文件保持简单。
    api.register_indicator(
        'sma_fast',
        lambda c, o, h, l, v: pd.Series(c).rolling(fast_ma).mean().to_numpy(),
        window=fast_ma,
    )
    api.register_indicator(
        'sma_slow',
        lambda c, o, h, l, v: pd.Series(c).rolling(slow_ma).mean().to_numpy(),
        window=slow_ma,
    )

def ma_cross_strategy(api: StrategyAPI):
    """双均线交叉策略 — 主循环逻辑。

    主循环只做：
      1. 取参数 + 当前持仓
      2. O(1) 查 sma_fast / sma_slow 在 t-1 / t 两根 Bar 的值
      3. 金叉/死叉判断 + 下单
    """
    fast_ma = api.get_param('fast_ma', 2)
    slow_ma = api.get_param('slow_ma', 3)

    current_idx = api.get_idx()
    if current_idx < slow_ma:
        return

    # === 方式一核心：O(1) 查表，最近 2 个值用于判断金叉/死叉 ===
    fast_arr = api.get_indicator_array('sma_fast', window=2)
    slow_arr = api.get_indicator_array('sma_slow', window=2)

    # 长度兜底（数据头部 NaN 区域）
    if len(fast_arr) < 2 or len(slow_arr) < 2:
        return

    f0, f1 = fast_arr[-2], fast_arr[-1]
    s0, s1 = slow_arr[-2], slow_arr[-1]

    # v2 验证：第一次取到非 NaN sma 时打印一次心跳，确认 IndicatorCache 在 SIMNOW/实盘下激活
    import math as _math
    if not getattr(api, '_v2_logged', False) and not _math.isnan(f1) and not _math.isnan(s1):
        api.log(f"[v2 验证] IndicatorCache 已激活 (LiveDataSource 路径)："
                f"sma_fast={f1:.4f}, sma_slow={s1:.4f}")
        api._v2_logged = True

    current_pos = api.get_pos()

    # 均线金叉：快线上穿慢线
    if f0 <= s0 and f1 > s1:
        if current_pos <= 0:
            if current_pos < 0:
                api.buycover(volume=1, order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"均线金叉：快线({f1:.2f})上穿慢线({s1:.2f})，买入")

    # 均线死叉：快线下穿慢线
    elif f0 >= s0 and f1 < s1:
        if current_pos >= 0:
            if current_pos > 0:
                api.sell(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"均线死叉：快线({f1:.2f})下穿慢线({s1:.2f})，卖出")

# =====================================================================
# 配置区（与 B_双均线策略.py 完全一致；策略逻辑改动透明、配置无需调整）
# =====================================================================

if __name__ == "__main__":
    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    # v2 起 IndicatorCache 在三种模式下统一可用：
    #   BACKTEST       — DataSource 一次性预计算
    #   SIMNOW         — LiveDataSource 每根新 K 线全量重算
    #   REAL_TRADING   — 同 SIMNOW
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'fast_ma': 5,
        'slow_ma': 20,
        'fast_ma': 2,
        'slow_ma': 3,
        'verbose_kline': True,   # SIMNOW 验证模式：打开 K 线打印便于观察 v2 工作
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            symbol='rb888',                    # 合约代码（支持 au2602, au888 等）
            kline_period='1d',                 # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            start_date='2022-01-01',            # 回测开始日期
            end_date='2026-06-18',              # 回测结束日期
            initial_capital=1000000,           # 初始资金（元）
            slippage_ticks=1,                  # 滑点跳数（每跳=price_tick）
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )

    elif RUN_MODE == RunMode.SIMNOW:
        # SIMNOW 模拟 — IndicatorCache 走 LiveDataSource 流式重算路径
        # 数值与回测路径逐位等价（profiling/audit_live_indicator_v2.py 已验证）
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            symbol='rb888',                    # 合约代码（888=主力连续，CTP会自动解析为实际合约）
            kline_period='1m',                 # K线周期（CTP Tick合成）
            kline_source='local',            # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送)
            order_offset_ticks=5,              # 委托超价跳数（+5=对手价+5跳，确保成交）
            algo_trading=True,                 # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                  # 订单超时时间（秒），0=不启用
            retry_limit=3,                     # 订单失败最大重试次数
            retry_offset_ticks=5,              # 重试时额外超价跳数
            auto_roll_enabled=False,           # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,             # 移仓后是否在新主力补回仓位
            preload_history=True,              # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=3000,        # 预加载历史K线数量
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            # IndicatorCache 实盘版的"全量重算窗口"由 lookback_bars 控制：
            # 每根新 K 线在最近 lookback_bars 根上重算，O(N) ~ ms 级
            lookback_bars=500,                # 回溯窗口（实盘IndicatorCache重算范围）
            enable_tick_callback=False,        # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,              # 是否保存K线到CSV文件
            save_kline_db=False,               # 是否保存K线到SQLite数据库
            save_tick_csv=False,               # 是否保存Tick到CSV文件
            save_tick_db=False,                # 是否保存Tick到SQLite数据库
        )

    elif RUN_MODE == RunMode.REAL_TRADING:
        # 实盘 — IndicatorCache 同样走 LiveDataSource 流式重算
        # ⚠ 真金白银！上线前请务必：① 核对账户  ② 先在 SIMNOW 跑通  ③ 小资金试跑
        config = get_config(RUN_MODE,
            account='real_default',            # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            symbol='au888',                    # 合约代码
            kline_period='1m',                 # K线周期
            kline_source='data_server',             # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送)
            order_offset_ticks=-10,            # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）
            algo_trading=True,                 # 智能算法交易
            order_timeout=10,                  # 订单超时（秒）
            retry_limit=3,                     # 最大重试次数
            retry_offset_ticks=5,              # 重试超价跳数
            auto_roll_enabled=False,           # 自动移仓
            auto_roll_reopen=True,             # 移仓补回仓位
            preload_history=True,              # 预加载历史K线
            history_lookback_bars=100,         # 预加载K线数
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            # IndicatorCache 实盘版的"全量重算窗口"由 lookback_bars 控制：
            # 每根新 K 线在最近 lookback_bars 根上重算，O(N) ~ ms 级
            lookback_bars=500,                 # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,        # Tick回调
            save_kline_csv=False,              # 保存K线CSV
            save_kline_db=False,               # 保存K线DB
            save_tick_csv=False,               # 保存Tick CSV
            save_tick_db=False,                # 保存Tick DB
        )

    else:
        raise ValueError(f"未支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("双均线策略（高性能版 / IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=ma_cross_strategy,
            initialize=initialize,
            strategy_params=strategy_params,
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
