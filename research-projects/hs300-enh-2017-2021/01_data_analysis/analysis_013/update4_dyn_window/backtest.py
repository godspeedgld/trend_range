"""analysis_013 更新四 — 动态窗口 v2（LOO 离群截断）：12 形态回测 A/B + 机制统计。

承接更新二框架（规则不变：开仓=空仓且 close>R（形态过滤）→次日开盘；止损=entry−3×ATR14(信号日)；
止盈=入场后最高−3×ATR14(当日)；满仓；单边 10bps）。唯一变化：画线 v1（固定120）→ v2
（动态窗口，shared/quantreg_sr_algo_v2.py）。v1 结果直接读 ../update2_pattern_backtests/ 做 A/B。

产物：signals_v2.parquet（含 win_len/truncated）/ runs/{12}/ / summary_table.csv（v1 vs v2 并排）/
mechanism_stats.txt（截断率、窗长分布、形态标签漂移、突破数对比）
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
U2 = HERE.parent / "update2_pattern_backtests"
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ / "shared"))
from quantreg_sr_algo import DURATION_PATTERNS, breakout_signals  # noqa: E402
from quantreg_sr_algo_v2 import rolling_lines_v2  # noqa: E402

ATR_N, ATR_K, COST = 14, 3.0, 10 / 1e4
warnings.filterwarnings("ignore", module="statsmodels.*")


def atr14(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_N, adjust=False).mean()


def simulate(df, sig, atr, run_name):
    n = len(df)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    dates = df["date"]
    R = sig["R"].reindex(dates).to_numpy()
    has_line = sig["R"].reindex(dates).notna().to_numpy()
    dur = sig["dur_pattern"].reindex(dates).to_numpy()
    chan = sig["chan_pattern"].reindex(dates).to_numpy()
    rets = np.zeros(n)
    trades, i = [], 0
    while i < n - 1:
        entry_ok = has_line[i] and c[i] > R[i] and (
            run_name == "全部对照" or dur[i] == run_name or chan[i] == run_name)
        if not entry_ok:
            i += 1
            continue
        e, ep = i + 1, o[i + 1]
        floor_static, peak = ep - ATR_K * atr[i], h[i + 1]
        j, xp = e, np.nan
        for j in range(e, n):
            floor = max(floor_static, peak - ATR_K * atr[j])
            if l[j] <= floor:
                xp = min(o[j], floor)
                break
            peak = max(peak, h[j])
        else:
            j, xp = n - 1, c[n - 1]
        trades.append({"entry_date": dates[e].date(), "entry_price": round(ep, 2),
                       "exit_date": dates[j].date(), "exit_price": round(xp, 2),
                       "ret_pct": round((xp / ep - 1) * 100, 3), "reason": "止损/止盈",
                       "hold_days": int(j - e + 1)})
        rets[e] = (c[e] / ep - 1) - COST
        for k in range(e + 1, j):
            rets[k] = c[k] / c[k - 1] - 1
        if j > e:
            rets[j] = (xp / c[j - 1] - 1) - COST
        else:
            rets[e] = (xp / ep - 1) - 2 * COST
        i = j
    return rets, trades


def metrics(rets, trades):
    nav = np.cumprod(1 + rets)
    r = pd.Series(rets)
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    t = pd.DataFrame(trades)
    wins, losses = t[t.ret_pct > 0].ret_pct, t[t.ret_pct <= 0].ret_pct
    return {"n_trades": len(t),
            "win_rate_pct": round(len(wins) / len(t) * 100, 1) if len(t) else np.nan,
            "payoff": round(wins.mean() / abs(losses.mean()), 2) if len(wins) and len(losses) and losses.mean() != 0 else np.nan,
            "total_return_pct": round((nav[-1] - 1) * 100, 1),
            "annual_pct": round((nav[-1] ** (252 / len(rets)) - 1) * 100, 2),
            "sharpe": round(r.mean() / r.std() * np.sqrt(252), 2) if r.std() > 0 else np.nan,
            "maxDD_pct": round(dd * 100, 1)}


def main():
    idx = pd.read_parquet(U2 / "hs300_index.parquet")
    df = idx.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    atr = atr14(df).to_numpy()

    sig = breakout_signals(rolling_lines_v2(df, causal=True), df["close"])
    sig.to_parquet(HERE / "signals_v2.parquet")

    # ── 机制统计（v1 signals 来自 update3 缓存）──
    sig1 = pd.read_parquet(HERE.parent / "update3_breakout_lines" / "lines_causal.parquet")
    m = []
    m.append(f"有效线日: v1 {sig1['R'].notna().sum()} vs v2 {sig['R'].notna().sum()}")
    m.append(f"截断率(v2): {sig['truncated'].mean()*100:.1f}% | win_len 中位 {sig['win_len'].median():.0f} "
             f"均值 {sig['win_len'].mean():.0f}（p10 {sig['win_len'].quantile(.1):.0f} / p90 {sig['win_len'].quantile(.9):.0f}）")
    m.append(f"突破事件: v1 {int(sig1['breakout'].sum())} vs v2 {int(sig['breakout'].sum())}")
    for col in ("dur_pattern", "chan_pattern"):
        a = sig1.loc[sig1["breakout"], col].value_counts()
        b = sig.loc[sig["breakout"], col].value_counts()
        cmp = pd.DataFrame({"v1": a, "v2": b}).fillna(0).astype(int)
        m.append(f"\n突破日 {col} 分布 v1 vs v2:\n{cmp.to_string()}")
    (HERE / "mechanism_stats.txt").write_text("\n".join(map(str, m)), encoding="utf-8")
    print("\n".join(map(str, m)))

    # ── 12 回测（同更新二规则）──
    runs = ([(f"dur_{k}", k) for k in DURATION_PATTERNS]
            + [(f"chan_{k}", k) for k in ("上升通道收敛", "上升通道发散", "横盘",
                                          "下降通道收敛", "下降通道发散")]
            + [("all_全部对照", "全部对照")])
    rows = []
    for run_id, name in runs:
        rets, trades = simulate(df.reset_index(), sig, atr, name)
        mm = metrics(rets, trades)
        rd = HERE / "runs" / run_id
        rd.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(trades).to_csv(rd / "trades.csv", index=False, encoding="utf-8-sig")
        nav = pd.DataFrame({"date": df.index, "ret": rets})
        nav["nav"] = (1 + nav["ret"]).cumprod()
        nav.to_csv(rd / "nav.csv", index=False)
        (rd / "metrics.json").write_text(json.dumps(mm, ensure_ascii=False, indent=2), "utf-8")
        rows.append({"run_id": run_id, "形态": name, **mm})
    v2t = pd.DataFrame(rows)
    # A/B 并排
    v1t = pd.read_csv(U2 / "summary_table.csv")[["run_id", "n_trades", "total_return_pct",
                                                 "sharpe", "maxDD_pct", "win_rate_pct"]]
    ab = v2t.merge(v1t, on="run_id", suffixes=("_v2", "_v1"))
    ab.to_csv(HERE / "summary_table.csv", index=False, encoding="utf-8-sig")
    v2t.to_csv(HERE / "summary_v2_only.csv", index=False, encoding="utf-8-sig")
    print("\n== A/B（v2 动态窗口 vs v1 固定120）==")
    print(ab.to_string(index=False))


if __name__ == "__main__":
    main()
