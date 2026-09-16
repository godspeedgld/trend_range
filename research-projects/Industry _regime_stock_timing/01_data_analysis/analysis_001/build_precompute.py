"""analysis_001 预计算 —— 沪深300 面板 / ATR14 / v4 活带事件 / COMBO v2 / **变盘指数**。

**本脚本全部独立重算**（用户要求 11）：不复用 hs300-enh-2017-2021 的任何中间产物，
产物落在本目录 `_precomputed/`。算完由 `verify.py` 与旧工程逐值对账，证明重算正确。

产出（`_precomputed/`）：
  panel.parquet           沪深300 并集面板（668 只 × 2015-2026）
  atr14.parquet           Wilder ATR(14)（**独立缓存**，不用 shared/atr14_panel.parquet）
  v4_events.parquet       plateau v4 活带 break_up 事件（全 degree）
  events_combo.parquet    deg 1~5 筛后标定的 COMBO v2（严格按日，μ/σ 只用 date<当日）
  regime_index.parquet    **变盘指数**（申万一级 31 行业，I'_20 及一阶导 T'）

变盘指数口径（银河证券 20260701 研报 §4.1，原文图 3 四步）：
  ① Rank_std_{i,t} = |Rank_{i,t} − Rank_{i,t−220}| / N      N=31 个一级行业
  ② R_t = (1/N) Σ_i Rank_std_{i,t}
  ③ I_t = std_220(R_t)                                      220 日滚动标准差
  ④ I'_t = Mov_20(I_t)                                      平滑窗口 m=20（研报最佳）
  → T'_t = I'_t − I'_{t−1}                                  一阶导（下行 = T'<0）
  其中 Rank = 行业 trailing-21 交易日收益率的当日截面排名（研报"月度收益率"）
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]                      # trend_range
PROJ = HERE.parents[1]                      # Industry _regime_stock_timing
SHARED_HS = ROOT / "research-projects/hs300-enh-2017-2021/shared"
sys.path.insert(0, str(SHARED_HS))
from plateau_algo_v4 import run_band_breakout_v4        # noqa: E402

WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
OUT = HERE / "_precomputed"
OUT.mkdir(parents=True, exist_ok=True)

INDEX_CODE = "000300.SH"
START, END = "2015-01-05", "2026-08-21"
ATR_N = 14
# v4 事件 / COMBO 口径（与 hs300 链路一致，用于对账）
EV_START = "2017-01-01"
MIN_DEGREE, MAX_DEGREE, MIN_PRIOR = 1, 5, 500
# 变盘指数参数（研报最佳）
RET_WIN = 21          # "月度收益率" = trailing 21 交易日
LOOKBACK = 220        # 排名比较回望期
VOL_WIN = 220         # 滚动标准差窗口
SMOOTH = 20           # 平滑窗口（研报最佳）


# ── ① 沪深300 面板 ──
def build_panel() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mem = [r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument='{INDEX_CODE}'").fetchall()]
    inl = ",".join(f"'{s}'" for s in mem)
    bar = con.execute(f"""SELECT date, instrument AS symbol, name, open, high, low, close,
                                 volume, amount, turn FROM stock_bar1d
                          WHERE instrument IN ({inl}) AND date >= '{START}' AND date <= '{END}'""").df()
    val = con.execute(f"""SELECT date, instrument AS symbol, total_market_cap FROM stock_valuation
                          WHERE instrument IN ({inl}) AND date >= '{START}' AND date <= '{END}'""").df()
    con.close()
    for d in (bar, val):
        d["date"] = pd.to_datetime(d["date"])
    pan = (bar.merge(val, on=["date", "symbol"], how="left")
              .sort_values(["symbol", "date"]).reset_index(drop=True))
    pan.to_parquet(OUT / "panel.parquet", index=False)
    print(f"① 面板 {len(pan):,} 行 / {pan['symbol'].nunique()} 只 / "
          f"{pan['date'].min().date()} ~ {pan['date'].max().date()}")
    return pan


# ── ② ATR(14) Wilder（独立缓存）──
def build_atr(pan: pd.DataFrame) -> pd.DataFrame:
    out = []
    for sym, g in pan.sort_values(["symbol", "date"]).groupby("symbol", sort=True):
        h, l, c = g["high"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy()
        pc = pd.Series(c).shift(1).to_numpy()
        tr = pd.Series([h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i]))
                                        for i in range(1, len(g))])
        atr = tr.ewm(alpha=1.0 / ATR_N, adjust=False, min_periods=ATR_N).mean()
        out.append(pd.DataFrame({"symbol": sym, "date": g["date"].to_numpy(), "atr14": atr.to_numpy()}))
    df = pd.concat(out, ignore_index=True)
    df.to_parquet(OUT / "atr14.parquet", index=False)
    print(f"② ATR14 {len(df):,} 行 / {df['symbol'].nunique()} 只 / 非空 {df.atr14.notna().mean()*100:.1f}%")
    return df


# ── ③ v4 活带事件 ──
def build_v4(pan: pd.DataFrame) -> pd.DataFrame:
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
            if d < pd.Timestamp(EV_START) or d not in gi:
                continue
            rows.append({"symbol": sym, "name": g["name"].iloc[0], "date": d,
                         "close_sig": float(e["close"]), "line": float(e["line"]),
                         "lo": float(e["lo"]), "hi": float(e["hi"]),
                         "degree": int(e["degree"]), "sig_i": int(gi[d])})
        if k % 200 == 0:
            print(f"  ... {k}/{len(syms)}, events {len(rows)}", flush=True)
    ev = pd.DataFrame(rows)
    ev.to_parquet(OUT / "v4_events.parquet", index=False)
    print(f"③ v4 事件 {len(ev):,} 条 / {ev['symbol'].nunique()} 只")
    return ev


# ── ④ COMBO v2（先筛 deg 1~5，再严格按日标定）──
def build_combo(pan: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    ev = ev[(ev["degree"] >= MIN_DEGREE) & (ev["degree"] <= MAX_DEGREE)]
    p = pan[["date", "symbol", "close", "volume"]].sort_values(["symbol", "date"])
    gp = p.groupby("symbol")
    p["ma_vol20"] = gp["volume"].transform(lambda v: v.rolling(20).mean())
    p["up_vol"] = np.where(p["close"] > gp["close"].shift(1), p["volume"], 0.0)
    p["sum_vol20"] = gp["volume"].transform(lambda v: v.rolling(20).sum())
    p["sum_upvol20"] = gp["up_vol"].transform(lambda v: v.rolling(20).sum())
    p["RV"] = p["volume"] / p["ma_vol20"]
    p["UDVR"] = p["sum_upvol20"] / p["sum_vol20"]

    e = ev.rename(columns={"symbol": "instrument"}).merge(
        p[["symbol", "date", "RV", "UDVR"]].rename(columns={"symbol": "instrument"}),
        on=["instrument", "date"], how="inner").dropna(subset=["RV", "UDVR"])
    e["lrv"] = np.log(e["RV"].replace([np.inf, -np.inf], np.nan))
    e = e.dropna(subset=["lrv"])
    e = (e.sort_values(["date", "instrument", "degree"], ascending=[True, True, False])
          .drop_duplicates(["instrument", "date"], keep="first").reset_index(drop=True))
    print(f"   deg 1~5 规范化后事件 {len(e):,}")

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
    out.to_parquet(OUT / "events_combo.parquet", index=False)
    ok = out[out.COMBO.notna()]
    print(f"④ COMBO 有效 {len(ok):,}/{len(out):,}（>0 占 {(ok.COMBO>0).mean()*100:.0f}%）")
    return out


# ── ⑤ 变盘指数（申万一级 31 行业）──
def build_regime_index() -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    pre = con.execute("""SELECT DISTINCT industry_level1_name AS nm, substr(industry_instrument,1,2) AS p2
                         FROM stock_industry_component WHERE industry='sw2021'""").df()
    plist = "','".join(sorted(pre["p2"]))
    ind = con.execute(f"""SELECT substr(instrument,1,2) AS p2, date, avg(change_ratio) AS chg
                          FROM stock_industry_bar1d
                          WHERE substr(instrument,1,2) IN ('{plist}')
                          GROUP BY 1, 2 ORDER BY 1, 2""").df()
    con.close()
    ind["date"] = pd.to_datetime(ind["date"])
    N = ind["p2"].nunique()

    # 行业 trailing-21 交易日收益率（复利）
    piv = ind.pivot(index="date", columns="p2", values="chg").sort_index()
    cum = np.log1p(piv.fillna(0)).cumsum()
    ret = np.expm1(cum - cum.shift(RET_WIN))                    # trailing-21 收益率
    # ① 当日截面排名 → 与 LOOKBACK 日前排名之差（除以 N 取绝对值）
    rk = ret.rank(axis=1, pct=False)                            # 1..N
    rank_std = (rk - rk.shift(LOOKBACK)).abs() / N
    # ② 截面聚合
    R = rank_std.mean(axis=1)
    # ③ 220 日滚动标准差
    I = R.rolling(VOL_WIN, min_periods=VOL_WIN).std()
    # ④ 平滑 + 一阶导
    out = pd.DataFrame({"R": R, "I": I})
    out[f"I_smooth{SMOOTH}"] = I.rolling(SMOOTH, min_periods=SMOOTH).mean()
    out["T_prime"] = out[f"I_smooth{SMOOTH}"].diff()
    out["down"] = out["T_prime"] < 0
    out = out.dropna(subset=["T_prime"]).reset_index()
    out.to_parquet(OUT / "regime_index.parquet", index=False)
    print(f"⑤ 变盘指数 {len(out):,} 行 / {N} 个一级行业 / "
          f"{out.date.min().date()} ~ {out.date.max().date()} | 下行日占比 {out.down.mean()*100:.1f}%")
    return out


def main():
    pan = build_panel()
    build_atr(pan)
    ev = build_v4(pan)
    build_combo(pan, ev)
    build_regime_index()
    print(f"\n全部产物 → {OUT}")


if __name__ == "__main__":
    main()
