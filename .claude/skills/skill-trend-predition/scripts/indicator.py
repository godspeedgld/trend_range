"""趋势预测用指标与标签计算。

纯计算模块（输入 OHLCV Series/DataFrame，输出对齐的 pd.Series）。
包含：ATR / ADX / Hurst(R-S) / MACD / HMA / 对数收益 / close-vol 比 / 前瞻 3 分类趋势标签。

Wilder 平滑统一用 ewm(alpha=1/n, adjust=False)（与 Wilder SMMA 等价的常用实现，warmup 后误差可忽略）。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


# ────────────────────────────────────────────────────────────
# 输入规整
# ────────────────────────────────────────────────────────────
def extract_ohlcv(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """从 DataFrame 提取 (close, high, low, vol)，列名大小写不敏感；缺失用 close 近似。"""
    def pick(*names):
        for n in names:
            if n in df.columns:
                return df[n].astype(float)
        return None
    close = pick("close", "Close", "CLOSE")
    if close is None:
        raise ValueError("data 必须含 close 列")
    high = pick("high", "High")
    if high is None:
        high = close.copy()
    low = pick("low", "Low")
    if low is None:
        low = close.copy()
    vol = pick("vol", "volume", "Volume")
    if vol is None:
        vol = pd.Series(np.ones(len(close)), index=close.index, dtype=float)
    return close, high, low, vol


# ────────────────────────────────────────────────────────────
# ATR / ADX
# ────────────────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder ATR。"""
    pc = close.shift()
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder ADX（趋势强度，>25 通常视为有趋势）。"""
    up = high.diff()
    down = -low.diff()
    plus_dm = (((up > down) & (up > 0)) * up).clip(lower=0.0)
    minus_dm = (((down > up) & (down > 0)) * down).clip(lower=0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr_ = tr.ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / atr_
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


# ────────────────────────────────────────────────────────────
# Hurst (R/S)
# ────────────────────────────────────────────────────────────
def hurst_rs(series: pd.Series | np.ndarray, max_lag: int | None = None) -> float:
    """经典 R/S 法 Hurst 指数。>0.5 持续(趋势)，≈0.5 随机，<0.5 反持久。"""
    s = np.asarray(series, dtype=float)
    s = s[np.isfinite(s)]
    n = len(s)
    if n < 30:
        return float("nan")
    if max_lag is None:
        max_lag = n // 2
    lags = np.unique(np.geomspace(10, min(max_lag, n - 1), num=20).astype(int))
    lags = lags[(lags >= 4) & (lags < n)]
    pts = []
    for lag in lags:
        m = n // lag
        if m < 1:
            continue
        rs = []
        for i in range(m):
            block = s[i * lag:(i + 1) * lag]
            adj = block - block.mean()
            cum = np.cumsum(adj)
            r = cum.max() - cum.min()
            sd = block.std(ddof=1)
            if sd > 0:
                rs.append(r / sd)
        if rs:
            pts.append((lag, float(np.mean(rs))))
    if len(pts) < 3:
        return float("nan")
    x = np.log([p[0] for p in pts])
    y = np.log([p[1] for p in pts])
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def hurst_rolling(series: pd.Series, window: int = 200) -> pd.Series:
    """滚动 Hurst（每个窗口上跑 R/S），用于特征。"""
    s = pd.Series(series).astype(float)
    out = s.rolling(window).apply(lambda x: hurst_rs(x), raw=True)
    return out


# ────────────────────────────────────────────────────────────
# MACD / HMA / 收益 / close-vol
# ────────────────────────────────────────────────────────────
def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD：返回 (macd_line, signal_line, hist)。"""
    ema_f = close.ewm(span=fast, adjust=False).mean()
    ema_s = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_f - ema_s
    sig = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig
    return macd_line, sig, hist


def _wma(s: pd.Series, n: int) -> pd.Series:
    weights = np.arange(1, n + 1, dtype=float)
    return s.rolling(n).apply(lambda x: (x * weights).sum() / weights.sum(), raw=True)


def hma(close: pd.Series, n: int = 20) -> pd.Series:
    """Hull 移动平均。"""
    half = max(n // 2, 1)
    sqrt_n = max(int(np.sqrt(n)), 1)
    return _wma(2 * _wma(close, half) - _wma(close, n), sqrt_n)


def log_return(close: pd.Series) -> pd.Series:
    return np.log(close).diff()


def close_vol_ratio(close: pd.Series, vol: pd.Series) -> pd.Series:
    """ln(close) − ln(vol)。"""
    return np.log(close) - np.log(vol.replace(0, np.nan))


# ────────────────────────────────────────────────────────────
# 前瞻 3 分类趋势标签（ground truth）
# ────────────────────────────────────────────────────────────
def trend_label(
    close: pd.Series,
    high: Optional[pd.Series] = None,
    low: Optional[pd.Series] = None,
    horizon: int = 10,
    k: float = 1.5,
    atr_n: int = 14,
) -> pd.Series:
    """前瞻 3 分类标签：未来 horizon 天收益 |r| > k×ATR → 上行(+1)/下行(−1)，否则震荡(0)。

    末尾 horizon 个点无未来收益 → NaN（使用时丢弃）。
    """
    close = pd.Series(close).astype(float)
    if high is not None and low is not None:
        a = atr(high, low, close, atr_n)
    else:
        a = close.diff().abs().rolling(atr_n).mean()  # 无 high/low 时的 ATR 代理
    fwd = close.shift(-horizon) / close - 1.0
    thr = k * a / close  # 相对 ATR（与 fwd 同为比率，避免量纲错配）
    label = np.sign(fwd).where(fwd.abs() > thr, 0.0)
    return label


__all__ = [
    "extract_ohlcv",
    "atr",
    "adx",
    "hurst_rs",
    "hurst_rolling",
    "macd",
    "hma",
    "log_return",
    "close_vol_ratio",
    "trend_label",
]
