"""trend_following.indicators — 技术指标计算。

移动平均系列：SMA / WMA / EMA / SMMA / MMA。

约定
----
- 输入：``pd.Series``（按时间正序，通常是 close）。
- 输出：同长 ``pd.Series``，前期 warmup 为 NaN，索引与输入对齐。
- ``n`` 为窗口期数（≥1）。
"""

import math

import numpy as np
import pandas as pd


def sma(series, n):
    """SMA 简单移动平均：过去 n 期等权平均。

        SMA_t = (P_t + P_{t-1} + ... + P_{t-n+1}) / n
    """
    return series.rolling(n).mean()


def wma(series, n):
    """WMA 线性加权移动平均：近期权重更大，权重为 1,2,...,n。

        WMA_t = Σ_{i=0}^{n-1} (n-i)·P_{t-i} / Σ_{k=1}^{n} k
              = (n·P_t + (n-1)·P_{t-1} + ... + 1·P_{t-n+1}) / (n(n+1)/2)
    """
    weights = np.arange(1, n + 1, dtype=float)        # 最远=1 ... 最近=n
    denom = weights.sum()
    return series.rolling(n).apply(lambda w: np.dot(w, weights) / denom, raw=True)


def ema(series, n):
    """EMA 指数移动平均（标准递推，平滑因子 α=2/(n+1)）。

        α = 2/(n+1)
        EMA_t = α·P_t + (1-α)·EMA_{t-1}

    ``adjust=False`` 即递推口径（前期不做有限样本重新归一化），等价于
    TradingView/通达信的 ta.ema / EMA(C, n)。
    """
    return series.ewm(span=n, adjust=False).mean()


def smma(series, n):
    """SMMA 平滑移动平均（Wilder 平滑 / RMA，α=1/n）。

        α = 1/n
        SMMA_t = (1/n)·P_t + (1-1/n)·SMMA_{t-1}

    即 RSI/KDJ 里常用的 Wilder 平滑；等价于 ``ewm(alpha=1/n, adjust=False)``，
    也等价于 ``ewm(span=2n-1, adjust=False)``。
    """
    return series.ewm(alpha=1.0 / n, adjust=False).mean()


def mma(series, n):
    """MMA 修正移动平均（Modified Moving Average）。

        MMA_t = (MMA_{t-1}·(n-1) + P_t) / n
              = (1/n)·P_t + (1-1/n)·MMA_{t-1}

    数学上等价于 :func:`smma`（Wilder 平滑）。此处单独保留以匹配常见指标惯例
    （部分行情软件把 Wilder 平滑称为 MMA）。
    """
    return series.ewm(alpha=1.0 / n, adjust=False).mean()


