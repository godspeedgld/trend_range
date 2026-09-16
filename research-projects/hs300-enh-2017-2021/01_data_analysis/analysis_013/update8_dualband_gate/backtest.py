"""更新八 · 组合回测 — 更新七分桶甜点兑现：双带闸门 + 30 坑（对照 update6 的 [0,10)）。

更新七发现本套信号（形态×2/4ATR 出场）甜点为双峰：[0,3%) 最强 + <-6% 深线下次甜，
[0,6%) 带 26% 交易贡献 100% 期望，而 [6,10%) 是负区。据此测两个闸门（均 30 坑、其余规则
同更新五/六）：
  dual    ：dev<−6%  ∪ [0,+6%)   ← 我的建议（双带吃双峰）
  band06  ：[0,+6%)               ← 单带归因（双带里深线下段的增量贡献）
输出 runs/{dual,band06}/ 各一套 backtest_logs，供对照 update6([0,10)) / update5(无闸门)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
U5 = HERE.parent / "update5_pattern_portfolio"
PROJ = HERE.parents[2]
WAREHOUSE = PROJ.parents[2] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"

PATTERNS = {"旗形", "上升通道收敛", "上升通道发散", "下降通道收敛", "上升三角形"}
ATR_N, K_STOP, K_CHAND = 14, 2.0, 4.0
NOTIONAL, MAX_POS = 100_000.0, 30
CASH0 = NOTIONAL * MAX_POS
W = NOTIONAL / CASH0
COST = 15 / 1e4
POOL_DAYS = 5


def gate_mask(dev: pd.Series, mode: str) -> pd.Series:
    if mode == "dual":
        return (dev < -0.06) | ((dev >= 0.0) & (dev < 0.06))
    if mode == "band06":
        return (dev >= 0.0) & (dev < 0.06)
    if mode == "band10":                       # update6 参照
        return (dev >= 0.0) & (dev < 0.10)
    raise ValueError(mode)


def run(mode: str):
    sig = pd.read_parquet(U5 / "signals_v2_members.parquet")
    ok = sig["dur_pattern"].isin(PATTERNS) | sig["chan_pattern"].isin(PATTERNS)
    ev = sig[sig["breakout"] & ok]

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                      "ORDER BY date").fetchdf()
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    s = idx.set_index("date")["close"]
    ma200 = s.rolling(200).mean()
    dev = (s - ma200) / ma200
    gate = set(dev.index[gate_mask(dev, mode)])
    ev = ev[ev["date"].isin(gate)]
    events = {d: set(g["symbol"]) for d, g in ev.groupby("date")}
    n_gate_days = len(gate)

    panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet",
                            columns=["date", "symbol", "open", "high", "low", "close"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    dates = [pd.Timestamp(d) for d in sorted(panel["date"].unique())]
    bars, atr = {}, {}
    for s_, g in panel.groupby("symbol"):
        g = g.set_index("date").sort_index()
        bars[s_] = g[["open", "high", "low", "close"]]
        pc = g["close"].shift(1)
        tr = pd.concat([g["high"] - g["low"], (g["high"] - pc).abs(),
                        (g["low"] - pc).abs()], axis=1).max(axis=1)
        atr[s_] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()

    pend, hold, trades, rets = {}, {}, [], []
    max_conc = 0
    for d in dates:
        r_day = 0.0
        for s_ in sorted(pend, key=lambda x: pend[x][0], reverse=True):
            if len(hold) >= MAX_POS:
                break
            sd, s_atr = pend[s_]
            b = bars.get(s_)
            if b is None or d not in b.index:
                if (d - sd).days > POOL_DAYS:
                    del pend[s_]
                continue
            o = float(b.at[d, "open"])
            sc = float(b.at[sd, "close"]) if sd in b.index else None
            del pend[s_]
            if o <= 0 or (sc and o / sc - 1.0 > 0.095):
                continue
            hold[s_] = {"entry_px": o, "stop": o - K_STOP * s_atr,
                        "peak": float(b.at[d, "high"]), "entry_date": d, "prev_close": o}
            r_day -= W * COST
        for s_ in [k for k, v in pend.items() if (d - v[0]).days > POOL_DAYS]:
            del pend[s_]
        for s_ in list(hold):
            h = hold[s_]
            b = bars.get(s_)
            if b is None or d not in b.index:
                continue
            lo, o, c = float(b.at[d, "low"]), float(b.at[d, "open"]), float(b.at[d, "close"])
            a = atr[s_].at[d] if d in atr[s_].index else np.nan
            if not np.isfinite(a) or a <= 0:
                continue
            floor = max(h["stop"], h["peak"] - K_CHAND * a)
            if lo <= floor:
                xp = min(o, floor)
                r_day += W * (xp / h["prev_close"] - 1.0) - W * COST
                trades.append({"symbol": s_, "entry_date": str(h["entry_date"].date()),
                               "entry_price": round(h["entry_px"], 3), "exit_date": str(d.date()),
                               "exit_price": round(xp, 3),
                               "ret_pct": round((xp / h["entry_px"] - 1) * 100, 3),
                               "reason": "止损" if floor == h["stop"] else "吊灯",
                               "hold_days": int((d - h["entry_date"]).days)})
                del hold[s_]
                continue
            h["peak"] = max(h["peak"], float(b.at[d, "high"]))
            r_day += W * (c / h["prev_close"] - 1.0)
            h["prev_close"] = c
        for s_ in events.get(d, ()):
            if s_ in hold or s_ in pend:
                continue
            a = atr.get(s_)
            if a is None or d not in a.index or not np.isfinite(a.at[d]) or a.at[d] <= 0:
                continue
            pend[s_] = (d, float(a.at[d]))
        rets.append({"date": d, "ret": r_day, "n_hold": len(hold)})
        max_conc = max(max_conc, len(hold))

    d = dates[-1]
    for s_, h in hold.items():
        b = bars.get(s_)
        c = float(b["close"].iloc[-1]) if b is not None and len(b) else h["prev_close"]
        trades.append({"symbol": s_, "entry_date": str(h["entry_date"].date()),
                       "entry_price": round(h["entry_px"], 3), "exit_date": str(d.date()),
                       "exit_price": round(c, 3), "ret_pct": round((c / h["entry_px"] - 1) * 100, 3),
                       "reason": "期末", "hold_days": int((d - h["entry_date"]).days)})

    ret = pd.DataFrame(rets).set_index("date")
    r = ret["ret"]
    tr = pd.DataFrame(trades)
    nav = 1 + r.cumsum()
    wins, losses = tr[tr.ret_pct > 0].ret_pct, tr[tr.ret_pct <= 0].ret_pct
    dd = (nav / nav.cummax() - 1).min()
    yrs = len(r) / 252
    metrics = {"n_trades": len(tr),
               "win_rate_pct": round(len(wins) / len(tr) * 100, 1),
               "payoff": round(wins.mean() / abs(losses.mean()), 2),
               "avg_ret_pct": round(tr.ret_pct.mean(), 3),
               "avg_hold_days": round(tr.hold_days.mean(), 1),
               "total_return_pct": round((nav.iloc[-1] - 1) * 100, 1),
               "annual_pct": round((nav.iloc[-1] ** (1 / yrs) - 1) * 100, 2),
               "sharpe": round(r.mean() / r.std() * 15.87, 2) if r.std() > 0 else None,
               "maxDD_pct": round(dd * 100, 1),
               "avg_concurrent": round(float(ret["n_hold"].mean()), 1),
               "max_concurrent": max_conc,
               "n_gate_days": n_gate_days,
               "reason_split": tr.reason.value_counts().to_dict(),
               "yearly_pct": (r.groupby(r.index.year).sum() * 100).round(1).to_dict()}
    logs = HERE / "runs" / mode / "backtest_logs"
    logs.mkdir(parents=True, exist_ok=True)
    ret.assign(nav=nav).to_csv(logs / "nav.csv")
    tr.to_csv(logs / "trades.csv", index=False, encoding="utf-8-sig")
    (logs / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), "utf-8")
    print(f"[{mode}] 闸门日 {n_gate_days} | {json.dumps({k: v for k, v in metrics.items() if k != 'yearly_pct'}, ensure_ascii=False)}")
    return metrics


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "dual"
    run(mode)
