"""v4 记录统计分析（stats_v4/）：
  1. 离场/成本拆分分布：按 exit_reason 与 result 拆分 ret 分布（止损成本/吊灯止盈/吊灯非正小亏）
  2. 特征 IC 分析：13 特征（同生成版口径，t 日值≤t，月截面 z-score，spearman IC/IR/单调）
产物：overall.csv / exit_split.csv / ic_summary.csv / stats_v4_view.html
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
V4 = HERE.parent / "detail_v4.parquet"
PROJ = HERE.parents[3]
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from llt60_precompute import _llt                      # noqa: E402

MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
ROC_N, LLT_D, W_DECILE = 20, 60, 252
PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = Path(r"C:\Quant\trend_range\data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")
FEATURES = ["turn", "ma_turn20", "vol", "ma_vol20", "degree", "decile",
            "float_market_cap", "dividend_yield_ratio", "pe_ttm", "pb",
            "macd", "roc", "llt"]


def build_features(det: pd.DataFrame) -> pd.DataFrame:
    det = det.copy()
    det["date"] = pd.to_datetime(det["date"])
    dec = det[det["result"].isin(["success", "fail"])].copy()
    bar = pd.read_parquet(PANEL)
    bar["date"] = pd.to_datetime(bar["date"])
    fs_by_sym = {}
    for sym, g in bar.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        gg = g.set_index("date")
        c = gg["close"].astype(float)
        ema_f, ema_s = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=9, adjust=False).mean()
        llt_s = _llt(c, LLT_D)
        f = pd.DataFrame({
            "turn": gg["turn"].astype(float) if "turn" in gg else np.nan,
            "vol": gg["volume"].astype(float),
            "ma_turn20": gg["turn"].astype(float).rolling(20).mean() if "turn" in gg else np.nan,
            "ma_vol20": gg["volume"].astype(float).rolling(20).mean(),
            "macd": (macd - macd_sig) / c,
            "roc": c.pct_change(ROC_N, fill_method=None),
            "llt": llt_s.diff() / c,
        }, index=gg.index)
        cs = c.to_numpy(float)
        dcl = pd.Series(np.nan, index=gg.index)
        for i in range(len(cs)):
            lo = max(0, i - W_DECILE + 1)
            win = cs[lo:i + 1]
            if len(win) >= 60:
                dcl.iloc[i] = min(int(float((win < cs[i]).mean()) * 10) + 1, 10)
        f["decile"] = dcl
        fs_by_sym[sym] = f
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    val = con.execute("SELECT date, instrument, float_market_cap, dividend_yield_ratio, "
                      "pe_ttm, pb FROM stock_valuation").fetchdf()
    con.close()
    val["date"] = pd.to_datetime(val["date"])
    val_by_sym = {s: x.set_index("date") for s, x in val.groupby("instrument")}

    rows = []
    for r in dec.itertuples():
        f = fs_by_sym.get(r.symbol)
        v = val_by_sym.get(r.symbol)
        d = pd.Timestamp(r.date)
        if f is None or d not in f.index:
            continue
        fr = f.loc[d]
        row = {"symbol": r.symbol, "date": d, "ret": r.ret, "result": r.result,
               "reason": r.reason, "degree": int(r.degree), "hold_bars": r.hold_bars}
        for c_ in ["turn", "ma_turn20", "vol", "ma_vol20", "macd", "roc", "llt", "decile"]:
            row[c_] = float(fr[c_]) if pd.notna(fr[c_]) else np.nan
        for c_ in ["float_market_cap", "dividend_yield_ratio", "pe_ttm", "pb"]:
            row[c_] = float(v.loc[d, c_]) if v is not None and d in v.index and pd.notna(v.loc[d, c_]) else np.nan
        rows.append(row)
    fx = pd.DataFrame(rows)
    fx["pe_ttm"] = fx["pe_ttm"].where(fx["pe_ttm"] > 0)
    for c_ in ["float_market_cap", "pe_ttm", "pb"]:
        fx[c_] = np.log(fx[c_].where(fx[c_] > 0))
    fx["ym"] = fx["date"].dt.to_period("M").astype(str)
    for c_ in FEATURES:
        g = fx.groupby("ym")[c_]
        fx[f"{c_}_z"] = (fx[c_] - g.transform("mean")) / g.transform("std").replace(0, np.nan)
    return fx


def ic_analyze(fx: pd.DataFrame):
    from scipy.stats import spearmanr
    out, icm = [], {}
    for c_ in FEATURES:
        z, s, v = fx[f"{c_}_z"], fx["ret"], fx[f"{c_}_z"].notna() & fx["ret"].notna()
        pearson = np.corrcoef(z[v], s[v])[0, 1] if v.sum() > 100 else np.nan
        ics = []
        for m, g in fx[v].groupby("ym"):
            if len(g) >= 30:
                ic, _ = spearmanr(g[f"{c_}_z"], g["ret"])
                ics.append((m, ic))
        ser = pd.Series(dict(ics)).sort_index()
        icm[c_] = ser
        ic_mean, ic_std = ser.mean(), ser.std()
        ir = ic_mean / ic_std if ic_std and ic_std > 0 else np.nan
        try:
            q = pd.qcut(fx.loc[v, c_], 10, labels=False, duplicates="drop")
            ym = fx.loc[v].groupby(q)["ret"].mean()
            up = ym.iloc[-1] >= ym.iloc[0]
            mono = (np.diff(ym) >= 0 if up else np.diff(ym) <= 0).mean()
        except Exception:
            ym, mono = pd.Series(dtype=float), np.nan
        out.append({"feature": c_, "pearson_z": pearson, "ic_mean": ic_mean,
                    "ic_std": ic_std, "IR": ir, "ic_n_months": len(ser),
                    "mono_pct": mono,
                    "d_first": ym.iloc[0] if len(ym) else np.nan,
                    "d_last": ym.iloc[-1] if len(ym) else np.nan})
    s = pd.DataFrame(out)
    s.to_csv(HERE / "ic_summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(icm).to_csv(HERE / "ic_monthly.csv", encoding="utf-8-sig")
    return s


def main():
    det = pd.read_parquet(V4)
    det["date"] = pd.to_datetime(det["date"])
    dec = det[det["result"].isin(["success", "fail"])].copy()
    dec["ret_pct"] = dec["ret"] * 100
    n_s = int((dec["result"] == "success").sum())
    w, l = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
    overall = pd.DataFrame([{"n": len(dec), "win_rate": n_s / len(dec),
                             "mean_ret": dec["ret_pct"].mean(), "median": dec["ret_pct"].median(),
                             "payoff": w.mean() / abs(l.mean())}])
    overall.to_csv(HERE / "overall.csv", index=False)
    print(f"总体: {len(dec)} 笔 | 胜率 {overall.win_rate.iloc[0]*100:.1f}% | "
          f"期望 {overall.mean_ret.iloc[0]:+.2f}% | 盈亏比 {overall.payoff.iloc[0]:.2f}")

    # 1) 离场/成本拆分
    split = (dec.groupby(["reason"])["ret_pct"]
             .agg(n="count", mean="mean", median="median", sum="sum").reset_index())
    split.to_csv(HERE / "exit_split.csv", index=False, encoding="utf-8-sig")
    print("\n离场拆分:")
    print(split.round(2).to_string(index=False))

    # 2) 特征 IC
    print("\n构建特征...")
    fx = build_features(det)
    fx.to_parquet(HERE / "features_v4.parquet", index=False)
    ic = ic_analyze(fx)
    print("\n特征 IC:")
    print(ic.round(4).to_string(index=False))
    return dec, split, ic


if __name__ == "__main__":
    main()