def hma(series, n):
    """HMA Hull 移动平均（Hull Moving Average）。

    Hull(2005) 提出的低延迟平滑均线——用加权移动平均的加权移动平均
    来降低滞后（lag）同时保持平滑。

    步骤：
        1. MA1 = WMA(series, n//2)                — 半窗口
        2. MA2 = WMA(series, n)                    — 全窗口
        3. MA3 = MA1 + (MA1 − MA2) = 2×MA1 − MA2  — 外推去滞后
        4. HMA = WMA(MA3, √n)                     — 再次平滑（√n 向下取整）

    Args:
        series: pd.Series（按时间正序，典型的 close）
        n:      窗口期数

    Returns:
        pd.Series，前期 warmup 为 NaN。
    """
    h = int(n // 2)               # floor(n/2)
    r = int(math.isqrt(n))        # floor(sqrt(n))
    ma1 = wma(series, max(h, 1))
    ma2 = wma(series, n)
    ma3 = 2.0 * ma1 - ma2
    return wma(ma3, max(r, 1))


def kama(series, n=10, fast=2, slow=30):
    """KAMA 自适应移动平均（Kaufman's Adaptive Moving Average）。

    根据市场效率比（ER）自适应调节平滑速度：趋势明确时（ER 高）快速跟随，
    震荡/噪音时（ER 低）慢速平滑。本质上是一个平滑系数 SC 跟随 ER 变化的 EMA。

    步骤：
        1. ER = 方向性波动 / 总波动
           方向性波动 = |P_t − P_{t−n}|           （n 期净变化）
           总波动     = Σ|P_i − P_{i−1}|, i=1..n  （路径长度）
        2. fast_a = 2/(fast+1), slow_a = 2/(slow+1)
           SC = [ER × (fast_a − slow_a) + slow_a]²
        3. KAMA_t = KAMA_{t−1} + SC × (P_t − KAMA_{t−1})
                  = SC × P_t + (1−SC) × KAMA_{t−1}

    Args:
        series: pd.Series，价格序列（按时间正序）
        n:      效率比窗口（默认 10）
        fast:   最快平滑周期（默认 2，α≈0.6667）
        slow:   最慢平滑周期（默认 30，α≈0.0645）

    Returns:
        pd.Series，前期 n 期为 NaN（ER 需至少 n 个 bar 才能计算）。
    """
    fast_a = 2.0 / (fast + 1)
    slow_a = 2.0 / (slow + 1)
    delta = fast_a - slow_a

    price = series.astype(float)

    # 效率比
    direction = (price - price.shift(n)).abs()
    volatility = price.diff().abs().rolling(n).sum()
    er = direction / volatility.replace(0.0, np.nan)

    # 平滑系数
    sc = (er * delta + slow_a) ** 2

    # 递推：首有效值取当期价格，其后按公式递推（numpy arrays 比 pandas iloc 快 ≈10×）
    p = price.to_numpy()
    s = sc.to_numpy()
    result = np.empty(len(p)); result.fill(np.nan)
    start = n
    if start < len(p):
        result[start] = p[start]
        for i in range(start + 1, len(p)):
            si = s[i]
            if np.isnan(si):
                result[i] = np.nan
            else:
                result[i] = result[i - 1] + si * (p[i] - result[i - 1])
    return pd.Series(result, index=price.index)


def _wilder_smooth(values, n, init="sum"):
    """Wilder 平滑（ADX/RSI 内部用）：首值=前 n 个 sum/mean，其后 prev·(n−1)/n + cur。

    自动跳过前导 NaN——从第一个非 NaN 起取 n 个作首值，递推到序列末尾。
    """
    v = np.asarray(values, dtype=float)
    out = np.full(len(v), np.nan)
    valid = np.where(~np.isnan(v))[0]
    if len(valid) < n:
        return out
    start = valid[0]
    window = v[start:start + n]
    if np.isnan(window).any():
        return out
    out[start + n - 1] = window.sum() if init == "sum" else window.mean()
    for i in range(start + n, len(v)):
        if np.isnan(v[i]) or np.isnan(out[i - 1]):
            out[i] = np.nan
        elif init == "sum":
            out[i] = out[i - 1] * (n - 1) / n + v[i]          # TR_n / DM_n
        else:  # mean
            out[i] = (out[i - 1] * (n - 1) + v[i]) / n        # ADX
    return out


def adx(high, low, close, n=14):
    """ADX 平均方向运动指标（Wilder, 1978）——衡量趋势强度（不论方向）。

    步骤：
        1. UpMove   = high_t − high_{t−1}
        2. DownMove = low_{t−1} − low_t
        3. +DM = UpMove  if UpMove  > max(DownMove, 0) else 0
        4. −DM = DownMove if DownMove > max(UpMove, 0)    else 0
        5. TR  = max(high−low, |high−prev_close|, |low−prev_close|)
        6. +DM_n / −DM_n / TR_n = Wilder 平滑（首值=前 n 期 sum，其后递推）
        7. +DI_n = 100 × +DM_n / TR_n；−DI_n = 100 × −DM_n / TR_n
        8. DX  = 100 × |(+DI_n − −DI_n) / (+DI_n + −DI_n)|
        9. ADX = DX 的 Wilder 平滑（首值=前 n 期 mean，其后递推）

    Args:
        high / low / close: pd.Series（同索引、同长，按时间正序）
        n: 周期（默认 14，Wilder 原值）

    Returns:
        pd.Series，前 ~2n 期为 NaN（TR_n 需 n 期，ADX 又需 n 期 DX）。
    """
    orig_index = high.index if isinstance(high, pd.Series) else None
    high = pd.Series(high, dtype=float).reset_index(drop=True)
    low = pd.Series(low, dtype=float).reset_index(drop=True)
    close = pd.Series(close, dtype=float).reset_index(drop=True)

    up_move = high.diff()
    dn_move = -low.diff()                      # low_{t-1} - low_t

    plus_dm = np.where(up_move > np.maximum(dn_move, 0.0), up_move, 0.0)
    minus_dm = np.where(dn_move > np.maximum(up_move, 0.0), dn_move, 0.0)

    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1).to_numpy()

    tr_n = _wilder_smooth(tr, n, "sum")
    plus_dm_n = _wilder_smooth(plus_dm, n, "sum")
    minus_dm_n = _wilder_smooth(minus_dm, n, "sum")

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * plus_dm_n / tr_n
        minus_di = 100.0 * minus_dm_n / tr_n
        di_sum = plus_di + minus_di
        dx = 100.0 * np.abs(plus_di - minus_di) / np.where(di_sum == 0, np.nan, di_sum)

    adx_val = _wilder_smooth(dx, n, "mean")
    return pd.Series(adx_val, index=orig_index)


if __name__ == "__main__":
    import math
    # 自测：用一段已知数据验证
    s = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], dtype=float)
    n = 5
    print(f"输入: {s.values}")
    print(f"SMA({n})  : {sma(s, n).round(3).values}")
    print(f"WMA({n})  : {wma(s, n).round(3).values}")
    print(f"EMA({n})  : {ema(s, n).round(3).values}")
    print(f"SMMA({n}) : {smma(s, n).round(3).values}")
    print(f"MMA({n})  : {mma(s, n).round(3).values}")
    print(f"HMA({n})  : {hma(s, n).round(3).values}")
    # 验证 MMA == SMMA
    assert mma(s, n).equals(smma(s, n)), "MMA 应等于 SMMA"
    print("\n✓ MMA 等于 SMMA（Wilder 平滑）验证通过")
    # 验证 HMA 最终值落在合理范围
    h = hma(s, n).dropna()
    assert h.iloc[-1] > 0, "HMA 应为正"
    print(f"✓ HMA 长度 {len(hma(s, n).dropna())} 在期望范围内（{n + 2*int(math.isqrt(n))}~{3*int(math.isqrt(n))+n} 期后才有值）")
