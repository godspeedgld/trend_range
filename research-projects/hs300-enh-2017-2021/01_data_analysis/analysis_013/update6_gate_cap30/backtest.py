"""更新六 · 组合回测 — 更新五规则 + 沪深300 指数偏离 MA200 闸门 [0,+10%) + 30 坑上限。

与更新五差异（仅两条，其余规则原样）：
  ① 开仓闸门：信号日 t 沪深300 (close−MA200)/MA200 ∈ [0, +10%) 才挂单（≤t 数据，无未来；
     analysis_012 补充6 的绝对区间口径；009-u2 同带）
  ② 坑位上限 30：每仓固定 10 万 → 初始本金口径 300 万（权重 1/30）。坑满时不新开；
     挂单竞争按【最近信号优先】（A_v2/006 框架惯例）
其余：形态过滤 {旗形,上升通道收敛,上升通道发散,下降通道收敛,上升三角形}；止损=成交价−
2×ATR14(信号日)；吊灯=入场后最高−4×ATR14(当日)（盘中 low 触发，跳空按开盘）；t 收盘→
t+1 开盘（跳空>+9.5% 不追；5 自然日内无 bar 弃单）；15bps 双边；停牌冻结；期末强平。
"""
from __future__ import annotations

import json
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
CASH0 = NOTIONAL * MAX_POS                 # 300 万基数
W = NOTIONAL / CASH0
COST = 15 / 1e4
POOL_DAYS = 5
DEV_LO, DEV_HI = 0.0, 0.10                 # 偏离闸门 [0, +10%)


def main():
    sig = pd.read_parquet(U5 / "signals_v2_members.parquet")
    ok = sig["dur_pattern"].isin(PATTERNS) | sig["chan_pattern"].isin(PATTERNS)
    ev = sig[sig["breakout"] & ok]

    # ── 偏离闸门（≤t，无未来）──
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                      "ORDER BY date").fetchdf()
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    s = idx.set_index("date")["close"]
    dev = (s - s.rolling(200).mean()) / s.rolling(200).mean()
    gate = set(dev.index[(dev >= DEV_LO) & (dev < DEV_HI)])
    ev = ev[ev["date"].isin(gate)]
    events = {d: set(g["symbol"]) for d, g in ev.groupby("date")}
    print(f"闸门后突破信号 {len(ev)} 日次（偏离样本 {dev.dropna().min():+.2%}~{dev.dropna().max():+.2%}，"
          f"闸门开启 {len(gate)} 日）")

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
        # ── 开盘：执行挂单（坑满不开；最近信号优先）──
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
        # ── 盘中+收盘：止损/吊灯 或 盯市 ──
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
        # ── 收盘：新信号挂单（闸门已在 events 过滤）──
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
               "reason_split": tr.reason.value_counts().to_dict(),
               "yearly_pct": (r.groupby(r.index.year).sum() * 100).round(1).to_dict()}
    logs = HERE / "backtest_logs"
    logs.mkdir(exist_ok=True)
    ret.assign(nav=nav).to_csv(logs / "nav.csv")
    tr.to_csv(logs / "trades.csv", index=False, encoding="utf-8-sig")
    (logs / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    return metrics


if __name__ == "__main__":
    main()
