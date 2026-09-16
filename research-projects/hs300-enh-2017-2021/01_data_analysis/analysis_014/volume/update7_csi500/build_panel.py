"""analysis_014/volume 更新七 — 中证500 独立面板 + v4 事件 + COMBO（**不与沪深300 混用**）。

背景：W2 是中证500 无交集的新池测试。用户要求"预计算结果独立存储、不要混用"——
因为 COMBO 的 expanding 因果标定依赖**事件总体**，混用会让两者的 z 分数不可比。

本脚本一次产出三件（全部落在本目录内，独立于 hs300 的 _market_hs300_panel / v4_events）：
  ① _market_csi500_panel.parquet   —— 中证500 成分股并集面板
  ② v4_events_csi500.parquet       —— plateau v4 活带事件（在 ① 上重跑）
  ③ events_combo_csi500.parquet    —— COMBO v2（严格按日标定，只在 ② 的事件序列上）

口径与 hs300 链路逐字对齐（已复刻验证：面板重建与 _market_hs300_panel 逐列 0.00e+00 一致）：
  面板列 = date/symbol/name/open/high/low/close/volume/amount/turn/total_market_cap
  事件   = run_band_breakout_v4，type=='break_up'，date>=2017-01-01，全 degree（供后续筛 deg≤5）
  COMBO  = z(UDVR) − z(log RV)，μ/σ 只用**严格早于当日**的事件，前置不足 500 笔置 NaN
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]                      # hs300-enh-2017-2021
ROOT = HERE.parents[6]                      # trend_range
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from plateau_algo_v4 import run_band_breakout_v4   # noqa: E402

WAREHOUSE = ROOT / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
INDEX_CODE = "000905.SH"                    # 中证500
START = "2017-01-01"
MIN_PRIOR = 500
MIN_DEGREE, MAX_DEGREE = 1, 5               # ⚠ 与 hs300 build_events.py 一致：**标定前**就筛 deg 1~5
                                            # （策略层的 deg 筛只影响用哪些事件，标定总体必须同口径）
PANEL = HERE / "_market_csi500_panel.parquet"
V4 = HERE / "v4_events_csi500.parquet"
COMBO = HERE / "events_combo_csi500.parquet"


def build_panel() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mem = [r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument='{INDEX_CODE}'").fetchall()]
    inlist = ",".join(f"'{s}'" for s in mem)
    bar = con.execute(f"""SELECT date, instrument AS symbol, name, open, high, low, close,
                                 volume, amount, turn FROM stock_bar1d
                          WHERE instrument IN ({inlist})""").df()
    val = con.execute(f"""SELECT date, instrument AS symbol, total_market_cap FROM stock_valuation
                          WHERE instrument IN ({inlist})""").df()
    con.close()
    for d in (bar, val):
        d["date"] = pd.to_datetime(d["date"])
    pan = (bar.merge(val, on=["date", "symbol"], how="left")
              .sort_values(["symbol", "date"]).reset_index(drop=True))
    pan.to_parquet(PANEL, index=False)
    print(f"① 面板 {len(pan):,} 行 / {pan['symbol'].nunique()} 只 / "
          f"{pan['date'].min().date()} ~ {pan['date'].max().date()} -> {PANEL.name}")
    return pan


def build_v4(pan: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    if V4.exists() and not force:
        ev = pd.read_parquet(V4)
        ev["date"] = pd.to_datetime(ev["date"])
        print(f"② v4 事件 {len(ev):,} 条（缓存命中，跳过扫描）-> {V4.name}")
        return ev
    rows, syms = [], pan["symbol"].unique()
    for k, sym in enumerate(syms, 1):
        g = pan[pan["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if len(g) < 60:
            continue
        try:
            events, _b, _bb = run_band_breakout_v4(g)
        except Exception as ex:                       # noqa: BLE001
            print(f"  WARN {sym}: {ex}")
            continue
        gi = {d: i for i, d in enumerate(g["date"])}
        for e in events:
            if e["type"] != "break_up":
                continue
            d = pd.Timestamp(e["date"])
            if d < pd.Timestamp(START) or d not in gi:
                continue
            rows.append({"symbol": sym, "name": g["name"].iloc[0], "date": d,
                         "close_sig": float(e["close"]), "line": float(e["line"]),
                         "lo": float(e["lo"]), "hi": float(e["hi"]),
                         "degree": int(e["degree"]), "sig_i": int(gi[d])})
        if k % 200 == 0:
            print(f"  ... {k}/{len(syms)}, events {len(rows)}", flush=True)
    ev = pd.DataFrame(rows)
    ev.to_parquet(V4, index=False)
    print(f"② v4 事件 {len(ev):,} 条 / {ev['symbol'].nunique()} 只 -> {V4.name}")
    return ev


def build_combo(pan: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    p = pan[["date", "symbol", "close", "volume"]].sort_values(["symbol", "date"])
    gp = p.groupby("symbol")
    p["ma_vol20"] = gp["volume"].transform(lambda v: v.rolling(20).mean())
    p["up_vol"] = np.where(p["close"] > gp["close"].shift(1), p["volume"], 0.0)
    p["sum_vol20"] = gp["volume"].transform(lambda v: v.rolling(20).sum())
    p["sum_upvol20"] = gp["up_vol"].transform(lambda v: v.rolling(20).sum())
    p["RV"] = p["volume"] / p["ma_vol20"]
    p["UDVR"] = p["sum_upvol20"] / p["sum_vol20"]

    # ⚠ 关键口径：先筛 deg 1~5，再标定（与 hs300 build_events.py 逐字一致）
    ev = ev[(ev["degree"] >= MIN_DEGREE) & (ev["degree"] <= MAX_DEGREE)]
    print(f"   deg {MIN_DEGREE}~{MAX_DEGREE} 事件 {len(ev):,}")
    e = ev.rename(columns={"symbol": "instrument"}).merge(
        p[["symbol", "date", "RV", "UDVR"]].rename(columns={"symbol": "instrument"}),
        on=["instrument", "date"], how="inner").dropna(subset=["RV", "UDVR"])
    e["lrv"] = np.log(e["RV"].replace([np.inf, -np.inf], np.nan))
    e = e.dropna(subset=["lrv"])
    e = e.sort_values(["date", "instrument", "degree"], ascending=[True, True, False])
    e = e.drop_duplicates(["instrument", "date"], keep="first").reset_index(drop=True)
    print(f"   规范化后事件 {len(e):,}")

    gd = e.groupby("date")
    dn, du, dr = gd.size(), gd["UDVR"].sum(), gd["lrv"].sum()
    duu = gd["UDVR"].apply(lambda s: float((s ** 2).sum()))
    drr = gd["lrv"].apply(lambda s: float((s ** 2).sum()))
    cn = dn.cumsum().shift(1)
    cu, cr = du.cumsum().shift(1), dr.cumsum().shift(1)
    cuu, crr = duu.cumsum().shift(1), drr.cumsum().shift(1)

    def _mu_sd(cs, css):
        mu = cs / cn
        var = (css - cn * mu ** 2) / (cn - 1)
        return mu, np.sqrt(var.clip(lower=0))

    mu_u, sd_u = _mu_sd(cu, cuu)
    mu_r, sd_r = _mu_sd(cr, crr)
    e["COMBO"] = ((e["UDVR"] - e["date"].map(mu_u)) / e["date"].map(sd_u)
                  - (e["lrv"] - e["date"].map(mu_r)) / e["date"].map(sd_r))
    e.loc[e["date"].map(cn).fillna(0) < MIN_PRIOR, "COMBO"] = np.nan
    e.loc[e["date"].map(sd_u) <= 0, "COMBO"] = np.nan
    e.loc[e["date"].map(sd_r) <= 0, "COMBO"] = np.nan

    out = e.rename(columns={"instrument": "symbol"})
    out.to_parquet(COMBO, index=False)
    ok = out[out["COMBO"].notna()]
    print(f"③ COMBO 有效 {len(ok):,}/{len(out):,}（>0 占 {(ok['COMBO'] > 0).mean()*100:.0f}%，"
          f"首个有效 {ok['date'].min().date()}）-> {COMBO.name}")
    return out


def main():
    pan = build_panel()
    ev = build_v4(pan)
    build_combo(pan, ev)


if __name__ == "__main__":
    main()
