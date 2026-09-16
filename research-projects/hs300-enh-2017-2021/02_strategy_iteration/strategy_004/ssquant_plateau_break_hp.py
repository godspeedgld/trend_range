"""迭代四·平台突破 ssquant 高性能版（register_indicator + api 属性状态机）。

对齐 ssquant B_双均线策略_高性能.py 结构，规避 0 交易的两个坑：
  1. register_indicator 预计算布林带 UB/LB + ATR → 主循环 O(1) 查表（不做重活）
  2. 增量状态机状态存 **api 属性**（api._trend 等），而非全局变量（全局跨 bar 重置）

算法与 plateau_break_local_sim.py 本地模拟完全一致（已验证 21 笔）：
  开仓：close > 阻力位×1.03 → 次日开盘买入
  平仓：2×ATR 跟踪止损（持仓期最高收盘 − 2×ATR，只升不降）→ 次日开盘卖出
"""
import math

import numpy as np
import pandas as pd

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import RunMode, UnifiedStrategyRunner
from ssquant.config.trading_config import get_config

BB_WINDOW, BB_K = 20, 1.0
CLEAN_INTERVAL = 4
HSAR_M, HSAR_Q = 10, 2
BREAKOUT_PCT = 0.03
ATR_PERIOD, ATR_MULT = 14, 4.0


# ── 辅助函数（纯函数，模块级安全）──
def resistance_hsar(highs, M=HSAR_M, Q=HSAR_Q):
    if len(highs) < Q:
        return None
    min_h, max_h = min(highs), max(highs)
    if max_h == min_h:
        return max_h
    width = (max_h - min_h) / M
    cnt, upper = [0] * M, [0] * M
    for h in highs:
        idx = min(int((h - min_h) / width), M - 1)
        cnt[idx] += 1
        upper[idx] = min_h + (idx + 1) * width
    threshold = min_h + (max_h - min_h) * 2 / 3
    valid = [(cnt[i], upper[i]) for i in range(M) if cnt[i] >= Q and upper[i] >= threshold]
    if not valid:
        return None
    valid.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return valid[0][1]


def clean_points(points, min_interval=CLEAN_INTERVAL):
    if len(points) <= 1:
        return points
    cleaned = [points[0]]
    for p in points[1:]:
        if p[0] - cleaned[-1][0] < min_interval:
            cleaned.pop()
            cleaned.append(p)
        else:
            cleaned.append(p)
    return cleaned


def initialize(api: StrategyAPI):
    api.log("平台突破 高性能版（register_indicator + api状态）初始化")

    def ub_func(c, o, h, l, v):
        s = pd.Series(c)
        return (s.rolling(BB_WINDOW).mean() + BB_K * s.rolling(BB_WINDOW).std()).to_numpy()

    def lb_func(c, o, h, l, v):
        s = pd.Series(c)
        return (s.rolling(BB_WINDOW).mean() - BB_K * s.rolling(BB_WINDOW).std()).to_numpy()

    def atr_func(c, o, h, l, v):
        pc = pd.Series(c).shift(1)
        tr = pd.concat([pd.Series(h) - pd.Series(l),
                        (pd.Series(h) - pc).abs(),
                        (pd.Series(l) - pc).abs()], axis=1).max(axis=1)
        return tr.rolling(ATR_PERIOD).mean().to_numpy()

    api.register_indicator('ub', ub_func, window=BB_WINDOW + 1)
    api.register_indicator('lb', lb_func, window=BB_WINDOW + 1)
    api.register_indicator('atr', atr_func, window=ATR_PERIOD + 1)

    # 增量状态机（api 属性，跨 bar 持久）
    api._trend = 'NONE'
    api._tmp_hp = 0.0; api._tmp_hp_i = 0
    api._tmp_lp = 0.0; api._tmp_lp_i = 0
    api._confirmed = []          # [(idx, price, 'H'/'L')]
    api._resistance = 0.0
    api._pos_high = 0.0          # 持仓期最高收盘
    api._pos_stop = 0.0          # 2×ATR 跟踪止损价
    api._pending_atr = 0.0       # 开仓时的 ATR（成交后设止损用）


