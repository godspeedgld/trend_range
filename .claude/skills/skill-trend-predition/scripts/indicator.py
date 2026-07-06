"""趋势预测用指标与标签计算。

纯计算模块（输入 OHLCV Series/DataFrame，输出对齐的 pd.Series）。
包含：ATR / ADX / Hurst(R-S) / MACD / HMA / 对数收益 / close-vol 比 / 前瞻 3 分类趋势标签。

Wilder 平滑用标准 SMMA（首值 = 前 n 个连续有效值均值；之后 y[t]=y[t-1]·(n-1)/n + x[t]/n）。
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
# Wilder SMMA（标准种子）
# ────────────────────────────────────────────────────────────
def _wilder_smma(x: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑移动平均（SMMA）。

    首个值 = 前 n 个连续有效值的均值；之后 y[t] = y[t-1]·(n-1)/n + x[t]/n。
    前导 NaN 自动跳过；输出对齐原 index（warmup 区为 NaN，符合 Wilder 定义）。
    """
    x = pd.Series(x).astype(float)
    out = pd.Series(np.nan, index=x.index, dtype=float)
    a = x.to_numpy()
    nv = len(a)
    start = None
    for i in range(nv - n + 1):  # 第一个长度为 n 的全有效窗口
        if not np.isnan(a[i:i + n]).any():
            start = i
            break
    if start is None:
        return out
    prev = float(a[start:start + n].mean())
    out.iloc[start + n - 1] = prev
    for t in range(start + n, nv):
        v = a[t]
        if np.isnan(v):
            continue
        prev = prev * (n - 1) / n + v / n
        out.iloc[t] = prev
    return out


# ────────────────────────────────────────────────────────────
# ATR / ADX
# ────────────────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder ATR（= TR 的 SMMA）。"""
    pc = close.shift()
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return _wilder_smma(tr, n)


def _di_dx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14, smooth=None):
    """ADX 内部：用 `smooth(series, n)` 平滑 DM/TR 得到 DI，返回 (plus_di, minus_di, dx)。

    smooth 默认 _wilder_smma（标准）；可传 hma 做低延迟变体。
    """
    if smooth is None:
        smooth = _wilder_smma
    up = high.diff()
    down = -low.diff()
    plus_dm = (((up > down) & (up > 0)) * up).clip(lower=0.0)
    minus_dm = (((down > up) & (down > 0)) * down).clip(lower=0.0)
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    tr_n = smooth(tr, n)
    plus_di = 100 * smooth(plus_dm, n) / tr_n.replace(0, np.nan)
    minus_di = 100 * smooth(minus_dm, n) / tr_n.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    dx = dx.replace([np.inf, -np.inf], np.nan)
    return plus_di, minus_di, dx


def _adx_parts(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """ADX 内部：返回 (adx, plus_di, minus_di)。ADX = Wilder SMMA(dx)。"""
    plus_di, minus_di, dx = _di_dx(high, low, close, n)
    return _wilder_smma(dx, n), plus_di, minus_di


def adx(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder ADX（趋势强度，>25 通常视为有趋势）。warmup 区（约前 2n 根）为 NaN。"""
    return _adx_parts(high, low, close, n)[0]


def adx_components(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """返回 (adx, plus_di, minus_di)，便于副图同时画 ADX + DI+ / DI−。"""
    return _adx_parts(high, low, close, n)


def adx_hma(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """低延迟 ADX：DX→ADX 的 Wilder SMMA 改为 HMA；DI+/DI− 保持标准 Wilder SMMA。

    为何 DI 不也用 HMA：DI = 100·DM_n/TR_n 是**比率**，需 DM_n/TR_n 非负。HMA 含
    `2·WMA(n/2)−WMA(n)` 外推减法，对稀疏的 DM（多 0 带尖峰）会产出**负值**，使 DI/DX 失效
    （实测全 HMA 版与标准 ADX corr≈0.09、ADX>25 占比畸高至 85%）。故 DM/TR 平滑必须用
    正性保持的 Wilder SMMA；HMA 只作用于稠密有界的 DX∈[0,100]。
    """
    _, _, dx = _di_dx(high, low, close, n)  # DI 走标准 Wilder
    return hma(dx, n)


def adx_hma_components(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """返回 (adx_hma, plus_di, minus_di)；ADX=HMA(DX)，DI 标准 Wilder。"""
    plus_di, minus_di, dx = _di_dx(high, low, close, n)
    return hma(dx, n), plus_di, minus_di


def adx_diff_hma(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    """方向性低延迟趋势强度（带符号）：HMA 平滑 (DI+ − DI−)。

    与标准 ADX 的区别：
      ① 不用 |DI+−DI−|/(DI++DI−) 比值，而用**原始差值** DI+−DI−（幅度更陡、未归一）；
      ② **保留方向符号**：>0 多头主导、<0 空头主导、绝对值=强度；
      ③ HMA 平滑，低延迟。
    DI+−DI− 稠密有界（约 [−100,100]），HMA 可安全作用（与稀疏的 DM 不同，不会因外推失效）。
    """
    plus_di, minus_di, _ = _di_dx(high, low, close, n)
    return hma(plus_di - minus_di, n)


def adx_diff_hma_components(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14):
    """返回 (adx_diff_hma, plus_di, minus_di)。"""
    plus_di, minus_di, _ = _di_dx(high, low, close, n)
    return hma(plus_di - minus_di, n), plus_di, minus_di


def kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9, m1: int = 3, m2: int = 3):
    """KDJ：RSV=(C−low_n)/(high_n−low_n)·100；K=SMA(RSV,m1)；D=SMA(K,m2)；J=3K−2D。返回 (K,D,J)。"""
    low_n = low.rolling(n).min()
    high_n = high.rolling(n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


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
    "adx_components",
    "adx_hma",
    "adx_hma_components",
    "adx_diff_hma",
    "adx_diff_hma_components",
    "kdj",
    "hurst_rs",
    "hurst_rolling",
    "macd",
    "hma",
    "log_return",
    "close_vol_ratio",
    "trend_label",
]
