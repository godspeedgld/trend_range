"""个股 LLT(60) 牛熊预计算（strategy_007 开仓闸门单一事实源）。

LLT 递推同源：replication/短线择时策略研究之三.../reference_implementation.llt
（广发研报二二阶低通滤波，α=2/(d+1)）。切线斜率 k=LLT 一阶差分；k>0 = 该股当日多头。

预计算用 2015 全面板（非回测 2017 面板）：LLT 递推初值影响按 (1−α)^t 衰减，
2015-01 起算到回测首信号日（2017-04）已 550+ bar，初值完全消失（若用 2017 面板，
首 60~90 信号日的斜率仍含初值污染）。回测策略只查表（symbol, date）→ bool。

缓存：shared/llt60_bull.parquet（symbol/date/llt_bull）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

LLT_D = 60
CACHE_NAME = "llt60_bull.parquet"


def _llt(close: pd.Series, d: int) -> pd.Series:
    """LLT 低延迟趋势线（研报二式二阶低通递推；初值 C[0]/C[1]，耗散收敛）。"""
    alpha = 2.0 / (d + 1)
    c = close.to_numpy(float)
    n = len(c)
    out = np.full(n, np.nan)
    if n < 3:
        return pd.Series(out, index=close.index)
    a2 = alpha * alpha
    b0, b1, b2 = alpha - a2 / 4, a2 / 2, alpha - 3 * a2 / 4
    out[0], out[1] = c[0], c[1]
    for t in range(2, n):
        out[t] = (b0 * c[t] + b1 * c[t - 1] - b2 * c[t - 2]
                  + 2 * (1 - alpha) * out[t - 1] - (1 - alpha) ** 2 * out[t - 2])
    return pd.Series(out, index=close.index)


def compute_llt60(panel: pd.DataFrame) -> pd.DataFrame:
    """逐股 LLT(60) 斜率>0 → DataFrame(symbol, date, llt_bull)。"""
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    rows = []
    for sym, g in panel.sort_values(["symbol", "date"]).groupby("symbol", sort=True):
        k = _llt(g.set_index("date")["close"], LLT_D).diff()
        bull = k > 0
        for d_, b in bull.items():
            rows.append((sym, d_, bool(b)))
    out = pd.DataFrame(rows, columns=["symbol", "date", "llt_bull"])
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_llt60(panel_path: Path, shared_dir: Path, force: bool = False) -> pd.DataFrame:
    """读缓存；无缓存（或 force）则重算并落盘。"""
    cache = Path(shared_dir) / CACHE_NAME
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(panel_path)
    df = compute_llt60(panel)
    df.to_parquet(cache, index=False)
    return df
