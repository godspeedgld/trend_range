"""
策略名称: 转折点识别与HSAR阻力位突破策略
策略描述:
    1. 基于布林带过滤识别局部高低点(转折点)
    2. 使用HSAR算法(分箱+密度)识别阻力位
    3. 收盘价突破阻力位3%做多
    4. 2倍ATR跟踪止损
作者: 松鼠Quant-Ai agent

# ============================================================
# 本策略由 SSQuant AI Agent 自动生成
# AI助手地址: ai.kanpan789.com
# SSQuant项目地址: https://gitee.com/ssquant/ssquant
# 松鼠Quant俱乐部提供技术支持
# ============================================================
"""
import pandas as pd
import numpy as np
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


# ============== 全局状态变量 ==============
# 趋势状态: 'UP', 'DOWN', 'NONE'
g_trend_state = 'NONE'
g_temp_hp = 0      # 临时高点价格
g_temp_hp_idx = 0  # 临时高点索引
g_temp_lp = 0      # 临时低点价格
g_temp_lp_idx = 0  # 临时低点索引

# 历史确认的转折点列表: [(index, price, type), ...] type: 'H' or 'L'
g_confirmed_points = []

# HSAR 阻力位
g_resistance_price = 0


# ============== 辅助函数 ==============
def calculate_bollinger(close, window=20, k=1):
    """计算布林带"""
    ma = close.rolling(window).mean()
    std = close.rolling(window).std()
    ub = ma + k * std
    lb = ma - k * std
    return ma, ub, lb

def identify_resistance_hsar(points_list, M=10, Q=2):
    """
    HSAR 阻力位识别算法
    points_list: 列表，元素为 (index, price, type)，type='H'表示高点
    M: 分箱数量
    Q: 最小聚集点数
    返回: 阻力位价格，如果没有满足条件的阻力位返回 None
    """
    # 1. 提取所有高点
    highs = [p[1] for p in points_list if p[2] == 'H']

    if len(highs) < Q:
        return None

    # 2. 确定价格范围
    min_h = min(highs)
    max_h = max(highs)

    if max_h == min_h:
        return max_h

    # 3. 分箱 (Binning)
    bin_width = (max_h - min_h) / M
    if bin_width == 0:
        return max_h

    # 初始化箱体计数
    bins_count = [0] * M
    bins_upper_bound = [0] * M

    for h in highs:
        # 计算所属箱体索引
        idx = int((h - min_h) / bin_width)
        if idx >= M:
            idx = M - 1
        bins_count[idx] += 1
        # 记录箱体上界
        bins_upper_bound[idx] = min_h + (idx + 1) * bin_width

    # 4. 筛选条件
    # 条件A: 高点个数 >= Q
    # 条件B: 位于价格前 1/3 高位 (即箱体上界 > 整体高点的 66% 分位? 或者简单的价格位置)
    # 原文: "限定该区间价位需排在所有区间的前 1/3" -> 通常指价格处于较高区域
    # 这里简化为：箱体上界必须大于 高点最小值 + (最大值-最小值)*2/3

    threshold_price_level = min_h + (max_h - min_h) * 2 / 3

    valid_bins = []
    for i in range(M):
        if bins_count[i] >= Q and bins_upper_bound[i] >= threshold_price_level:
            valid_bins.append((bins_count[i], bins_upper_bound[i]))

    if not valid_bins:
        return None

    # 5. 选择包含高点最多的区间，若有并列取上界最高的
    # 排序: 先按数量降序，再按上界降序
    valid_bins.sort(key=lambda x: (x[0], x[1]), reverse=True)

    best_resistance = valid_bins[0][1]
    return best_resistance

def clean_points(points_list, min_interval=4):
    """
    清洗转折点：移除时间间隔过近的相邻点
    points_list: [(idx, price, type), ...] 按时间排序
    min_interval: 最小时间间隔
    """
    if len(points_list) <= 1:
        return points_list

    cleaned = [points_list[0]]
    for i in range(1, len(points_list)):
        prev_point = cleaned[-1]
        curr_point = points_list[i]

        # 检查时间间隔
        if curr_point[0] - prev_point[0] < min_interval:
            # 如果间隔太近，移除前一个点（保留最新的，因为最新的可能更准确代表当前极值）
            # 或者根据业务逻辑，也可以保留幅度更大的那个。这里简单处理：移除旧的
            cleaned.pop()
            cleaned.append(curr_point)
        else:
            cleaned.append(curr_point)

    return cleaned


