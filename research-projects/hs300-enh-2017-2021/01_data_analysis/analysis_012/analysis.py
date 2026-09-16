"""analysis_012 — 突破事件 t 日特征 × 事件收益率：相关 / IC·IR / 累计IC / 单调性。

基础：analysis_007 更新八交易记录（atr4_static/detail_atr4static.parquet，12847 已判定，
止损=静态4ATR+吊灯前日ATR）。y = 事件 ret（t+1 开盘入场至离场）。
x = 信号日 t 时刻的 12 个特征（≤t 数据，无未来）：
  量价：turn(换手率)、ma_turn20、vol(成交量)、ma_vol20 —— stock_bar1d
  结构：degree（v3 阻力带转折点数）、decile（过去252日收盘分位档）—— 事件自带+面板算
  估值：float_market_cap、dividend_yield_ratio、pe_ttm、pb —— stock_valuation
  指标：macd(12,26,9 归一化 macd/close)、roc(20)、llt(60) 切线斜率归一化 —— 自算
口径：
  - z-score 化：截面（同月全部事件）z-score，避免量纲与时点水平差异
  - IC = 月度截面 spearman(feature_z, ret)；IR = mean(IC)/std(IC)；累计IC = cumsum
  - 单调性：全样本按特征十分位（z 前原值分桶）看平均 ret 的单调性 + 分桶曲线
输出：features.parquet / ic_summary.csv / ic_monthly.csv / result_view.html
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range")
PROJ = ROOT / "replication/research-projects/hs300-enh-2017-2021"
HERE = Path(__file__).resolve().parent
U8 = PROJ / "01_data_analysis/analysis_007/atr4_static"
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from llt60_precompute import _llt                      # noqa: E402  与 strategy_007 同源

PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

MACD_FAST, MACD_SLOW, MACD_SIG = 12, 26, 9
ROC_N, LLT_D = 20, 60
W_DECILE = 252

FEATURES = ["turn", "ma_turn20", "vol", "ma_vol20", "degree", "decile",
            "float_market_cap", "dividend_yield_ratio", "pe_ttm", "pb",
            "macd", "roc", "llt"]


def build_feature_table() -> pd.DataFrame:
    det = pd.read_parquet(U8 / "detail_atr4static.parquet")
    det["date"] = pd.to_datetime(det["date"])
    dec = det[det["result"].isin(["success", "fail"])].copy()
    dec["ret"] = dec["ret"].astype(float)

    # ── bar1d（turn/vol + 自算指标的价格序列）──
    bar = pd.read_parquet(PANEL)                     # 与事件同源面板（后复权 close）
    bar["date"] = pd.to_datetime(bar["date"])
    feats_by_sym = {}
    for sym, g in bar.sort_values(["symbol", "date"]).groupby("symbol", sort=False):
        gg = g.set_index("date")
        c = gg["close"].astype(float)
        ema_f = c.ewm(span=MACD_FAST, adjust=False).mean()
        ema_s = c.ewm(span=MACD_SLOW, adjust=False).mean()
        macd = ema_f - ema_s
        macd_sig = macd.ewm(span=MACD_SIG, adjust=False).mean()
        llt_series = _llt(c, LLT_D)
        f = pd.DataFrame({
            "turn": gg["turn"].astype(float) if "turn" in gg else np.nan,
            "vol": gg["volume"].astype(float),
            "ma_turn20": gg["turn"].astype(float).rolling(20).mean() if "turn" in gg else np.nan,
            "ma_vol20": gg["volume"].astype(float).rolling(20).mean(),
            "macd": (macd - macd_sig) / c,           # DIF−DEA，归一化
            "roc": c.pct_change(ROC_N),
            "llt": llt_series.diff() / c,            # 切线斜率归一化
        }, index=gg.index)
        # decile（过去252日）
        cs = c.to_numpy(float)
        dcl = pd.Series(np.nan, index=gg.index)
        for i in range(len(cs)):
            lo = max(0, i - W_DECILE + 1)
            win = cs[lo:i + 1]
            if len(win) >= 60:
                dcl.iloc[i] = min(int(float((win < cs[i]).mean()) * 10) + 1, 10)
        f["decile"] = dcl
        feats_by_sym[sym] = f

    # ── 估值（warehouse valuation）──
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    val = con.execute("SELECT date, instrument, float_market_cap, dividend_yield_ratio, "
                      "pe_ttm, pb FROM stock_valuation").fetchdf()
    con.close()
    val["date"] = pd.to_datetime(val["date"])
    val_by_sym = {s: x.set_index("date") for s, x in val.groupby("instrument")}

    rows = []
    for r in dec.itertuples():
        f = feats_by_sym.get(r.symbol)
        v = val_by_sym.get(r.symbol)
        d = pd.Timestamp(r.date)
        if f is None or d not in f.index:
            continue
        fr = f.loc[d]
        row = {"symbol": r.symbol, "date": d, "ret": r.ret,
               "result": r.result, "degree": int(r.degree)}
        for c_ in ["turn", "ma_turn20", "vol", "ma_vol20", "macd", "roc", "llt", "decile"]:
            row[c_] = float(fr[c_]) if pd.notna(fr[c_]) else np.nan
        if v is not None and d in v.index:
            for c_ in ["float_market_cap", "dividend_yield_ratio", "pe_ttm", "pb"]:
                row[c_] = float(v.loc[d, c_]) if pd.notna(v.loc[d, c_]) else np.nan
        else:
            for c_ in ["float_market_cap", "dividend_yield_ratio", "pe_ttm", "pb"]:
                row[c_] = np.nan
        rows.append(row)
    fx = pd.DataFrame(rows)
    # 估值去极值（pe/pb/市值 取 log；pe 负值置 NaN）
    fx["pe_ttm"] = fx["pe_ttm"].where(fx["pe_ttm"] > 0)
    for c_ in ["float_market_cap", "pe_ttm", "pb"]:
        fx[c_] = np.log(fx[c_].where(fx[c_] > 0))
    fx["ym"] = fx["date"].dt.to_period("M").astype(str)
    # 截面 z-score（按月）
    for c_ in FEATURES:
        grp = fx.groupby("ym")[c_]
        mu, sd = grp.transform("mean"), grp.transform("std")
        fx[f"{c_}_z"] = (fx[c_] - mu) / sd.replace(0, np.nan)
    fx.to_parquet(HERE / "features.parquet", index=False)
    print(f"特征表 {len(fx)} 行 × {len(FEATURES)} 特征（月度截面 z-score 已加 _z 列）")
    return fx


def analyze(fx: pd.DataFrame):
    from scipy.stats import spearmanr
    out = []
    ic_monthly = {}
    for c_ in FEATURES:
        z, s = fx[f"{c_}_z"], fx["ret"]
        v = s.notna() & z.notna()
        pearson = np.corrcoef(z[v], s[v])[0, 1] if v.sum() > 100 else np.nan
        # 月度 IC（截面 spearman）
        ics = []
        for m, g in fx[v].groupby("ym"):
            if len(g) >= 30:
                ic, _ = spearmanr(g[f"{c_}_z"], g["ret"])
                ics.append((m, ic))
        ser = pd.Series(dict(ics)).sort_index()
        ic_monthly[c_] = ser
        ic_mean, ic_std = ser.mean(), ser.std()
        ir = ic_mean / ic_std if ic_std and ic_std > 0 else np.nan
        # 十分位单调（全样本按原始值分桶）
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
                    "decile_ret_first": ym.iloc[0] if len(ym) else np.nan,
                    "decile_ret_last": ym.iloc[-1] if len(ym) else np.nan})
    summary = pd.DataFrame(out)
    summary.to_csv(HERE / "ic_summary.csv", index=False, encoding="utf-8-sig")
    im = pd.DataFrame(ic_monthly)
    im.to_csv(HERE / "ic_monthly.csv", encoding="utf-8-sig")
    print(summary.round(4).to_string(index=False))
    return summary, im


if __name__ == "__main__":
    fx = build_feature_table()
    analyze(fx)
