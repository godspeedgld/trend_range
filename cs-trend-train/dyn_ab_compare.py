"""三套止盈口径的总账对比（只读，不改数据；结论见 README「已知限制」第 10 条）：静态 / 吊灯·现行 / 吊灯·标准。

统计公式**逐字对齐 trades.html 的 stats()**（胜率/盈亏比/期望R/夏普/肥尾率/最大回撤/Σ盈亏），
派生量复用 server.py 的 `_metrics()`（与页面同源）。

用法：python dyn_ab_compare.py
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load_server():
    spec = importlib.util.spec_from_file_location("srv_cmp", HERE / "server.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["srv_cmp"] = m
    spec.loader.exec_module(m)
    return m


def metrics_of(srv, rec, ex, pts_real):
    """按 server.decorate 的口径算派生量（R/ret_pct/pnl/status）。"""
    is_fut = rec.get("source") == "future"
    buy, stop = rec.get("buy_price"), rec.get("stop_price")
    mult = rec.get("multiplier") or 1
    if is_fut:
        rb, rs = rec.get("real_buy_price"), rec.get("real_stop_price")
        rps = abs(rb - rs) if (rb is not None and rs is not None) else None
        buy_ref = rb if rb is not None else buy
    else:
        rps = abs(buy - stop) if (buy is not None and stop is not None) else None
        buy_ref = buy
    short = (rec.get("direction") or "long") == "short"
    return srv._metrics(ex, pts_real, short, buy, buy_ref, rps, rec.get("shares"), mult, is_fut)


def agg(srv, rows):
    """rows = [(rec, m)] → 与 trades.html stats() 同式的汇总。"""
    closed = [(r, m) for r, m in rows if m["status"] != "pending" and m["R"] is not None]
    Rs = [m["R"] for _, m in closed]
    wins = [x for x in Rs if x > 0]
    losses = [x for x in Rs if x < 0]
    mean = lambda a: sum(a) / len(a) if a else None
    sd = lambda a: (math.sqrt(sum((x - mean(a)) ** 2 for x in a) / (len(a) - 1))
                    if len(a) > 1 else None)
    held = [r.get("entry_date") and m for r, m in closed if (m.get("_hd") or 0) > 0]
    hd = [m["_hd"] for _, m in closed if (m.get("_hd") or 0) > 0]
    sumR = sum(Rs)
    # 累计 R 路径最大回撤
    peak = 0.0; acc = 0.0; mdd = 0.0
    for _, m in closed:
        acc += m["R"]; peak = max(peak, acc); mdd = min(mdd, acc - peak)
    sumPnl = sum(m["pnl"] for _, m in closed if m.get("pnl") is not None) \
        if any(m.get("pnl") is not None for _, m in closed) else None
    tails = [m["ret_pct"] for _, m in closed if m.get("ret_pct") is not None]
    return dict(
        n=len(closed), pend=len(rows) - len(closed),
        winRate=(len(wins) / len(Rs) * 100 if Rs else None),
        payoff=(mean(wins) / abs(mean(losses)) if (wins and losses and mean(losses)) else None),
        expR=mean(Rs), sumR=sumR, mddR=mdd,
        avgHold=mean(hd) if hd else None,
        sharpe=((mean(Rs) / sd(Rs)) * math.sqrt(252 / mean(hd)) if (sd(Rs) and hd and mean(hd)) else None),
        tail=(sum(1 for t in tails if t >= 30) / len(tails) * 100 if tails else None),
        sumPnl=sumPnl)


def main():
    srv = load_server()
    variants = {"静态（固定止盈）": [], "吊灯·现行": [], "吊灯·标准": []}
    rows_diff = []
    for f, src in (("data/trades.json", "stock"), ("data/trades_future.json", "future")):
        db = json.load(open(HERE / f, encoding="utf-8"))
        for sym, lst in db.items():
            for r in lst:
                m_s = metrics_of(srv, r, r.get("exit_price"), r.get("pts_real"))
                m_s["_hd"] = r.get("holding_days")
                d1 = srv.chandelier_exit(sym, r, src, standard=False)
                d2 = srv.chandelier_exit(sym, r, src, standard=True)
                rec1 = dict(r, **d1, source=src)   # 已回填记录 = 现行口径
                rec2 = dict(r, **d2, source=src)
                m1 = metrics_of(srv, rec1, rec1["dyn_exit_price"],
                                rec1.get("dyn_pts_real"))
                m2 = metrics_of(srv, rec2, rec2["dyn_exit_price"], rec2.get("dyn_pts_real"))
                m1["_hd"], m2["_hd"] = d1["dyn_holding_days"], d2["dyn_holding_days"]
                variants["静态（固定止盈）"].append((r, m_s))
                variants["吊灯·现行"].append((r, m1))
                variants["吊灯·标准"].append((r, m2))
                rows_diff.append({"sym": sym, "id": r.get("id"), "dir": r.get("direction") or "long",
                                  "entry": r.get("entry_date"), "R": m_s["R"],
                                  "R_现行": m1["R"], "R_标准": m2["R"]})

    print("=" * 96)
    print(f"{'口径':<16}{'已平仓':>6}{'胜率%':>8}{'盈亏比':>8}{'期望R':>8}{'ΣR':>8}"
          f"{'R回撤':>8}{'均持仓':>8}{'夏普':>7}{'肥尾%':>7}{'Σ盈亏(元)':>12}")
    print("-" * 96)
    for name, rows in variants.items():
        a = agg(srv, rows)
        f = lambda v, n=2: "—" if v is None else f"{v:.{n}f}"
        pnl = "—" if a["sumPnl"] is None else f"{a['sumPnl']:,.0f}"
        print(f"{name:<16}{a['n']:>6}{f(a['winRate'],1):>8}{f(a['payoff']):>8}{f(a['expR']):>8}"
              f"{f(a['sumR']):>8}{f(a['mddR']):>8}{f(a['avgHold'],1):>8}{f(a['sharpe']):>7}"
              f"{f(a['tail'],1):>7}{pnl:>12}")
    print("=" * 96)

    # 分方向
    print("\n分方向（做多 / 做空）—— 现行 vs 标准：")
    for d, tag in (("long", "做多"), ("short", "做空")):
        line = [f"{tag}({sum(1 for x in rows_diff if x['dir'] == d)} 笔)"]
        for key in ("R", "R_现行", "R_标准"):
            vals = [x[key] for x in rows_diff if x["dir"] == d and x[key] is not None]
            line.append(f"{key} 均值 {sum(vals)/len(vals):+.3f}" if vals else f"{key} —")
        print("   " + " | ".join(line))

    # 现行 vs 标准 差异最大的几笔
    print("\n现行 ↔ 标准 差异最大的 8 笔（按 |ΔR|）：")
    rows_diff.sort(key=lambda x: -abs((x["R_标准"] or 0) - (x["R_现行"] or 0)))
    print(f"   {'标的':<12}{'方向':<5}{'开仓':<12}{'静态R':>8}{'现行R':>8}{'标准R':>8}")
    for x in rows_diff[:8]:
        f = lambda v: "—" if v is None else f"{v:+.2f}"
        print(f"   {x['sym']:<12}{'空' if x['dir']=='short' else '多':<5}{x['entry']:<12}"
              f"{f(x['R']):>8}{f(x['R_现行']):>8}{f(x['R_标准']):>8}")


if __name__ == "__main__":
    main()