# ============== 策略初始化函数 ==============
def initialize(api: StrategyAPI):
    """
    策略初始化函数
    """
    api.log("=" * 60)
    api.log("转折点识别与HSAR阻力位突破策略初始化")
    api.log("=" * 60)

    # 获取参数
    bb_window = api.get_param('bb_window', 20)
    bb_k = api.get_param('bb_k', 1.0)
    clean_interval = api.get_param('clean_interval', 4)
    hsar_m = api.get_param('hsar_m', 10)
    hsar_q = api.get_param('hsar_q', 2)
    breakout_pct = api.get_param('breakout_pct', 0.03)
    atr_period = api.get_param('atr_period', 14)
    atr_mult = api.get_param('atr_mult', 2.0)

    api.log(f"布林带参数: Window={bb_window}, K={bb_k}")
    api.log(f"清洗间隔: {clean_interval}")
    api.log(f"HSAR参数: M={hsar_m}, Q={hsar_q}")
    api.log(f"突破阈值: {breakout_pct*100}%")
    api.log(f"ATR止损倍数: {atr_mult}")


# ============== 策略主函数 ==============
def strategy(api: StrategyAPI):
    """
    策略主函数
    """
    global g_trend_state, g_temp_hp, g_temp_hp_idx, g_temp_lp, g_temp_lp_idx, g_confirmed_points, g_resistance_price

    # 1. 获取参数
    bb_window = api.get_param('bb_window', 20)
    bb_k = api.get_param('bb_k', 1.0)
    clean_interval = api.get_param('clean_interval', 4)
    hsar_m = api.get_param('hsar_m', 10)
    hsar_q = api.get_param('hsar_q', 2)
    breakout_pct = api.get_param('breakout_pct', 0.03)
    atr_period = api.get_param('atr_period', 14)
    atr_mult = api.get_param('atr_mult', 2.0)

    # 2. 数据检查
    min_bars = bb_window + 10
    if api.get_idx() < min_bars:
        return

    # 3. 获取数据
    close = api.get_close()
    high = api.get_high()
    low = api.get_low()

    if len(close) < min_bars:
        return

    current_idx = api.get_idx()
    current_close = close.iloc[-1]
    current_high = high.iloc[-1]
    current_low = low.iloc[-1]

    # 4. 计算布林带
    ma, ub, lb = calculate_bollinger(close, bb_window, bb_k)

    if pd.isna(ub.iloc[-1]) or pd.isna(lb.iloc[-1]):
        return

    current_ub = ub.iloc[-1]
    current_lb = lb.iloc[-1]

    # 5. 转折点识别算法 (状态机)

    # 初始状态处理
    if g_trend_state == 'NONE':
        if current_high > current_ub:
            g_trend_state = 'UP'
            g_temp_hp = current_high
            g_temp_hp_idx = current_idx
            api.log(f"[{current_idx}] 初始转为上升趋势, 临时高点: {g_temp_hp}")
        elif current_low < current_lb:
            g_trend_state = 'DOWN'
            g_temp_lp = current_low
            g_temp_lp_idx = current_idx
            api.log(f"[{current_idx}] 初始转为下降趋势, 临时低点: {g_temp_lp}")
        return # 第一根突破K线不交易，仅初始化状态

    # 迭代规则
    if g_trend_state == 'UP':
        # 上升趋势中
        if current_high > g_temp_hp:
            # 更新临时高点
            g_temp_hp = current_high
            g_temp_hp_idx = current_idx
        else:
            # 保持原有临时高点

            # 检查是否跌破下轨 -> 趋势反转
            if current_low < current_lb:
                # 确认前序高点
                new_point = (g_temp_hp_idx, g_temp_hp, 'H')
                g_confirmed_points.append(new_point)
                api.log(f"[{current_idx}] 确认高点: {g_temp_hp}, 趋势转降")

                # 切换状态
                g_trend_state = 'DOWN'
                g_temp_lp = current_low
                g_temp_lp_idx = current_idx

                # 清洗点
                g_confirmed_points = clean_points(g_confirmed_points, clean_interval)

    elif g_trend_state == 'DOWN':
        # 下降趋势中
        if current_low < g_temp_lp:
            # 更新临时低点
            g_temp_lp = current_low
            g_temp_lp_idx = current_idx
        else:
            # 保持原有临时低点

            # 检查是否突破上轨 -> 趋势反转
            if current_high > current_ub:
                # 确认前序低点
                new_point = (g_temp_lp_idx, g_temp_lp, 'L')
                g_confirmed_points.append(new_point)
                api.log(f"[{current_idx}] 确认低点: {g_temp_lp}, 趋势转升")

                # 切换状态
                g_trend_state = 'UP'
                g_temp_hp = current_high
                g_temp_hp_idx = current_idx

                # 清洗点
                g_confirmed_points = clean_points(g_confirmed_points, clean_interval)

    # 6. HSAR 阻力位识别
    # 每次有新点确认或定期重新计算
    if len(g_confirmed_points) > 0:
        res_price = identify_resistance_hsar(g_confirmed_points, hsar_m, hsar_q)
        if res_price is not None:
            g_resistance_price = res_price
            # api.log(f"[{current_idx}] 当前阻力位: {g_resistance_price:.2f}")
        # else:
        #     api.log(f"[{current_idx}] 未找到有效阻力位")

    # 7. 计算 ATR (用于止损)
    # 简单 ATR 计算: 这里使用 rolling mean of TR
    tr = pd.DataFrame({
        'hl': high - low,
        'hc': abs(high - close.shift(1)),
        'lc': abs(low - close.shift(1))
    }).max(axis=1)
    atr = tr.rolling(atr_period).mean()
    current_atr = atr.iloc[-1]

    if pd.isna(current_atr):
        return

    # 8. 交易逻辑
    pos = api.get_pos()

    # --- 开仓逻辑 ---
    if pos == 0 and g_resistance_price > 0:
        # 突破阻力位 3%
        if current_close > g_resistance_price * (1 + breakout_pct):
            api.buy(volume=1, order_type='next_bar_open', reason=f'突破阻力位 {g_resistance_price:.2f}')
            api.log(f"[{current_idx}] 买入开多! 收盘价:{current_close:.2f}, 阻力位:{g_resistance_price:.2f}")

    # --- 止损/止盈逻辑 (2*ATR 跟踪止损) ---
    elif pos > 0:
        # 获取入场价格 (需要自己记录，这里简化假设用最近一次买入价，实际应全局记录)
        # 由于SSQuant API没有直接获取平均持仓成本的完美方法(回测中可能复杂)，
        # 我们使用一个简单的跟踪止损逻辑：
        # 止损价 = Max(历史最高收盘价 - 2*ATR, 初始止损价)

        # 为了简化，我们使用全局变量记录持仓期间的最高收盘价
        if not hasattr(strategy, 'g_long_highest_close'):
            strategy.g_long_highest_close = current_close
            strategy.g_long_stop_price = current_close - atr_mult * current_atr
        else:
            strategy.g_long_highest_close = max(strategy.g_long_highest_close, current_close)
            # 更新止损价：只升不降
            new_stop = strategy.g_long_highest_close - atr_mult * current_atr
            if new_stop > strategy.g_long_stop_price:
                strategy.g_long_stop_price = new_stop

        # 检查止损
        if current_close < strategy.g_long_stop_price:
            api.sell(volume=None, order_type='next_bar_open', reason='ATR跟踪止损')
            api.log(f"[{current_idx}] 多头止损平仓. 现价:{current_close:.2f}, 止损价:{strategy.g_long_stop_price:.2f}")
            # 重置状态
            delattr(strategy, 'g_long_highest_close')
            delattr(strategy, 'g_long_stop_price')

    # 注意：本策略主要为多头突破，若需做空可对称添加逻辑


# ============== 主函数 ==============
if __name__ == "__main__":
    # ========== 运行模式 ==========
    RUN_MODE = RunMode.BACKTEST

    # ========== 策略参数 ==========
    strategy_params = {
        'bb_window': 20,
        'bb_k': 1.0,
        'clean_interval': 4,
        'hsar_m': 10,
        'hsar_q': 2,
        'breakout_pct': 0.03,  # 3%
        'atr_period': 14,
        'atr_mult': 2.0,
    }

    # ========== 配置 ==========
    config = get_config(RUN_MODE,
        symbol='rb888',
        kline_period='1d',
        adjust_type='1',
        start_date='2020-01-01',
        end_date='2023-12-31',
        initial_capital=100000,
        slippage_ticks=1,
        lookback_bars=500,
    )

    # ========== 运行 ==========
    print(f"\n运行模式: {RUN_MODE.value}")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=strategy,
            initialize=initialize,
            strategy_params=strategy_params
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
