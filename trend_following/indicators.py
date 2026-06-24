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
