"""analysis_007 更新八 — 止损=静态4ATR(信号日定线) + 止盈=移动吊灯4ATR，两条并存。

用户口径（2026-09-03）：
  入场：v3 突破事件（degree≥2）。t 日突破产生信号，t+1 只开盘买入，其他什么都不做。
  离场（t+1 起逐日收盘判定，先触发者平仓，t+1 开盘执行）：
    ① 止损线【t 日定死】：收盘 < stop_line = close_sig(t 收盘) − 4×ATR14(截至 t)
    ② 止盈线【移动】：收盘 < t 日起最高 high − 4×ATR14(截至前一日)
       ——吊灯 ATR 用前一交易日（判定当日的前一根）收盘已知值，避免用当日 ATR=未来数据：
         t+2 判定用 ATR(t+1)、t+3 用 ATR(t+2)…
  一切计算用 ≤当日/前一日 数据；触发后 t+1 开盘成交。
产出本目录 detail_atr4static.*（交易记录）+ 供统计/分类复用。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
A7 = HERE.parent
PROJ = A7.parents[1]
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from atr14_precompute import load_atr14            # noqa: E402

ATR_MULT = 4.0
MIN_DEGREE = 2


def simulate(g: pd.DataFrame, atr: np.ndarray, sig_i: int, close_sig: float) -> dict | None:
    """t+1 开盘入场 → 两线并行；吊灯 ATR 取前一日（判定日的前一根），无未来。"""
    n = len(g)
    if sig_i + 1 >= n:
        return None
    opens, highs, closes = g["open"].values, g["high"].values, g["close"].values
    dates = g["date"].values
    base = float(opens[sig_i + 1])                    # t+1 开盘 = 入场价
    a_sig = atr[sig_i]
    if a_sig is None or np.isnan(a_sig) or a_sig <= 0:
        return None
    stop_line = float(close_sig) - ATR_MULT * float(a_sig)   # ① t 日定死的止损线
    max_hi = float(np.nanmax(highs[sig_i:sig_i + 1]))        # t 日起最高（含信号日）
    for k in range(sig_i + 1, n):                     # t+1 起逐日
        hk, ck = highs[k], closes[k]
        if not np.isnan(hk):
            max_hi = max(max_hi, float(hk))           # 移动止盈基准（至当日）
        if np.isnan(ck):
            continue
        if ck < stop_line:                            # ① 静态止损（t 日线，无 ATR 依赖）
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ck / base - 1.0, "exit_reason": "stop_4atr",
                    "hold_bars": k - sig_i, "max_high": max_hi}
        a_prev = atr[k - 1]                           # ② 吊灯 ATR = 前一日（无未来）
        if a_prev is not None and not np.isnan(a_prev) and a_prev > 0 \
                and ck < max_hi - ATR_MULT * float(a_prev):
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ck / base - 1.0, "exit_reason": "chandelier",
                    "hold_bars": k - sig_i, "max_high": max_hi}
    return {"base": base, "exit_date": None, "exit_price": np.nan,
            "ret": np.nan, "exit_reason": "pending", "hold_bars": n - 1 - sig_i,
            "max_high": max_hi}


def main():
    ev = pd.read_parquet(A7 / "v3_events_cache.parquet")
    ev["date"] = pd.to_datetime(ev["date"])
    events = ev[ev["degree"] >= MIN_DEGREE].copy()
    print(f"事件 {len(events)}（degree>={MIN_DEGREE}）")

    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])
    groups = {s: g.sort_values("date").reset_index(drop=True)
              for s, g in market.groupby("symbol")}
    atr_df = load_atr14(PROJ / "_market_hs300_panel.parquet", SHARED)
    atr_by_sym = {s: x.set_index("date")["atr14"] for s, x in atr_df.groupby("symbol")}

    rows = []
    for sym, evs in events.groupby("symbol"):
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
                         "sig_i": r.sig_i, "stop_line": None,
                         **sim, "result": result, "reason": reason2})
    det = pd.DataFrame(rows)
    det.to_parquet(HERE / "detail_atr4static.parquet", index=False)
    det.to_csv(HERE / "detail_atr4static.csv", index=False, encoding="utf-8-sig")

    dec = det[det["result"].isin(["success", "fail"])].copy()
    n_s, n_f = int((dec.result == "success").sum()), int((dec.result == "fail").sum())
    wins, losses = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
    print(f"已判定 {len(dec)}：成功 {n_s} / 失败 {n_f} | 胜率 {n_s/len(dec)*100:.1f}% | "
          f"期望 {dec['ret'].mean()*100:+.2f}% | 盈亏比 "
          f"{wins.mean()/abs(losses.mean()):.2f} | 持仓中位 {dec['hold_bars'].median():.0f} bar")
    print("离场构成:", dec["reason"].value_counts().to_dict())
    print(f"写出 detail_atr4static.parquet/csv（{len(det)} 行）")


if __name__ == "__main__":
    main()
