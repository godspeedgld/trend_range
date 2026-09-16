"""更新三前置 — v4 事件级 COMBO 表（expanding 严格因果，无未来）。

对 plateau v4 全部事件（deg≤5，v4_events.parquet）计算信号日量能特征并按日期排序
expanding 标定 z：第 i 笔事件的 μ/σ 只用 [0, i) 的事件（burn-in 前 500 笔 COMBO=NaN，
不产生信号）。产物 events_combo.parquet（symbol/date/line/close_sig/degree/COMBO/RV/UDVR）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]                      # hs300-enh-2017-2021
V4 = PROJ / "01_data_analysis/analysis_012/v4_backtest/v4_events.parquet"
PANEL = PROJ / "_market_hs300_panel.parquet"
BURN = 500


def main():
    ev = pd.read_parquet(V4)
    ev["date"] = pd.to_datetime(ev["date"])
    ev = ev[ev["degree"] <= 5].sort_values("date").reset_index(drop=True)

    pan = pd.read_parquet(PANEL, columns=["date", "symbol", "close", "volume"])
    pan["date"] = pd.to_datetime(pan["date"])
    pan = pan.sort_values(["symbol", "date"])
    pan["ma_vol20"] = pan.groupby("symbol")["volume"].transform(lambda v: v.rolling(20).mean())
    up = pan["close"] > pan.groupby("symbol")["close"].shift(1)
    pan["up_vol"] = np.where(up, pan["volume"], 0.0)
    g = pan.groupby("symbol")
    pan["sum_vol20"] = g["volume"].transform(lambda v: v.rolling(20).sum())
    pan["sum_upvol20"] = g["up_vol"].transform(lambda v: v.rolling(20).sum())
    pan["RV"] = pan["volume"] / pan["ma_vol20"]
    pan["UDVR"] = pan["sum_upvol20"] / pan["sum_vol20"]
    feats = pan.set_index(["symbol", "date"])[["RV", "UDVR"]]

    ev = ev.join(feats, on=["symbol", "date"])
    n0 = len(ev)
    ev = ev.dropna(subset=["RV", "UDVR"]).sort_values("date").reset_index(drop=True)
    ev["lrv"] = np.log(ev["RV"].replace([np.inf, -np.inf], np.nan))
    ev = ev.dropna(subset=["lrv"]).reset_index(drop=True)
    print(f"事件 {n0} → 可配量能 {len(ev)}")

    mu_u = ev["UDVR"].expanding().mean().shift(1)
    sd_u = ev["UDVR"].expanding().std().shift(1)
    mu_r = ev["lrv"].expanding().mean().shift(1)
    sd_r = ev["lrv"].expanding().std().shift(1)
    ev["COMBO"] = (ev["UDVR"] - mu_u) / sd_u - (ev["lrv"] - mu_r) / sd_r
    ev.loc[: BURN - 1, "COMBO"] = np.nan          # burn-in：前 500 笔不产生信号
    ev = ev[["symbol", "name", "date", "close_sig", "line", "degree", "COMBO", "RV", "UDVR"]]
    ev.to_parquet(HERE / "events_combo.parquet", index=False)
    ok = ev[ev["COMBO"].notna()]
    print(f"events_combo.parquet 写出：{len(ev)} 事件，COMBO 有效 {len(ok)}"
          f"（>0 占比 {(ok['COMBO'] > 0).mean()*100:.0f}%，>1 占比 {(ok['COMBO'] > 1).mean()*100:.0f}%，"
          f"RV>3.8 占比 {(ok['RV'] > 3.8).mean()*100:.0f}%）")
    print(f"COMBO 分布：p10 {ok['COMBO'].quantile(.1):+.2f} / 中位 {ok['COMBO'].median():+.2f} / p90 {ok['COMBO'].quantile(.9):+.2f}")


if __name__ == "__main__":
    main()
