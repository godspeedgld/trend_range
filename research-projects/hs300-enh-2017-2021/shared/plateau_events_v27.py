"""v2.7 趋势线突破事件预计算（strategy_005 开仓信号单一事实源）。

承接 shared/plateau_algo_v2.py（v2.7 TrendlineBreakout，冻结）——本文件只做**工程化封装**：
逐标的运行该状态机一遍，抽出 break_up 事件（symbol, date），缓存 parquet 供策略查表执行。
算法本身零改动（import 复用，不复制内联）。

为什么预计算查表：
  · 引擎每日对每只非持仓股调 entry_signal，逐日重跑 O(N²) 状态机不可行
  · 状态机逐 bar 增量推进，t 日事件仅由 ≤t 的 bar 决定——预计算**不引入未来数据**，
    查表 (symbol, date) 与"当日收盘跑一遍算法"结果完全一致

缓存：shared/plateau_v27_breakup_events.parquet（列 symbol/date/event；break_up 事件）。
面板数据更新后删除缓存或 --force 重算。

用法：
  python shared/plateau_events_v27.py --panel <panel.parquet> [--force]   # 重算并写缓存
  from plateau_events_v27 import load_breakup_events                      # 策略侧（有缓存直接读）
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from plateau_algo_v2 import TrendlineBreakout

CACHE_NAME = "plateau_v27_breakup_events.parquet"
META_NAME = "plateau_v27_breakup_events_meta.json"


def compute_breakup_events(panel: pd.DataFrame) -> pd.DataFrame:
    """逐标的跑 v2.7 状态机 → break_up 事件表（symbol, date, event）。

    panel 需含 date/symbol/open/high/low/close（升序任意，内部按 symbol+date 排）。
    """
    rows = []
    panel = panel.sort_values(["symbol", "date"])
    n = panel["symbol"].nunique()
    t0 = time.time()
    for k, (sym, g) in enumerate(panel.groupby("symbol", sort=True), 1):
        if k % 50 == 0 or k == n:
            print(f"  [{k}/{n}] {sym}  elapsed {time.time()-t0:.0f}s", flush=True)
        tb = TrendlineBreakout()
        for r in g.itertuples():
            ev = tb.feed({"date": r.date, "open": r.open, "high": r.high,
                          "low": r.low, "close": r.close})
            if ev is not None and ev["type"] == "break_up":
                rows.append({"symbol": sym, "date": pd.Timestamp(r.date),
                             "event": "break_up"})
    out = pd.DataFrame(rows, columns=["symbol", "date", "event"])
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def load_breakup_events(panel_path: Path, shared_dir: Path,
                        force: bool = False) -> pd.DataFrame:
    """读缓存；无缓存（或 force）则重算并写缓存 + meta。"""
    cache = Path(shared_dir) / CACHE_NAME
    meta_p = Path(shared_dir) / META_NAME
    panel_path = Path(panel_path)
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    df = compute_breakup_events(panel)
    df.to_parquet(cache, index=False)
    meta_p.write_text(json.dumps({
        "panel": str(panel_path), "panel_rows": int(len(panel)),
        "n_symbols": int(panel["symbol"].nunique()),
        "n_breakup_events": int(len(df)),
        "date_min": str(df["date"].min().date()) if len(df) else None,
        "date_max": str(df["date"].max().date()) if len(df) else None,
        "algo": "plateau_algo_v2.TrendlineBreakout (v2.7)",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", required=True, help="宽表面板 parquet 路径")
    ap.add_argument("--force", action="store_true", help="忽略缓存重算")
    args = ap.parse_args()
    shared = Path(__file__).resolve().parent
    ev = load_breakup_events(Path(args.panel), shared, force=args.force)
    print(f"break_up 事件: {len(ev)} 条, {ev['symbol'].nunique()} 标的, "
          f"{ev['date'].min().date()} ~ {ev['date'].max().date()}")
