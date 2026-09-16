"""analysis_014/volume 更新七 — 生成**中证500 的纯 v4 活带交易记录**。

口径 = analysis_012/v4_backtest/v4_backtest.py 的 `simulate()` **逐字照搬**：
  · 信号   v4 **活带** break_up 突破（死带不参与）
  · 入场   t 收盘出信号 → **t+1 开盘**成交（base = open[sig_i+1]）
  · 止损   静态 4×ATR14(信号日) 硬止损：close < close_sig − 4×ATR[sig_i]
  · 止盈   前日 ATR 吊灯：close < 持仓最高 − 4×ATR14[k−1]
  · 判定   stop_4atr → fail；chandelier → ret>0 ? success : fail；未触发 → pending
  · **无** COMBO 排序 / MA200 闸门 / 阀门 θ / 形态过滤 / degree 过滤（用户指定：全 degree）

与 HS300 版 `analysis_012/v4_backtest/detail_v4.parquet`（11,100 笔，deg≥2）的唯一差异 = 池子与
**不做 degree 过滤**。

产物：detail_v4_csi500.parquet / detail_v4_csi500.csv（交易记录，供后续迭代）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[3]
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from atr_csi500 import load_atr_csi500            # noqa: E402  ⚠ 独立缓存，勿用 shared 的

PANEL = HERE / "_market_csi500_panel.parquet"
EVENTS = HERE / "v4_events_csi500.parquet"
ATR_MULT = 4.0


def simulate(g: pd.DataFrame, atr: np.ndarray, sig_i: int, close_sig: float) -> dict | None:
    """逐字照搬 analysis_012/v4_backtest/v4_backtest.py::simulate。"""
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


def main():
    ev = pd.read_parquet(EVENTS)
    ev["date"] = pd.to_datetime(ev["date"])
    print(f"事件 {len(ev):,} 条（全 degree {ev.degree.min()}~{ev.degree.max()}，不做过滤）")

    market = pd.read_parquet(PANEL)
    market["date"] = pd.to_datetime(market["date"])
    groups = {s: x.sort_values("date").reset_index(drop=True)
              for s, x in market.groupby("symbol")}
    atr_df = load_atr_csi500(HERE)
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
    det = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    det.to_parquet(HERE / "detail_v4_csi500.parquet", index=False)
    det.to_csv(HERE / "detail_v4_csi500.csv", index=False, encoding="utf-8-sig")

    dec = det[det["result"].isin(["success", "fail"])]
    w, l = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
    print(f"\n═══ 中证500 纯 v4 活带（无 COMBO / 无 MA200 / 无阀门 / 无 degree 过滤）═══")
    print(f"已判定 {len(dec):,} 笔：成功 {(dec.result=='success').sum():,} / "
          f"失败 {(dec.result=='fail').sum():,} | 胜率 {(dec.result=='success').mean()*100:.1f}% | "
          f"失败率 {(dec.ret<=0).mean()*100:.1f}%")
    print(f"期望 {dec.ret.mean()*100:+.2f}% | 中位 {dec.ret.median()*100:+.2f}% | "
          f"肥尾率 {(dec.ret>=0.30).mean()*100:.1f}% | 盈亏比 {w.mean()/abs(l.mean()):.2f} | "
          f"持仓中位 {dec.hold_bars.median():.0f} bar")
    print("离场:", dec["reason"].value_counts().to_dict())


if __name__ == "__main__":
    main()
