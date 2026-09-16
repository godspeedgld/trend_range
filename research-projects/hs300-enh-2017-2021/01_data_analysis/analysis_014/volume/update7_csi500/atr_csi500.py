"""更新七专用 ATR(14) —— **独立缓存，绝不复用 shared/atr14_panel.parquet**。

⚠ 踩过的坑（2026-09-15）：`shared/atr14_precompute.load_atr14(panel_path, SHARED)` 会**优先读全局
缓存** `shared/atr14_panel.parquet`，而那个缓存是用沪深300 面板建的 —— 传 CSI500 面板进去它照样
返回 HS300 的 ATR（668 只），**中证500 独有的 688 只全为 NaN**。后果：
  · build_trades：18,478 条事件因 ATR 缺失被静默丢弃（28,137 → 判 9,582）
  · W2 策略：ATR_PIV 查不到 → 吊灯止损（离场②）与池失效条件②**全部静默失效**
故本目录自建缓存，算法与 `shared/atr14_precompute.compute_atr14` **逐字一致**（Wilder ewm α=1/14）。

用法（幂等，缓存存在则直接读）：
  from atr_csi500 import load_atr_csi500
  atr = load_atr_csi500(HERE)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ATR_N = 14
CACHE = "atr14_csi500.parquet"


def compute_atr14(panel: pd.DataFrame) -> pd.DataFrame:
    """与 shared/atr14_precompute.compute_atr14 逐字一致（Wilder ATR）。"""
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


def load_atr_csi500(here: Path, force: bool = False) -> pd.DataFrame:
    cache = Path(here) / CACHE
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    panel = pd.read_parquet(Path(here) / "_market_csi500_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    df = compute_atr14(panel)
    df.to_parquet(cache, index=False)
    print(f"ATR14 独立缓存: {len(df):,} 行 / {df['symbol'].nunique()} 只 / "
          f"非空 {df['atr14'].notna().mean()*100:.1f}% -> {CACHE}")
    return df


if __name__ == "__main__":
    import sys
    here = Path(__file__).resolve().parent
    load_atr_csi500(here, force="--force" in sys.argv)
