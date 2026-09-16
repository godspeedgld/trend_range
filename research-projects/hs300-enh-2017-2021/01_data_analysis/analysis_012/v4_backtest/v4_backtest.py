"""analysis_012 — 用 v4（活阻力带生命周期）信号重跑 更新八 回测。

规则与更新八完全相同（见 analysis_007/atr4_static/gen_trades.py）：
  开仓：t 突破事件（degree≥2）→ t+1 开盘买入
  平仓（t 收盘判 → t+1 开盘执行）：
    ① 静态止损：收盘 < close_sig(t) − 4×ATR(t)
    ② 吊灯：收盘 < 自 t 日起最高 high − 4×ATR(前一日)
  成功 = ret>0（吊灯正）；失败 = 止损 或 吊灯非正
差异只在【信号源】：
  更新八 = v3（plateau_v3_events，全带含永生死带）
  本版   = v4（plateau_algo_v4，突破只由当期【活阻力带】发）
数据：668 只沪深300历史成分（_market_hs300_panel.parquet），事件 date≥2017（同更新八）。
输出：本目录 v4_events.parquet / detail_v4.parquet / summary 对比 v3。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from atr14_precompute import load_atr14          # noqa: E402
from plateau_algo_v4 import run_band_breakout_v4  # noqa: E402

ATR_MULT = 4.0
MIN_DEGREE = 2
START = "2017-01-01"
PANEL = PROJ / "_market_hs300_panel.parquet"
V3_DETAIL = PROJ / "01_data_analysis/analysis_007/atr4_static/detail_atr4static.parquet"


# ── ① v4 事件扫描（全市场，只活带 break_up，含 sig_i）──
def scan_v4_events(force: bool = False) -> pd.DataFrame:
    cache = HERE / "v4_events.parquet"
    if cache.exists() and not force:
        df = pd.read_parquet(cache)
        df["date"] = pd.to_datetime(df["date"])
        return df
    market = pd.read_parquet(PANEL)
    market["date"] = pd.to_datetime(market["date"])
    rows, symbols = [], market["symbol"].unique()
    for k, sym in enumerate(symbols, 1):
        g = market[market["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if len(g) < 60:
            continue
        try:
            events, _bands, _bb = run_band_breakout_v4(g)
        except Exception as ex:                       # noqa: BLE001
            print(f"  WARN {sym}: {ex}")
            continue
        for e in events:
            if e["type"] != "break_up":
                continue
            d = pd.Timestamp(e["date"])
            if d < pd.Timestamp(START):
                continue
            hits = g.index[g["date"] == e["date"]]
            if len(hits) == 0:
                continue
            rows.append({"symbol": sym, "name": g["name"].iloc[0], "date": d,
                         "close_sig": float(e["close"]), "line": float(e["line"]),
                         "lo": float(e["lo"]), "hi": float(e["hi"]),
                         "degree": int(e["degree"]), "sig_i": int(hits[0])})
        if k % 100 == 0:
            print(f"  ... {k}/{len(symbols)}, events {len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(cache, index=False)
    return df


# ── ② 事件级模拟（与更新八 gen_trades 同源）──
def simulate(g: pd.DataFrame, atr: np.ndarray, sig_i: int, close_sig: float) -> dict | None:
    n = len(g)
    if sig_i + 1 >= n:
        return None
    opens, highs, closes = g["open"].values, g["high"].values, g["close"].values
    dates = g["date"].values
    base = float(opens[sig_i + 1])
    a_sig = atr[sig_i]
    if a_sig is None or np.isnan(a_sig) or a_sig <= 0:
        return None
    stop_line = float(close_sig) - ATR_MULT * float(a_sig)
    max_hi = float(np.nanmax(highs[sig_i:sig_i + 1]))
    for k in range(sig_i + 1, n):
        hk, ck = highs[k], closes[k]
        if not np.isnan(hk):
            max_hi = max(max_hi, float(hk))
        if np.isnan(ck):
            continue
        if ck < stop_line:
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ck / base - 1.0, "exit_reason": "stop_4atr",
                    "hold_bars": k - sig_i, "max_high": max_hi}
        a_prev = atr[k - 1]
        if a_prev is not None and not np.isnan(a_prev) and a_prev > 0 \
                and ck < max_hi - ATR_MULT * float(a_prev):
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ck / base - 1.0, "exit_reason": "chandelier",
                    "hold_bars": k - sig_i, "max_high": max_hi}
    return {"base": base, "exit_date": None, "exit_price": np.nan,
            "ret": np.nan, "exit_reason": "pending", "hold_bars": n - 1 - sig_i,
            "max_high": max_hi}


def run_all():
    ev = scan_v4_events()
    ev = ev[ev["degree"] >= MIN_DEGREE].copy()
    print(f"v4 事件（degree≥2, date≥2017）: {len(ev)}")
    v3 = pd.read_parquet(PROJ / "01_data_analysis/analysis_007/v3_events_cache.parquet")
    v3["date"] = pd.to_datetime(v3["date"])
    v3 = v3[(v3["degree"] >= MIN_DEGREE) & (v3["date"] >= START)]
    print(f"v3 事件（同过滤）: {len(v3)}（{len(v3) - len(ev)} 条为 v4 死带退役所滤）")

    market = pd.read_parquet(PANEL)
    market["date"] = pd.to_datetime(market["date"])
    groups = {s: x.sort_values("date").reset_index(drop=True)
              for s, x in market.groupby("symbol")}
    atr_df = load_atr14(PANEL, SHARED)
    atr_by_sym = {s: x.set_index("date")["atr14"] for s, x in atr_df.groupby("symbol")}

    rows = []
    for sym, evs in ev.groupby("symbol"):
        g = groups.get(sym)
        if g is None:
            continue
        a_ser = atr_by_sym.get(sym)
        atr = (g["date"].map(a_ser).to_numpy(dtype=float) if a_ser is not None
               else np.full(len(g), np.nan))
        for r in evs.itertuples():
            sim = simulate(g, atr, int(r.sig_i), float(r.close_sig))
            if sim is None:
                continue
            reason = sim["exit_reason"]
            if reason == "pending":
                result, reason2 = "pending", "pending_nofwd"
            elif reason == "stop_4atr":
                result, reason2 = "fail", "stop_4atr"
            else:
                result = "success" if sim["ret"] > 0 else "fail"
                reason2 = "chan_pos" if sim["ret"] > 0 else "chan_nonpos"
            rows.append({"symbol": sym, "name": r.name, "date": r.date,
                         "close_sig": r.close_sig, "line": r.line, "degree": r.degree,
                         **sim, "result": result, "reason": reason2})
    det = pd.DataFrame(rows)
    det.to_parquet(HERE / "detail_v4.parquet", index=False)
    det.to_csv(HERE / "detail_v4.csv", index=False, encoding="utf-8-sig")

    dec = det[det["result"].isin(["success", "fail"])].copy()
    n_s = int((dec.result == "success").sum())
    n_f = int((dec.result == "fail").sum())
    w, l = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
    print(f"\n═══ v4 信号回测（更新八规则）═══")
    print(f"已判定 {len(dec)}：成功 {n_s} / 失败 {n_f} | 胜率 {n_s/len(dec)*100:.1f}% | "
          f"期望 {dec['ret'].mean()*100:+.2f}% | 盈亏比 {w.mean()/abs(l.mean()):.2f} | "
          f"持仓中位 {dec['hold_bars'].median():.0f} bar")
    print("离场:", dec["reason"].value_counts().to_dict())

    v3d = pd.read_parquet(V3_DETAIL)
    v3d = v3d[v3d["result"].isin(["success", "fail"])]
    v3_ns, v3_nf = int((v3d.result == "success").sum()), int((v3d.result == "fail").sum())
    v3w, v3l = v3d.loc[v3d.ret > 0, "ret"], v3d.loc[v3d.ret <= 0, "ret"]
    print(f"\n═══ 对照：v3 信号回测（更新八原结果）═══")
    print(f"已判定 {len(v3d)}：成功 {v3_ns} / 失败 {v3_nf} | 胜率 {v3_ns/len(v3d)*100:.1f}% | "
          f"期望 {v3d['ret'].mean()*100:+.2f}% | 盈亏比 {v3w.mean()/abs(v3l.mean()):.2f}")
    return det


if __name__ == "__main__":
    run_all()
