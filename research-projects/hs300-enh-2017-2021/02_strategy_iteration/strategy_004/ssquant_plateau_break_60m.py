"""迭代四 ssquant 版 — 豆粕(m888)·平台突破 + 2×ATR 止损（60 分钟线，远程数据）。

结构参考 ssquant/examples/B_双均线策略_高性能.py（IndicatorCache 注册式 + O(1) 查表）：
  initialize(api)：注册 ATR 指标 + 初始化平台突破状态
  strategy(api)：  查平台突破（转折点+HSAR+突破3%，算法同迭代一~四）→ next_bar_open 开仓；
                   持仓中 2×ATR 静态止损（低于止损价即平，next_bar_open 成交）

与 local_backtest 版（strategy.py）的差异（用户指定）：
  - 周期：日线 → **60m（1h K线）**，data_source_mode='data_server'（远程数据，有权限）
  - 止损：1×ATR → **2×ATR**（atr_period 14）
  - 引擎：local_backtest → ssquant（价格双轨制：策略看复权价，盈亏用真实价）

平台突破算法不变：转折点 N20/K1/P4 + HSAR M10/Q2 + 突破3% + LOOKBACK 252（60m K线上）。

运行：python ssquant_plateau_break_60m.py（输出由 ssquant 自带：文本报告 + HTML）
"""
import math

import numpy as np
import pandas as pd

from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import RunMode, UnifiedStrategyRunner
from ssquant.config.trading_config import get_config

# ── 平台突破参数（与迭代一~四一致）──
P = {"bb_window": 20, "bb_k": 1.0, "p_clear": 4,       # 转折点
     "m_bins": 10, "q_density": 2,                       # HSAR
     "break_pct": 0.03}                                  # 突破 3%
LOOKBACK = 252                                           # 阻力位回溯窗口（60m bars）
ATR_PERIOD = 14
K_STOP = 2.0                                             # 2×ATR 静态止损


# ═══════════════════════════════════════════════════════════
# 转折点 + HSAR（从 shared/plateau_algo 移植为独立函数——ssquant 策略自包含运行，
# 不依赖工程目录 import；算法逐行同源，参数一致）
# ═══════════════════════════════════════════════════════════

def _turning_points(close, high, low):
    """布林带 N20/K1 过滤 + 方向迭代识别转折点，P=4 清洗。返回 [(idx, price)] 高点。"""
    ma = pd.Series(close).rolling(P["bb_window"]).mean()
    sd = pd.Series(close).rolling(P["bb_window"]).std()
    ub, lb = (ma + P["bb_k"] * sd).to_numpy(), (ma - P["bb_k"] * sd).to_numpy()
    highs, lows = [], []
    direction, hp_i, hp_p, lp_i, lp_p = 0, -1, -1.0, -1, -1.0
    for i in range(len(close)):
        hi, lo = high[i], low[i]
        if direction == 0:
            if not np.isnan(ub[i]) and hi > ub[i]:
                direction, hp_i, hp_p = 1, i, hi
            elif not np.isnan(lb[i]) and lo < lb[i]:
                direction, lp_i, lp_p = -1, i, lo
        elif direction == 1:
            if hi > hp_p:
                hp_i, hp_p = i, hi
            if not np.isnan(lb[i]) and lo < lb[i]:
                if hp_i >= 0:
                    highs.append((hp_i, hp_p))
                direction, lp_i, lp_p = -1, i, lo
        else:
            if lo < lp_p:
                lp_i, lp_p = i, lo
            if not np.isnan(ub[i]) and hi > ub[i]:
                if lp_i >= 0:
                    lows.append((lp_i, lp_p))
                direction, hp_i, hp_p = 1, i, hi
    pts = sorted([(i, pr, "H") for i, pr in highs] + [(i, pr, "L") for i, pr in lows])
    keep = []
    for k, (idx, pr, kind) in enumerate(pts):
        if 0 < k and idx - pts[k - 1][0] < P["p_clear"]:
            continue
        if k < len(pts) - 1 and pts[k + 1][0] - idx < P["p_clear"]:
            continue
        keep.append((idx, pr, kind))
    return [(i, pr) for i, pr, kd in keep if kd == "H"]


def _resistance_level(highs):
    """HSAR：价格分箱 M10 + 密度聚集 Q2，阻力位=含Q+高点的最大箱体上界（前1/3高位）。"""
    if len(highs) < P["q_density"]:
        return None
    prices = np.array([pr for _, pr in highs])
    lo, hi = prices.min(), prices.max()
    if hi - lo < 1e-12:
        return None
    width = (hi - lo) / P["m_bins"]
    counts = np.zeros(P["m_bins"])
    for pr in prices:
        counts[min(int((pr - lo) / width), P["m_bins"] - 1)] += 1
    cand = np.where(counts >= P["q_density"])[0]
    top = np.where(lo + np.arange(P["m_bins"]) * width >= lo + 2 * (hi - lo) / 3)[0]
    valid = [b for b in cand if b in set(top)]
    if not valid:
        return None
    best = max(valid, key=lambda b: (counts[b], b))
    return lo + (best + 1) * width


# ═══════════════════════════════════════════════════════════
# 策略
# ═══════════════════════════════════════════════════════════

