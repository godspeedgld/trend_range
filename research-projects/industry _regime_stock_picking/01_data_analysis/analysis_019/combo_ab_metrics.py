"""analysis_019 附件 — 方向 A / B 组合的**完整指标**落盘（年化/波动/笔数/在场周数）。

背景：A（反转周在场率）与 B（镜像闸门，= strategy_008）作用在**同一层**（反转周 exposure），
必须量出「能不能叠加」。本脚本用同一引擎跑 6 个变体并落 `combo_ab_metrics.csv`。

两条硬结论（见 analysis_019/records.md）：
  ① **A 会整个抹掉 B**：`008+A` 逐值等于 `007+A`（7.3276/1.1395/−0.2142）——
     因为 B 只关「稳定周」（n_common=3），而 A 无条件重开所有 n_common≥2 的周。
  ② 顺序反过来才有意义：**B 后叠 A（严格序）= 6.0629 / 年化 21.21% / 波动 16.70% /
     Sharpe 1.2344 / DD −20.76%** —— 收益更高但 Sharpe 仍低于 008 的 1.2754
     ⇒ 是「收益侧前沿点」，不是改进。

前置：`analysis_019/analysis.py`（本目录）与本脚本共用 strategy_008/ab_engine_controls.py。
自检：基线 3.6001、007 4.5663、008 4.5535、007+A 7.3276（与 combo_ab.py 同口径）。
用法：python combo_ab_metrics.py    产物：combo_ab_metrics.csv
勘误：本脚本取代早先的 temp/combo_ab.py（后者只打印 nav/sharpe/dd，无波动与笔数）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
sys.path.insert(0, str(PROJ / "02_strategy_iteration" / "strategy_008"))
sys.path.insert(0, str(PROJ / "shared"))

from expand_targets_daily import expand_to_daily   # noqa: E402
import ab_engine_controls as A                     # noqa: E402


def main():
    sig, meta, cal = A.build_sig_full()
    mk = pd.read_parquet(A.CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])
    cfg = A.eng.WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0,
                                     sell_bps=13.0, min_cost=5.0)
    period = A.eng.TradingDaysRebalance(1)
    sig_dates = list(sig["date"].unique())
    s = sig.copy()
    s["_wk"] = s["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})
    w_tag = expand_to_daily(s[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}), cal)
    w_wgt = expand_to_daily(s[["date", "instrument", "weight"]], cal)
    ep = w_tag["weight"].values.astype(int) - 1
    w0 = w_wgt["weight"].values
    daily = w_wgt.rename(columns={"instrument": "symbol"})

    def run(flags):
        d = daily.copy()
        d["weight"] = w0 * np.array([flags.get(t, 1) for t in sig_dates], dtype=float)[ep]
        _, tr, _ = A.eng.run_weight_backtest(mk, d, cfg, period)
        _, m = A.eng.nav_from_trades(mk, tr, cfg.initial_cash)
        r = m.iloc[0].to_dict() if hasattr(m, "iloc") else dict(m)
        r["n_trades"] = len(tr)
        r["weeks_in_market"] = int(sum(1 for t in sig_dates if flags.get(t, 1) == 1))
        return r

    def base():
        return {t: (0 if not meta[t]["stable"] else 1) for t in meta}

    def g007(f):
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "momentum" and pd.notna(m["sc_mean"]) and m["sc_mean"] < 2.0:
                f[t] = 0
        return f

    def gB(f):
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "reversal" and pd.notna(m["sc_max"]) and m["sc_max"] >= 3:
                f[t] = 0
        return f

    def gA(f):
        for t, m in meta.items():
            if m["regime"] == "reversal" and m["n_common"] >= 2:
                f[t] = 1
        return f

    cases = {
        "基线": base(),
        "007": g007(base()),
        "008 = 007+B": gB(g007(base())),
        "007+A": gA(g007(base())),
        "008+A(B后叠A)": gA(gB(g007(base()))),
        "B后叠A(严格序)": gB(gA(g007(base()))),
    }
    rows = []
    for k, f in cases.items():
        r = run(f)
        rows.append({"variant": k, "nav": r["final_nav"], "ann": r["annual_return"],
                     "vol": r["annual_volatility"], "sharpe": r["sharpe"],
                     "dd": r["max_drawdown"], "n_trades": r["n_trades"],
                     "weeks_in_market": r["weeks_in_market"]})
        print(f"{k:<16} nav {r['final_nav']:.4f} ann {r['annual_return']:.4f} "
              f"vol {r['annual_volatility']:.4f} sharpe {r['sharpe']:.4f} "
              f"dd {r['max_drawdown']:.4f} trades {r['n_trades']} 在场 {r['weeks_in_market']}周",
              flush=True)

    g = pd.DataFrame(rows)
    g.to_csv(HERE / "combo_ab_metrics.csv", index=False)
    print("→", HERE / "combo_ab_metrics.csv")


if __name__ == "__main__":
    main()
