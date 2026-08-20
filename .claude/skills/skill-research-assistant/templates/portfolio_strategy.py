"""组合策略模板 — 开仓池/平仓池引擎的 5 个策略接口。

引擎固定框架（见 scripts/local_portfolio_backtest.py）：
  每日收盘：持仓平仓检查 → 开仓池剔除 → 入场扫描
  次日开盘：平仓池卖出 + 持仓<n 时从开仓池按优先顺序开仓（权重 1/n）

本模板给出 5 个接口的**可运行默认实现**，标注"可替换点"。
按不同策略修改对应函数即可，引擎框架不动。
"""
import pandas as pd


# ═══════════════════════════════════════════════════════════
# 接口①：入场信号（入选逻辑）
# ═══════════════════════════════════════════════════════════

def entry_signal(hist_df: pd.DataFrame) -> bool:
    """t 日是否触发入场信号（收盘判定，次日开盘买入）。

    hist_df: 该标的截至 t 日（含）的全部历史（date,open,high,low,close,...）
    无未来数据：只用 ≤t 日。

    【可替换点】默认实现：双均线金叉（ma5 上穿 ma20）。
    长江平台突破版：转折点识别 + HSAR 阻力位 + 收盘 > 阻力位×1.03。
    """
    if len(hist_df) < 21:
        return False
    close = hist_df["close"]
    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    return bool(ma5.iloc[-1] > ma20.iloc[-1] and ma5.iloc[-2] <= ma20.iloc[-2])


# ═══════════════════════════════════════════════════════════
# 接口②：平仓检查（剔出逻辑）
# ═══════════════════════════════════════════════════════════

def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """持仓股是否触发平仓（收盘判定，次日开盘卖出）。

    entry_info: {"entry_date", "entry_price", "peak", "weight"}（引擎维护）
    hist_df: 该标的截至 t 日历史

    【可替换点】默认实现：滚动回撤 10% 或持有超 45 天。
    """
    import numpy as np
    if len(hist_df) == 0:
        return True
    c = hist_df["close"].iloc[-1]
    peak = entry_info.get("peak", entry_info["entry_price"])
    if peak and peak > 0 and c / peak - 1.0 < -0.10:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(entry_info["entry_date"])).days
    return days > 45


# ═══════════════════════════════════════════════════════════
# 接口③（可选）：开仓池剔除
# ═══════════════════════════════════════════════════════════

def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """开仓池中的股票是否剔除（未开仓但信号失效）。

    【可替换点】默认：信号后 10 日内未开仓（超时）或回撤 10% 剔除。
    返回 None/False 保留（也可不定义此函数，引擎跳过剔除）。
    """
    if len(hist_df) == 0:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(signal_date)).days
    if days > 10:
        return True
    c = hist_df["close"].iloc[-1]
    sig_close = hist_df.loc[hist_df["date"] == signal_date, "close"]
    if len(sig_close) and sig_close.iloc[0] > 0:
        if c / sig_close.iloc[0] - 1.0 < -0.10:
            return True
    return False


# ═══════════════════════════════════════════════════════════
# 接口④：开仓优先选择
# ═══════════════════════════════════════════════════════════

def select_order(open_pool: dict) -> list:
    """持仓 < n 时，从开仓池选股的优先顺序。

    open_pool: {symbol: {"signal_date", ...}}（入场信号时的信息）

    【可替换点】默认：突破（信号）时间最近优先。
    其他：信号强度 / 因子值 / 流动性等排序。
    """
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


# ═══════════════════════════════════════════════════════════
# 接口⑤（可选）：单股权重
# ═══════════════════════════════════════════════════════════

def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """单股目标权重（开仓时确定）。

    【可替换点】默认：等比 1/n。
    未来：等波动率（1/σ 归一化）、因子值加权等。
    """
    return 1.0 / n
