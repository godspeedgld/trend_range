"""方向 A / B 的**引擎级随机对照**（2026-10-16）。

上游发现：引擎结果与 nav 级判决**相反**——
  B3（007+镜像 max>=3）Sharpe 1.2754 / DD −18.4% vs 007 1.1449 / −22.5%（净值持平）
  A2（007+反转周≥2相同）nav 7.3276 / Sharpe 1.1395 / DD −21.4% vs 007 4.5663 / 1.1449 / −22.5%
⇒ 必须过随机对照，否则无法区分「规则有信息」vs「多/少在场的平凡效应」。

做法：**一次建表**（所有周 exposure=1 的周频 targets），此后任意在场规则 = 按周把 weight
缩放到 0；股票选择不随 exposure 变（buffer/held 链与 exposure 无关）⇒ 可复用。
引擎**进程内**调用（行情只读一次）。

自检：V0 基线应回 3.6001、V1(007) 应回 4.5663。
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]        # 归档后位于 <PROJ>/02_strategy_iteration/strategy_008/
REPO = PROJ.parents[1]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
OUT = HERE / "_gatecheck"
sys.path.insert(0, str(SHARED))

from build_weekly_targets import (          # noqa: E402
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily   # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "eng", REPO / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py")
eng = importlib.util.module_from_spec(_spec)
sys.modules["eng"] = eng                      # dataclass 需要模块已注册
_spec.loader.exec_module(eng)

N_SEED = 20
SEED = 20261016


def build_sig_full():
    """一遍循环 → (周频 (date,instrument,weight) 全开表, 每周元数据)。"""
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
    crowd = {(pd.Timestamp(w), i): float(s) for w, i, s in
             zip(cd["week"], cd["ind"], cd["signal_count"])}
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    prev = plan["top3"].shift(1)
    plan["n_common"] = [len(set(str(a).split(",")) & set(str(b).split(",")))
                        if isinstance(b, str) else 3 for a, b in zip(plan["top3"], prev)]

    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    pby = {d: g for d, g in panel.groupby("date")}
    prev_top3, held, frames, meta = None, {}, [], {}
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), pby.get(t)
        if day is None or cand is None:
            continue
        top3, regime = pick_industries(day, float(regi.at[t, "T_prime"]))
        dirs = factor_directions("baseline", regime)
        tg = build_targets(cand, top3, dirs, held)
        scs = [crowd.get((t, p), np.nan) for p in top3]
        scs = [x for x in scs if pd.notna(x)]
        meta[t] = {"regime": regime, "sc_mean": float(np.mean(scs)) if scs else np.nan,
                   "sc_max": float(np.nanmax([crowd.get((t, p), np.nan) for p in top3])),
                   "stable": (prev_top3 is None or set(top3) == set(prev_top3)),
                   "n_common": int(plan.loc[plan["signal_date"] == t, "n_common"].iloc[0])
                   if (plan["signal_date"] == t).any() else 3}
        rows, hn = [], {}
        for ind_name, syms in tg.items():
            if not syms:
                continue
            w = industry_weights(cand, syms)
            for s in syms:
                hn[s] = ind_name
                rows.append({"date": t, "instrument": s, "weight": float(w[s] / N_IND)})
        if rows:
            frames.append(pd.DataFrame(rows))
        held, prev_top3 = hn, top3
    sig = pd.concat(frames, ignore_index=True)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet",
                        columns=["date"])["date"]).unique()))
    return sig, meta, cal


def main():
    sig, meta, cal = build_sig_full()
    mk = pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])
    cfg = eng.WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = eng.TradingDaysRebalance(1)

    # ★ 关键：exposure 必须**在周频施加后再展开** —— expand_to_daily 在周界日会把
    #   「只存在于旧周」的股票按旧权重留下（实测 2017-05-26 权重和 0.8228，而 weekly_plan
    #   说该周 exposure=0）。展开后再缩放会把这一天的残留一并清零 ⇒ 与冻结基线不一致。
    sig_dates = list(sig["date"].unique())            # 周表实际出现的信号日（保序）
    assert sig_dates == sorted(sig_dates)
    sig = sig.copy()
    sig["_wk"] = sig["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})   # 1-based 周编号
    w_tag = expand_to_daily(sig[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}),
                            cal)
    w_wgt = expand_to_daily(sig[["date", "instrument", "weight"]], cal)
    assert (w_tag[["date", "instrument"]].values == w_wgt[["date", "instrument"]].values).all()
    w_tag["date"] = pd.to_datetime(w_tag["date"])
    w_wgt["date"] = pd.to_datetime(w_wgt["date"])
    ep = w_tag["weight"].values.astype(int) - 1        # 每行的**贡献周**下标（周界残留=旧周）
    w0 = w_wgt["weight"].values
    daily_base = w_wgt.rename(columns={"instrument": "symbol"})
    print(f"  展开 {len(w0):,} 行；周界残留行(贡献周≠最近周) {int((ep < 0).sum()) if False else ''}")

    def run(flags_arr: np.ndarray) -> dict:
        d = daily_base.copy()
        d["weight"] = w0 * flags_arr[ep]
        _, trades, _ = eng.run_weight_backtest(mk, d, cfg, period)
        _, mtr = eng.nav_from_trades(mk, trades, cfg.initial_cash)
        return {"nav": mtr["final_nav"], "sharpe": mtr["sharpe"], "dd": mtr["max_drawdown"]}

    def to_arr(flags: dict) -> np.ndarray:
        return np.array([flags.get(t, 1) for t in sig_dates], dtype=float)

    # ── 规则定义 ──
    def f_base():
        return {t: (0 if not meta[t]["stable"] else 1) for t in meta}

    def f_007():
        f = f_base()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "momentum" and pd.notna(m["sc_mean"]) and m["sc_mean"] < 2.0:
                f[t] = 0
        return f

    def f_B3():
        f = f_007()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "reversal" and pd.notna(m["sc_max"]) and m["sc_max"] >= 3:
                f[t] = 0
        return f

    def f_A2():
        f = f_007()
        for t, m in meta.items():
            if m["regime"] == "reversal" and m["n_common"] >= 2:
                f[t] = 1
        return f

    checks = {"V0 基线": f_base(), "V1 007": f_007(), "B3 007+镜像": f_B3(), "A2 007+反转≥2": f_A2()}
    print("== 自检 + 主结果（引擎，trades 口径）==")
    res = {}
    for k, f in checks.items():
        r = run(to_arr(f))
        res[k] = r
        print(f"  {k:<14} nav {r['nav']:.4f}  sharpe {(r['sharpe'] or 0):.4f}  dd {r['dd']:.4f}")
    print("  参照（冻结件）：基线 3.6001/0.9034/−24.31%   007 4.5663/1.1449/−22.52%")

    # ── 随机对照 ──
    rng = np.random.default_rng(SEED)
    f7 = f_007()
    arr7 = to_arr(f7)

    def ctrl(pool, k, open_weeks: bool, real_nav):
        _idx = {t: i for i, t in enumerate(sig_dates)}
        ids = np.array([_idx[t] for t in pool])
        vals = []
        for _ in range(N_SEED):
            pick = rng.choice(ids, size=k, replace=False)
            a = arr7.copy()
            a[pick] = 1.0 if open_weeks else 0.0
            vals.append(run(a)["nav"])
        vals = np.array(vals)
        pct = (vals < real_nav).mean() * 100
        print(f"  真实 {real_nav:.4f}  随机中位 {np.median(vals):.4f}  "
              f"P95 {np.percentile(vals,95):.4f}  分位 {pct:.0f}%")
        return vals

    IN_SIG = set(sig_dates)
    poolB = [t for t in meta if t in IN_SIG and f7[t] == 1 and meta[t]["regime"] == "reversal"]
    realB = [t for t in poolB if meta[t]["sc_max"] >= 3]
    print(f"\n== B3 随机对照：候选池 {len(poolB)} 周，真实关 {len(realB)} 周 × {N_SEED} 种子 ==")
    valsB = ctrl(poolB, len(realB), False, res["B3 007+镜像"]["nav"])

    poolA = [t for t in meta if t in IN_SIG and meta[t]["regime"] == "reversal" and f7[t] == 0]
    realA = [t for t in poolA if meta[t]["n_common"] >= 2]
    print(f"\n== A2 随机对照：候选池 {len(poolA)} 周，真实开 {len(realA)} 周 × {N_SEED} 种子 ==")
    valsA = ctrl(poolA, len(realA), True, res["A2 007+反转≥2"]["nav"])

    pd.DataFrame({"B3_random": valsB}).to_csv(OUT / "ctrl_B3.csv", index=False)
    pd.DataFrame({"A2_random": valsA}).to_csv(OUT / "ctrl_A2.csv", index=False)
    print(f"\n产物 → {OUT}")


if __name__ == "__main__":
    main()
