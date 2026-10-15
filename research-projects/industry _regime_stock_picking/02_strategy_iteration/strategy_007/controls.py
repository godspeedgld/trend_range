"""strategy_007 · 对照组——验收反向量能闸门的两道关卡（进程内引擎）。

对照 1（随机周空仓）：从「动量周 & 满仓」的同一合格池里，随机关掉与真实闸门**同数量**的周
  （20 种子）→ 若主回测不超过随机分布 P95，说明增益只是「少在场」。
对照 2（熊市闸门）：信号日沪深300 收盘 < MA200 的周全部关掉（不限定动量/数量）——
  若熊市闸门 ≈ 量能闸门，说明量能闸只是市场状态代理；量能闸明显更好才有独立增量。
  同时报告两个闸门命中周的重叠率。

用法：python controls.py
产物：controls_summary.csv（records/报告引用）
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts"))

from build_weekly_targets import (                     # noqa: E402
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily       # noqa: E402
from local_weight_backtest import PERIODS, WeightBacktestConfig, run_weight_backtest  # noqa: E402

PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"
CROWD = CACHE / "industry_crowding_weekly.parquet"
SC_THR = 2.0
N_SEEDS, SEED0 = 20, 1001


def build_with_gate(panel, ind, reg, cal, crowd, gate_fn):
    """基线骨架 + 周级 exposure 闸门钩子（gate_fn(t, top3, regime, exposure) -> exposure）。"""
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}
    prev_top3, held, frames = None, {}, []
    gated_weeks = []
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), panel_by_day.get(t)
        if day is None or cand is None:
            continue
        top3, regime = pick_industries(day, float(regi.at[t, "T_prime"]))
        dirs = factor_directions("baseline", regime)
        targets = build_targets(cand, top3, dirs, held)
        exposure = 1.0 if (prev_top3 is None or set(top3) == set(prev_top3)) else 0.0
        ex2 = gate_fn(t, top3, regime, exposure, crowd)
        if ex2 == 0.0 and exposure == 1.0:
            gated_weeks.append(t)
        rows, held_next = [], {}
        for ind_name, syms in targets.items():
            if not syms:
                continue
            w = industry_weights(cand, syms)
            for s in syms:
                held_next[s] = ind_name
                rows.append({"instrument": s, "weight": float(ex2 * w[s] / N_IND)})
        frames.append(pd.DataFrame(rows, columns=["instrument", "weight"]).assign(date=t))
        held, prev_top3 = held_next, top3
    sig = pd.concat(frames, ignore_index=True)
    return expand_to_daily(sig, cal), gated_weeks


def crowd_gate(t, top3, regime, exposure, crowd):
    if regime == "momentum" and exposure == 1.0:
        sc = [crowd.get((t, p)) for p in top3]
        sc = [x for x in sc if x is not None and not np.isnan(x)]
        if sc and sum(sc) / len(sc) < SC_THR:
            return 0.0
    return exposure


def metrics(daily, trades):
    ret = pd.Series(daily["nav"].to_numpy(dtype=float)).pct_change().dropna()
    navf = float((1 + ret).prod())
    sd = ret.std(ddof=1)
    return {"final_nav": navf, "annual_return": navf ** (252 / len(ret)) - 1,
            "sharpe": float(ret.mean() / sd * np.sqrt(252)),
            "max_drawdown": float((ret.add(1).cumprod() / (1 + ret).cumprod().cummax() - 1).min()),
            "n_trades": int(len(trades))}


def main():
    panel = pd.read_parquet(PANEL)
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cdf = pd.read_parquet(CROWD)
    crowd = {(pd.Timestamp(w), i): float(s)
             for w, i, s in zip(cdf["week"], cdf["ind"], cdf["signal_count"])}
    market = pd.read_parquet(MARKET)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(market["date"]).unique()))
    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = PERIODS["trading_days"](1)

    # ── 真实闸门周（决定对照数量）──
    tg, gate_weeks = build_with_gate(panel, ind, reg, cal, crowd, crowd_gate)
    print(f"真实闸门关掉的周数: {len(gate_weeks)}")

    # 合格池：动量 & 满仓（真实闸门只能从这里选）
    base_tg, _ = build_with_gate(panel, ind, reg, cal, crowd, lambda *a: a[3])
    regi = reg.set_index("date")
    bl_sum = base_tg.groupby(pd.to_datetime(base_tg["date"]))["weight"].sum()
    eligible = []
    prev3 = None
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day = ind[ind["date"] == t]
        if day.empty:
            continue
        top3, regime = pick_industries(day, float(regi.at[t, "T_prime"]))
        inv = bl_sum.get(t, 0) > 0.05
        if regime == "momentum" and inv and (prev3 is None or set(top3) == set(prev3)):
            eligible.append(t)
        prev3 = top3
    print(f"合格池（动量 & 满仓周）: {len(eligible)}")

    rows = []
    # 真实闸门（与 CLI 同口径复算一遍）
    daily, trades, _ = run_weight_backtest(market, tg.rename(columns={"instrument": "symbol"}), cfg, period)
    rows.append({"variant": "crowdgate(真实)", **metrics(daily, trades), "n_gated": len(gate_weeks)})

    # 对照 1：随机同数关周
    for k in range(N_SEEDS):
        rng = np.random.default_rng(SEED0 + k)
        pick = set(rng.choice(eligible, size=min(len(gate_weeks), len(eligible)), replace=False))
        fn = lambda t, top3, regime, exposure, crowd, _pick=pick: \
            0.0 if (t in _pick and exposure == 1.0) else exposure
        tg2, _ = build_with_gate(panel, ind, reg, cal, crowd, fn)
        daily, trades, _ = run_weight_backtest(market, tg2.rename(columns={"instrument": "symbol"}), cfg, period)
        rows.append({"variant": f"random_seed{SEED0 + k}", **metrics(daily, trades),
                     "n_gated": len(pick)})

    # 对照 2：熊市闸门（沪深300 < MA200 的信号周关掉）
    import duckdb
    con = duckdb.connect(str(PROJ.parents[1] / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"),
                         read_only=True)
    hs = con.execute("""SELECT date, close FROM index_bar1d WHERE instrument='000300.SH'
                        AND date >= '2015-01-01'""").df()
    con.close()
    hs["date"] = pd.to_datetime(hs["date"])
    hs["ma200"] = hs["close"].rolling(200).mean()
    hs_idx = hs.set_index("date")
    bear_weeks = {t for t in sorted(panel["date"].unique())
                  if t in hs_idx.index and pd.notna(hs_idx.at[t, "ma200"])
                  and hs_idx.at[t, "close"] < hs_idx.at[t, "ma200"]}
    fn_bear = lambda t, top3, regime, exposure, crowd: \
        0.0 if (t in bear_weeks and exposure == 1.0) else exposure
    tg3, bear_gated = build_with_gate(panel, ind, reg, cal, crowd, fn_bear)
    daily, trades, _ = run_weight_backtest(market, tg3.rename(columns={"instrument": "symbol"}), cfg, period)
    rows.append({"variant": "bear_MA200(熊市闸)", **metrics(daily, trades), "n_gated": len(bear_gated)})

    df = pd.DataFrame(rows)
    df.to_csv(HERE.parent / "controls_summary.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(df.round(4).to_string(index=False))

    rnd = df[df["variant"].str.startswith("random")]
    from scipy import stats as sps
    print(f"\n随机对照分布: 中位 {rnd['final_nav'].median():.4f} / P95 {np.percentile(rnd['final_nav'],95):.4f}")
    print(f"真实闸门 {df.iloc[0]['final_nav']:.4f} 的分位: "
          f"{sps.percentileofscore(rnd['final_nav'], df.iloc[0]['final_nav'], kind='mean'):.0f}%")
    ov = len(set(gate_weeks) & set(bear_gated))
    print(f"量能闸 {len(gate_weeks)} 周 ∩ 熊市闸 {len(bear_gated)} 周 = {ov} 周（重叠率 {ov/max(1,len(gate_weeks)):.0%}）")


if __name__ == "__main__":
    main()