def initialize(api: StrategyAPI):
    api.log("豆粕平台突破 + 2×ATR 止损（60m）初始化")
    # ATR(14) 指标注册（IndicatorCache 预计算，主循环 O(1)）
    def atr14(c, o, h, l, v):
        pc = pd.Series(c).shift(1)
        tr = pd.concat([pd.Series(h) - pd.Series(l),
                        (pd.Series(h) - pc).abs(),
                        (pd.Series(l) - pc).abs()], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean().to_numpy()

    api.register_indicator('atr14', atr14, window=ATR_PERIOD + 1)
    api._stop_price = None        # 开仓后记录 2×ATR 静态止损价


def plateau_break_strategy(api: StrategyAPI):
    idx = api.get_idx()
    if idx < LOOKBACK:
        return

    current_pos = api.get_pos()
    atr = api.get_indicator('atr14')
    if atr is None or math.isnan(atr) or atr <= 0:
        return

    # ── 持仓：2×ATR 静态止损（低于止损价 → 次根K线开盘平仓）──
    if current_pos > 0 and api._stop_price is not None:
        price = api.get_price()
        if price <= api._stop_price:
            api.sell(order_type='next_bar_open', reason=f"2×ATR止损 @{api._stop_price:.1f}")
            api._stop_price = None
            return

    # ── 空仓：平台突破检测（≤t 历史，最近 LOOKBACK 根 60m K线）──
    if current_pos <= 0:
        closes = api.get_close_array(window=LOOKBACK)
        highs_a = api.get_high_array(window=LOOKBACK)
        lows_a = api.get_low_array(window=LOOKBACK)
        if len(closes) < LOOKBACK:
            return
        hp = _turning_points(closes, highs_a, lows_a)
        res = _resistance_level(hp)
        if res is None:
            return
        if api.get_close() > res * (1 + P["break_pct"]):
            api.buy(volume=1, order_type='next_bar_open',
                    reason=f"平台突破 res={res:.1f}")
            api._stop_price = None     # 成交后按入场价设（简化：下根bar设置）


def on_order_filled(api: StrategyAPI, order):
    """成交回调（如引擎支持）：按入场价设置 2×ATR 静态止损。"""
    # 引擎若不自动回调，strategy 内下一根 bar 也会补设（见下）
    pass


def plateau_break_strategy_v2(api: StrategyAPI):
    """主策略（含成交后止损设置兜底）。"""
    idx = api.get_idx()
    if idx < LOOKBACK:
        return
    current_pos = api.get_pos()
    atr = api.get_indicator('atr14')
    if atr is None or math.isnan(atr) or atr <= 0:
        return

    # 持仓但止损价未设（刚成交）→ 按当前价设 2×ATR 静态止损（成交后首根 bar）
    if current_pos > 0 and api._stop_price is None:
        api._stop_price = api.get_price() - K_STOP * atr
        api.log(f"止损价设置: {api._stop_price:.1f} (2×ATR={2*atr:.1f})")
        return

    if current_pos > 0 and api._stop_price is not None:
        if api.get_price() <= api._stop_price:
            api.sell(order_type='next_bar_open', reason=f"2×ATR止损 @{api._stop_price:.1f}")
            api._stop_price = None
        return

    # 空仓：平台突破检测（用 get_close() Series 截取窗口，避开 get_close_array 零拷贝视图污染）
    close_s = api.get_close()
    if len(close_s) < LOOKBACK:
        if idx % 300 == 0:
            print(f"[DIAG] idx={idx} close_s={len(close_s)} <LOOKBACK 返回")
        return
    closes = close_s.iloc[-LOOKBACK:].to_numpy()
    highs_a = api.get_high().iloc[-LOOKBACK:].to_numpy()
    lows_a = api.get_low().iloc[-LOOKBACK:].to_numpy()
    hp = _turning_points(closes, highs_a, lows_a)
    res = _resistance_level(hp)
    price = api.get_price()                    # 当前价（标量）
    if price is not None and 3540 <= price <= 3570:
        print(f"[DIAG2] idx={idx} close_s={len(close_s)} closes[0]={closes[0]:.0f} closes[-1]={closes[-1]:.0f} hp={len(hp)} res={res}")
    if res is not None and price is not None and price > res * (1 + P["break_pct"]):
        print(f"[DIAG] ★突破触发 idx={idx} price={price:.1f} res={res:.1f}")
        api.buy(volume=1, order_type='next_bar_open', reason=f"平台突破 res={res:.1f}")


# =====================================================================
# 配置区（参考 B_双均线策略_高性能.py）
# =====================================================================

if __name__ == "__main__":
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'lookback': LOOKBACK,
        'atr_period': ATR_PERIOD,
        'k_stop': K_STOP,
    }

    config = get_config(RUN_MODE,
        symbol='m888',                     # 豆粕主力连续
        kline_period='1h',                 # 60 分钟K线
        adjust_type='1',                   # 后复权（价格双轨制：盈亏用真实价）
        start_date='2024-01-01',           # 起始（data_server 分钟数据覆盖范围）
        end_date='2026-06-18',
        initial_capital=1000000,
        slippage_ticks=1,
        lookback_bars=LOOKBACK + 50,       # IndicatorCache 预热 ≥ LOOKBACK
        data_source_mode='data_server',    # 远程数据（有权限）
    )

    print("\n" + "=" * 80)
    print("豆粕平台突破 + 2×ATR 止损（60m / ssquant）")
    print("=" * 80)
    print(f"合约: {config['symbol']} | 周期: {config['kline_period']} | "
          f"区间: {config['start_date']} ~ {config['end_date']}")
    print(f"突破: 转折点N20/K1/P4 + HSAR M10/Q2 + 3% | LOOKBACK {LOOKBACK} bars")
    print(f"止损: {K_STOP}×ATR({ATR_PERIOD}) 静态")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    try:
        results = runner.run(
            strategy=plateau_break_strategy_v2,
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
