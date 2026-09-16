"""更新五 · 组合回测 — 沪深300 成分股 × v2 动态窗形态突破（用户规则，2026-09-09）。

  开仓：收盘 > v2 分位回归压力线 + 形态 ∈ {旗形, 上升通道收敛, 上升通道发散, 下降通道收敛,
        上升三角形}（dur/chan 任一命中）→ t+1 开盘成交；次日无 bar 则 5 自然日内下一根开，
        再无则弃；开盘较信号收盘跳空 > +9.5%（近似涨停）不追（保守，显式假设）
  平仓：止损 = 成交价 − 2×ATR14(信号日)（静态）；吊灯 = 入场以来最高 high − 4×ATR14(当日)
        （移动）；盘中 low 触发 floor=max(两者)，成交价 = min(open, floor)（跳空按开盘）
  仓位：每只固定 10 万名义（不复利），无坑位上限——满足即开（无优先级筛选）。
        初始本金口径 100 万、权重 0.1/只；并发 >10 只 = 隐性杠杆（max_concurrent 记录）
  成本：15bps 双边；停牌日冻结（无 bar 不盯市不离场）；数据末仍持仓按末日收盘强平（记"期末"）
  铁律：t 收盘决策 → t+1 开盘执行；信号/成分只用 ≤t 数据（成分过滤在 scan 阶段完成）
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
WAREHOUSE = PROJ.parents[2] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"

PATTERNS = {"旗形", "上升通道收敛", "上升通道发散", "下降通道收敛", "上升三角形"}
ATR_N, K_STOP, K_CHAND = 14, 2.0, 4.0
NOTIONAL, CASH0 = 100_000.0, 1_000_000.0
W = NOTIONAL / CASH0
COST = 15 / 1e4
POOL_DAYS = 5


def main():
    sig = pd.read_parquet(HERE / "signals_v2_members.parquet")
    ok = sig["dur_pattern"].isin(PATTERNS) | sig["chan_pattern"].isin(PATTERNS)
    ev = sig[sig["breakout"] & ok]
    events = {d: set(g["symbol"]) for d, g in ev.groupby("date")}
    print(f"形态过滤后突破信号 {len(ev)} 日次（{ev['date'].min().date()} ~ {ev['date'].max().date()}）")

    panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet",
                            columns=["date", "symbol", "open", "high", "low", "close"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.dropna(subset=["open", "high", "low", "close"]).sort_values("date")
    dates = [pd.Timestamp(d) for d in sorted(panel["date"].unique())]
    bars, atr = {}, {}
    for s, g in panel.groupby("symbol"):
        g = g.set_index("date").sort_index()
        bars[s] = g[["open", "high", "low", "close"]]
        pc = g["close"].shift(1)
        tr = pd.concat([g["high"] - g["low"], (g["high"] - pc).abs(),
                        (g["low"] - pc).abs()], axis=1).max(axis=1)
        atr[s] = tr.ewm(alpha=1 / ATR_N, adjust=False).mean()

    pend, hold, trades, rets = {}, {}, [], []
    max_conc = 0

    for d in dates:
        r_day = 0.0
        # ── 开盘：执行挂单（只建仓+扣成本；当日盯市统一由盘中循环处理）──
        for s in list(pend):
            sd, s_atr = pend[s]
            if (d - sd).days > POOL_DAYS:
                del pend[s]
                continue
            b = bars.get(s)
            if b is None or d not in b.index:
                continue
            o = float(b.at[d, "open"])
            sc = float(b.at[sd, "close"]) if sd in b.index else None
            del pend[s]
            if o <= 0 or (sc and o / sc - 1.0 > 0.095):
                continue
            hold[s] = {"entry_px": o, "stop": o - K_STOP * s_atr, "peak": float(b.at[d, "high"]),
                       "entry_date": d, "prev_close": o}
            r_day -= W * COST
        # ── 盘中+收盘：止损/吊灯触发 或 盯市 ──
        for s in list(hold):
            h = hold[s]
            b = bars.get(s)
            if b is None or d not in b.index:
                continue                                  # 停牌冻结
            lo, o, c = float(b.at[d, "low"]), float(b.at[d, "open"]), float(b.at[d, "close"])
            a = atr[s].at[d] if d in atr[s].index else np.nan
            if not np.isfinite(a) or a <= 0:
                continue
            floor = max(h["stop"], h["peak"] - K_CHAND * a)
            if lo <= floor:
                xp = min(o, floor)
                r_day += W * (xp / h["prev_close"] - 1.0) - W * COST
                trades.append({"symbol": s, "entry_date": str(h["entry_date"].date()),
                               "entry_price": round(h["entry_px"], 3), "exit_date": str(d.date()),
                               "exit_price": round(xp, 3),
                               "ret_pct": round((xp / h["entry_px"] - 1) * 100, 3),
                               "reason": "止损" if floor == h["stop"] else "吊灯",
                               "hold_days": int((d - h["entry_date"]).days)})
                del hold[s]
                continue
            h["peak"] = max(h["peak"], float(b.at[d, "high"]))
            r_day += W * (c / h["prev_close"] - 1.0)
            h["prev_close"] = c
        # ── 收盘：新信号挂单（不与持仓/挂单重复）──
        for s in events.get(d, ()):
            if s in hold or s in pend:
                continue
            a = atr.get(s)
            if a is None or d not in a.index or not np.isfinite(a.at[d]) or a.at[d] <= 0:
                continue
            pend[s] = (d, float(a.at[d]))
        rets.append({"date": d, "ret": r_day, "n_hold": len(hold)})
        max_conc = max(max_conc, len(hold))

    # ── 数据末强平 ──
    d = dates[-1]
    for s, h in hold.items():
        b = bars.get(s)
        c = float(b["close"].iloc[-1]) if b is not None and len(b) else h["prev_close"]
        trades.append({"symbol": s, "entry_date": str(h["entry_date"].date()),
                       "entry_price": round(h["entry_px"], 3), "exit_date": str(d.date()),
                       "exit_price": round(c, 3), "ret_pct": round((c / h["entry_px"] - 1) * 100, 3),
                       "reason": "期末", "hold_days": int((d - h["entry_date"]).days)})

    ret = pd.DataFrame(rets).set_index("date")
    r = ret["ret"]
    tr = pd.DataFrame(trades)
    nav = 1 + r.cumsum()                                   # 固定名义加总口径（W 固定）
    avg_conc = float(ret["n_hold"].mean())
    used_cap = float(ret["n_hold"].max()) * NOTIONAL       # 峰值占用资金
    wins, losses = tr[tr.ret_pct > 0].ret_pct, tr[tr.ret_pct <= 0].ret_pct
    dd = (nav / nav.cummax() - 1).min()
    yrs = len(r) / 252
    metrics = {"n_trades": len(tr),
               "win_rate_pct": round(len(wins) / len(tr) * 100, 1),
               "payoff": round(wins.mean() / abs(losses.mean()), 2),
               "avg_ret_pct": round(tr.ret_pct.mean(), 3),
               "avg_hold_days": round(tr.hold_days.mean(), 1),
               "total_return_pct_100w_base": round((nav.iloc[-1] - 1) * 100, 1),
               "avg_concurrent": round(avg_conc, 1),
               "max_concurrent": max_conc,
               "peak_capital_wan": round(used_cap / 1e4, 0),
               "total_pnl_wan": round((nav.iloc[-1] - 1) * CASH0 / 1e4, 1),
               "annual_pct_on_peakcap": round(((nav.iloc[-1]) ** (1 / yrs) - 1) * 100, 2),
               "sharpe_100w": round(r.mean() / r.std() * 15.87, 2) if r.std() > 0 else None,
               "maxDD_pct": round(dd * 100, 1),
               "reason_split": tr.reason.value_counts().to_dict(),
               "yearly_pct_on_100w": (r.groupby(r.index.year).sum() * 100).round(1).to_dict()}
    logs = HERE / "backtest_logs"
    logs.mkdir(exist_ok=True)
    ret.assign(nav=nav).to_csv(logs / "nav.csv")
    tr.to_csv(logs / "trades.csv", index=False, encoding="utf-8-sig")
    (logs / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=1))
    return metrics


if __name__ == "__main__":
    main()
