"""ATR(14) 全面板预计算（strategy_005 更新一：吊灯止盈依赖，单一事实源）。

Wilder ATR：TR_t = max(high−low, |high−close_{t−1}|, |low−close_{t−1}|)
             ATR = TR.ewm(alpha=1/14, adjust=False)，min_periods=14（前 13 根 NaN）
首根无前收盘 → TR = high−low。

无未来：ATR(t) 只用 ≤t 的 bar（ewm 因子全部落在历史侧）。
缓存：shared/atr14_panel.parquet（symbol/date/atr14，长表）。面板更新后删缓存或 --force。

用法：
  python shared/atr14_precompute.py --panel <panel.parquet> [--force]
  from atr14_precompute import load_atr14          # 策略侧（有缓存直接读）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

CACHE_NAME = "atr14_panel.parquet"
META_NAME = "atr14_panel_meta.json"
ATR_N = 14


def compute_atr14(panel: pd.DataFrame) -> pd.DataFrame:
    """逐标的向量化 ATR(14) → 长表（symbol, date, atr14）。"""
    panel = panel.sort_values(["symbol", "date"])
    out = []
    for sym, g in panel.groupby("symbol", sort=True):
        h, l, c = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
        prev_c = pd.Series(c).shift(1).to_numpy()
        tr = pd.Series(
            [h[0] - l[0]] + [max(h[i] - l[i],
                                  abs(h[i] - prev_c[i]),
                                  abs(l[i] - prev_c[i])) for i in range(1, len(g))])
        atr = tr.ewm(alpha=1.0 / ATR_N, adjust=False, min_periods=ATR_N).mean()
        out.append(pd.DataFrame({"symbol": sym, "date": g["date"].to_numpy(),
                                 "atr14": atr.to_numpy()}))
    return pd.concat(out, ignore_index=True)


def load_atr14(panel_path: Path, shared_dir: Path, force: bool = False) -> pd.DataFrame:
    """读缓存；无缓存（或 force）则重算并写缓存 + meta。"""
    cache = Path(shared_dir) / CACHE_NAME
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(panel_path)
    panel["date"] = pd.to_datetime(panel["date"])
    df = compute_atr14(panel)
    df.to_parquet(cache, index=False)
    (Path(shared_dir) / META_NAME).write_text(json.dumps({
        "panel": str(panel_path), "rows": int(len(df)),
        "n_symbols": int(df["symbol"].nunique()),
        "method": f"Wilder ewm(alpha=1/{ATR_N}), min_periods={ATR_N}",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    df = load_atr14(Path(args.panel), Path(__file__).resolve().parent, force=args.force)
    print(f"ATR14: {len(df)} rows, {df['symbol'].nunique()} symbols, "
          f"非空 {df['atr14'].notna().mean()*100:.1f}%")