def strategy(api: StrategyAPI):
    idx = api.get_idx()
    if idx < BB_WINDOW + 10:
        return

    cu = api.get_indicator('ub')
    cl = api.get_indicator('lb')
    if cu is None or cl is None or math.isnan(cu) or math.isnan(cl):
        return

    cs = api.get_close()
    if len(cs) < BB_WINDOW + 10:
        return
    c0 = cs.iloc[-1]
    h0 = api.get_high().iloc[-1]
    l0 = api.get_low().iloc[-1]

    # ── 增量转折点状态机（与本地模拟一致，状态存 api 属性）──
    if api._trend == 'NONE':
        if h0 > cu:
            api._trend = 'UP'; api._tmp_hp, api._tmp_hp_i = h0, idx
        elif l0 < cl:
            api._trend = 'DOWN'; api._tmp_lp, api._tmp_lp_i = l0, idx
    elif api._trend == 'UP':
        if h0 > api._tmp_hp:
            api._tmp_hp, api._tmp_hp_i = h0, idx
        elif l0 < cl:
            api._confirmed.append((api._tmp_hp_i, api._tmp_hp, 'H'))
            api._trend = 'DOWN'; api._tmp_lp, api._tmp_lp_i = l0, idx
            api._confirmed = clean_points(api._confirmed)
    elif api._trend == 'DOWN':
        if l0 < api._tmp_lp:
            api._tmp_lp, api._tmp_lp_i = l0, idx
        elif h0 > cu:
            api._confirmed.append((api._tmp_lp_i, api._tmp_lp, 'L'))
            api._trend = 'UP'; api._tmp_hp, api._tmp_hp_i = h0, idx
            api._confirmed = clean_points(api._confirmed)

    # ── HSAR 阻力位 ──
    if api._confirmed:
        highs = [p[1] for p in api._confirmed if p[2] == 'H']
        r = resistance_hsar(highs)
        if r is not None:
            api._resistance = r

    # ── ATR ──
    atr = api.get_indicator('atr')
    if atr is None or math.isnan(atr) or atr <= 0:
        return

    pos = api.get_pos()

    # ── 持仓：吊灯止损（持仓期最高价 high − k×ATR，盘中 low 触及即触发，止损价成交）──
    if pos > 0:
        if api._pos_stop == 0:
            api._pos_high = h0
            api._pos_stop = h0 - ATR_MULT * atr
        else:
            api._pos_high = max(api._pos_high, h0)
            ns = api._pos_high - ATR_MULT * atr
            if ns > api._pos_stop:
                api._pos_stop = ns
        if l0 <= api._pos_stop:                       # 盘中 low 触及止损价
            print(f"[突破HP] 吊灯止损 idx={idx} low={l0:.1f} stop={api._pos_stop:.1f}")
            api.sell(order_type='limit', price=api._pos_stop, reason='吊灯止损')
            api._pos_high = 0.0; api._pos_stop = 0.0
        return

    # ── 空仓：突破阻力位 3% ──
    if api._resistance > 0 and c0 > api._resistance * (1 + BREAKOUT_PCT):
        print(f"[突破HP] ★开仓 idx={idx} close={c0:.1f} res={api._resistance:.1f}")
        api.buy(volume=1, order_type='next_bar_open', reason=f'突破阻力位 {api._resistance:.1f}')


# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    RUN_MODE = RunMode.BACKTEST
    strategy_params = {'bb_window': BB_WINDOW, 'bb_k': BB_K, 'clean_interval': CLEAN_INTERVAL,
                       'hsar_m': HSAR_M, 'hsar_q': HSAR_Q, 'breakout_pct': BREAKOUT_PCT,
                       'atr_period': ATR_PERIOD, 'atr_mult': ATR_MULT}

    config = get_config(RUN_MODE,
        symbol='m888',
        kline_period='1h',
        adjust_type='1',
        start_date='2022-01-01',
        end_date='2026-06-18',
        initial_capital=1000000,
        slippage_ticks=1,
        lookback_bars=500,
        data_source_mode='data_server',
    )

    print(f"运行模式: {RUN_MODE.value} | {config['symbol']} {config['kline_period']} "
          f"{config['start_date']}~{config['end_date']}")
    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    try:
        results = runner.run(strategy=strategy, initialize=initialize, strategy_params=strategy_params)
    except KeyboardInterrupt:
        print("\n用户中断"); runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback; traceback.print_exc()
        runner.stop()
