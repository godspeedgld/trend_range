"""突破价过去一年十分位预计算（strategy_008 开仓过滤单一事实源）。

口径（同 analysis_011）：
  decile(sym, t) = 信号日 t 收盘 C_t 在该股过去 252 个交易日（含 t）收盘分布中的分位档
    pct = mean(窗口收盘 < C_t)；decile = int(pct×10)+1（1=最低10%，10=最高10%）

设计：
  - 只需在【v3 突破事件日】算（strategy 无事件直接不开仓，分位仅在有事件时查）
    → 逐事件查该股 ≤t 最近 252 根，数量 ~1.5 万，秒级完成（无需全面板滚动分位）
  - 事件集用 2015 全面板算（shared/plateau_events_v3.py 同源）
  - 缓存：shared/decile252.parquet（symbol/date/decile，仅事件日）
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

WINDOW = 252
CACHE_NAME = "decile252.parquet"


def _decile_at(close: pd.Series, idx: int, window: int) -> int:
    """close: 该股全历史（date index 位置 idx 为事件日）。返回事件日收盘的十分位。"""
    c = close.to_numpy(float)
    lo = max(0, idx - window + 1)
    win = c[lo:idx + 1]
    pct = float((win < c[idx]).mean())
    return min(int(pct * 10) + 1, 10)


def compute_deciles(panel: pd.DataFrame, events: pd.DataFrame,
                    window: int = WINDOW) -> pd.DataFrame:
    """逐事件算十分位 → DataFrame(symbol, date, decile)。events 需含 symbol/date。"""
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    events = events.copy()
    events["date"] = pd.to_datetime(events["date"])
    by_sym = {s: g.set_index("date")["close"].astype(float).sort_index()
              for s, g in panel.groupby("symbol")}
    rows = []
    for r in events.itertuples():
        g = by_sym.get(r.symbol)
        if g is None or r.date not in g.index:
            continue
        i = g.index.get_loc(r.date)
        rows.append((r.symbol, pd.Timestamp(r.date), _decile_at(g, i, window)))
    return (pd.DataFrame(rows, columns=["symbol", "date", "decile"])
            .sort_values(["symbol", "date"]).reset_index(drop=True))


def load_deciles(panel_path: Path, shared_dir: Path, events_path: Path,
                 force: bool = False) -> pd.DataFrame:
    """读缓存；无缓存（或 force）则重算并落盘。events_path = plateau_v3_events.parquet。"""
    cache = Path(shared_dir) / CACHE_NAME
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(panel_path)
    events = pd.read_parquet(events_path)
    df = compute_deciles(panel, events)
    df.to_parquet(cache, index=False)
    return df
