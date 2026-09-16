"""analysis_014/volume 更新六 — COMBO 标定改「严格按日（只用 date<当日 事件）」，消除行序依赖。

**动机（2026-09-11 BigQuant 移植对账发现）**：原 expanding().shift(1) 标定依赖**事件行序**，
同日多事件谁在前由文件/SQL 行序决定 → COMBO 不可复现（本地 vs 云端同日事件次序不同，
单事件日 100% 一致、多事件日仅 35%）。选 B：**μ/σ 只用严格早于当日的事件**，
顺序无关 + 因果更纯（不用同日信息）。

同时规范化去重：按 (date, instrument, degree desc) 排序 → (instrument,date) 取首个（=同日同股
取 degree 最大的带），消除原 dict last-wins 的 dup 歧义。

产物：events_combo_v2.parquet（供 update6 回测与云端移植对账）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]
V4 = PROJ / "01_data_analysis/analysis_012/v4_backtest/v4_events.parquet"
PANEL = PROJ / "_market_hs300_panel.parquet"
MIN_DEGREE, MAX_DEGREE = 1, 5         # 与 W2 原事件集一致（deg≤5），隔离"标定口径"单一变量
MIN_PRIOR = 500                       # 标定最少前置事件数（对应原 burn-in 500）


def main():
    ev = pd.read_parquet(V4)
    ev["date"] = pd.to_datetime(ev["date"])
    ev = ev[(ev["degree"] >= MIN_DEGREE) & (ev["degree"] <= MAX_DEGREE)]

    pan = pd.read_parquet(PANEL, columns=["date", "symbol", "close", "volume"])
    pan["date"] = pd.to_datetime(pan["date"])
    pan = pan.sort_values(["symbol", "date"])
    pane = pan.groupby("symbol")
    pan["ma_vol20"] = pane["volume"].transform(lambda v: v.rolling(20).mean())
    up = pan["close"] > pane["close"].shift(1)
    pan["up_vol"] = np.where(up, pan["volume"], 0.0)
    pan["sum_vol20"] = pane["volume"].transform(lambda v: v.rolling(20).sum())
    pan["sum_upvol20"] = pane["up_vol"].transform(lambda v: v.rolling(20).sum())
    pan["RV"] = pan["volume"] / pan["ma_vol20"]
    pan["UDVR"] = pan["sum_upvol20"] / pan["sum_vol20"]

    ev = ev.rename(columns={"symbol": "instrument"}).merge(
        pan.rename(columns={"symbol": "instrument"})[["instrument", "date", "RV", "UDVR"]],
        on=["instrument", "date"], how="inner")
    ev = ev.dropna(subset=["RV", "UDVR"])
    ev["lrv"] = np.log(ev["RV"].replace([np.inf, -np.inf], np.nan))
    ev = ev.dropna(subset=["lrv"])

    # ── 规范化排序 + 去重（顺序无关）──
    ev = ev.sort_values(["date", "instrument", "degree"],
                        ascending=[True, True, False]).reset_index(drop=True)
    ev = ev.drop_duplicates(["instrument", "date"], keep="first").reset_index(drop=True)
    print(f"规范化后事件 {len(ev)}（deg {MIN_DEGREE}~{MAX_DEGREE}）")

    # ── 按日标定：μ/σ 只用严格早于当日的事件（=截至前一日的累计）──
    gd = ev.groupby("date")
    day_n = gd.size()
    day_u = gd["UDVR"].sum()
    day_r = gd["lrv"].sum()
    day_uu = gd["UDVR"].apply(lambda s: float((s ** 2).sum()))
    day_rr = gd["lrv"].apply(lambda s: float((s ** 2).sum()))

    cum_n = day_n.cumsum().shift(1)                   # 截至【前一日】的事件数
    cum_u, cum_r = day_u.cumsum().shift(1), day_r.cumsum().shift(1)
    cum_uu, cum_rr = day_uu.cumsum().shift(1), day_rr.cumsum().shift(1)

    def _mu_sd(cum_s, cum_ss):
        mu = cum_s / cum_n
        var = (cum_ss - cum_n * mu ** 2) / (cum_n - 1)
        return mu, np.sqrt(var.clip(lower=0))

    mu_u, sd_u = _mu_sd(cum_u, cum_uu)
    mu_r, sd_r = _mu_sd(cum_r, cum_rr)
    ev["COMBO"] = ((ev["UDVR"] - ev["date"].map(mu_u)) / ev["date"].map(sd_u)
                   - (ev["lrv"] - ev["date"].map(mu_r)) / ev["date"].map(sd_r))
    ev.loc[ev["date"].map(cum_n).fillna(0) < MIN_PRIOR, "COMBO"] = np.nan   # 前置事件不足
    ev.loc[ev["date"].map(sd_u) <= 0, "COMBO"] = np.nan
    ev.loc[ev["date"].map(sd_r) <= 0, "COMBO"] = np.nan

    out = ev.rename(columns={"instrument": "symbol"})
    out.to_parquet(HERE / "events_combo_v2.parquet", index=False)
    ok = out[out["COMBO"].notna()]
    first = ok["date"].min()
    print(f"COMBO 有效 {len(ok)}/{len(out)}（>0 占 {(ok['COMBO']>0).mean()*100:.0f}%，"
          f"首个有效 {first.date()}）；写出 events_combo_v2.parquet")
    print(f"[对照] v1（原 expanding 行序标定）有效数：" +
          str(len(pd.read_parquet(HERE.parent / 'update3_combo_backtest/events_combo.parquet').query('COMBO==COMBO'))))


if __name__ == "__main__":
    main()
