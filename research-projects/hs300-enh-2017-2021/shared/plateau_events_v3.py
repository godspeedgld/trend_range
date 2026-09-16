"""v3 水平带突破事件预计算（strategy_006 开仓信号单一事实源）。

承接 shared/plateau_algo_v3.py（BandBreakout，**v3 已锁定**）——工程化封装，同 plateau_events_v27.py
模式：逐标的跑状态机一遍，抽出 break_up 事件（含 degree/line），缓存 parquet 供策略查表。
算法零改动（import 复用）。无未来：状态机逐 bar 推进，t 日事件仅由 ≤t 的 bar 决定。

事件字段：symbol / date / close_sig（信号日收盘）/ line（被破阻力线=带内点均值）/
         lo / hi（带下/上界）/ degree（带计数=突破程度，**不过滤，≥1 全保留**）。

缓存：shared/plateau_v3_events.parquet（本文件首次落地时由 analysis_007 的事件缓存
v3_events_cache.parquet 转换种子，字段一致；面板更新后删缓存重算）。
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from plateau_algo_v3 import run_band_breakout

CACHE_NAME = "plateau_v3_events.parquet"


def compute_events(panel: pd.DataFrame) -> pd.DataFrame:
    """逐标的跑 v3 状态机 → break_up 事件表（全部 degree）。"""
    rows = []
    panel = panel.sort_values(["symbol", "date"])
    n = panel["symbol"].nunique()
    t0 = time.time()
    for k, (sym, g) in enumerate(panel.groupby("symbol", sort=True), 1):
        if k % 50 == 0 or k == n:
            print(f"  [{k}/{n}] {sym}  elapsed {time.time()-t0:.0f}s", flush=True)
        events, _bands, _tb = run_band_breakout(g)
        for e in events:
            rows.append({"symbol": sym, "date": pd.Timestamp(e["date"]),
                         "close_sig": float(e["close"]), "line": float(e["line"]),
                         "lo": float(e["lo"]), "hi": float(e["hi"]),
                         "degree": int(e["degree"])})
    out = pd.DataFrame(rows, columns=["symbol", "date", "close_sig", "line", "lo", "hi", "degree"])
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_events(panel_path: Path, shared_dir: Path, force: bool = False) -> pd.DataFrame:
    """读缓存；无缓存（或 force）则重算并落盘。"""
    cache = Path(shared_dir) / CACHE_NAME
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    df = compute_events(panel)
    df.to_parquet(cache, index=False)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    ev = load_events(Path(args.panel), Path(__file__).resolve().parent, force=args.force)
    print(f"break_up 事件: {len(ev)} 条, {ev['symbol'].nunique()} 标的, "
          f"{ev['date'].min().date()} ~ {ev['date'].max().date()}")
