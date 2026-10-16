"""strategy_009 —— 3×2 主矩阵 + 三道对照（引擎口径，trades 指标）。

主矩阵：暴露规则（基线 / 007 / 008）× 行业选择（原 top3 / 簇约束 top3）
  · 原 top3 列复用 `strategy_008/ab_engine_controls.py` 的全开表（自检须回 3.6001 / 4.5663 / 4.5535）
  · 簇约束列用 `build_targets_cluster.py` 产出的全开表（自检须回 4.5535 的对手行之外无参照）
  · ★ 暴露规则一律用**该列所选 top3 自己的 sc**（007/008 的闸门语义即"你所持行业的拥挤度"）
    ⇒ 这正是"本改动与闸门非严格正交"的体现，诊断里必须报 exposure 差异周数

对照（默认作用于 **008 行** = 主口径）：
  random    随机替换臂：同样 47 周，但换入**随机**行业（不是簇外最优）× N 种子
  loo       逐周复原：47 个被改周逐个还原为原 top3
  placebo   安慰剂反向：同样 47 周，**故意**换成同簇行业（= 加强同质暴露）
  grid      K∈{5,6,7} × 窗口∈{126,252,504}（事前定的防单点网格）

用法：
  python matrix_and_controls.py matrix
  python matrix_and_controls.py random --seeds 20 [--jobs 1]
  python matrix_and_controls.py loo | placebo | grid
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
CACHE = PROJ / "shared" / "_cache"
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(PROJ / "02_strategy_iteration" / "strategy_008"))
sys.path.insert(0, str(HERE))

import build_weekly_targets as B            # noqa: E402
import ab_engine_controls as A              # noqa: E402
import build_targets_cluster as BTC         # noqa: E402
from expand_targets_daily import expand_to_daily   # noqa: E402

K_DEF = 7
ENGINE = A.eng

# 冻结件参照
REF = {"基线": (3.6001, 0.9034, -0.2431), "007": (4.5663, 1.1449, -0.2252),
       "008": (4.5535, 1.2754, -0.1836)}


def _engine_ctx():
    mk = pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])
    cfg = ENGINE.WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0,
                                      sell_bps=13.0, min_cost=5.0)
    cal = pd.DatetimeIndex(sorted(mk["date"].unique()))
    return mk, cfg, ENGINE.TradingDaysRebalance(1), cal


def prepare(sig, cal):
    """全开表 → (w0, ep, daily 模板)：exposure 必须在**周频施加后再 expand**（陷阱 8）。

    用 tag-expand 定位每行贡献周：tag 表 = 每周编号，按同一展开规则映射到日频，
    于是每行 weight 的 exposure 因子 = 该行所属**贡献周**的 flag（周界残留行归旧周）。
    """
    sig_dates = list(sig["date"].unique())
    s = sig.copy()
    s["_wk"] = s["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})
    w_tag = expand_to_daily(s[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}), cal)
    w_wgt = expand_to_daily(s[["date", "instrument", "weight"]], cal)
    assert (w_tag[["date", "instrument"]].values == w_wgt[["date", "instrument"]].values).all()
    ep = w_tag["weight"].values.astype(int) - 1
    w0 = w_wgt["weight"].values
    daily = w_wgt.rename(columns={"instrument": "symbol"})
    return sig_dates, w0, ep, daily


def run_flags(sig_dates, w0, ep, daily, flags, mk, cfg, period):
    d = daily.copy()
    d["weight"] = w0 * np.array([flags.get(t, 1) for t in sig_dates], dtype=float)[ep]
    _, tr, _ = ENGINE.run_weight_backtest(mk, d, cfg, period)
    _, m = ENGINE.nav_from_trades(mk, tr, cfg.initial_cash)
    r = m.iloc[0].to_dict() if hasattr(m, "iloc") else dict(m)
    r["n_trades"] = len(tr)
    r["weeks_in_market"] = int(sum(1 for t in sig_dates if flags.get(t, 1) == 1))
    return r


def flags_for(meta: pd.DataFrame, rule: str) -> dict:
    """rule ∈ {base, r007, r008}；meta 必须是**该列自己**的 meta（sc 取所选 top3）。"""
    f = {t: (1 if m["stable"] else 0) for t, m in meta.iterrows()}
    if rule in ("r007", "r008"):
        for t, m in meta.iterrows():
            if f[t] == 1 and m["regime"] == "momentum" and pd.notna(m["sc_mean"]) and m["sc_mean"] < 2.0:
                f[t] = 0
    if rule == "r008":
        for t, m in meta.iterrows():
            if f[t] == 1 and m["regime"] == "reversal" and pd.notna(m["sc_max"]) and m["sc_max"] >= 3:
                f[t] = 0
    return f


def load_meta_perweek():
    """列1 meta 来自 ab_engine_controls 的规则化重算；列2 meta 来自 build_targets_cluster 落盘。"""
    _, mo, _ = A.build_sig_full()
    mt_orig = pd.DataFrame([{"date": t, **v} for t, v in mo.items()]).set_index("date")
    mt_clu = pd.read_parquet(CACHE / f"meta_cluster009_K{K_DEF}.parquet").set_index("date")
    return mt_orig, mt_clu


def mode_matrix(K=K_DEF, tag=""):
    mk, cfg, period, cal = _engine_ctx()
    sig_o, mo, cal_o = A.build_sig_full()
    mt_orig = pd.DataFrame([{"date": t, **v} for t, v in mo.items()]).set_index("date")
    sig_c = pd.read_parquet(CACHE / f"sig_weekly_cluster009_K{K}.parquet")
    mt_clu = pd.read_parquet(CACHE / f"meta_cluster009_K{K}.parquet").set_index("date")

    cols = {}
    for nm, sig, meta in (("原top3", sig_o, mt_orig), ("簇约束", sig_c, mt_clu)):
        cols[nm] = (meta,) + prepare(sig, cal)

    rows = []
    for rule, rn in (("base", "基线"), ("r007", "007"), ("r008", "008")):
        for nm in ("原top3", "簇约束"):
            meta, sig_dates, w0, ep, daily = cols[nm]
            fl = flags_for(meta, rule)
            r = run_flags(sig_dates, w0, ep, daily, fl, mk, cfg, period)
            ref = REF[rn]
            ok = (abs(r["final_nav"] - ref[0]) < 2e-3 and abs(r["sharpe"] - ref[1]) < 2e-3
                  and abs(r["max_drawdown"] - ref[2]) < 2e-3) if nm == "原top3" else None
            rows.append({"暴露规则": rn, "行业选择": nm, "nav": r["final_nav"],
                         "annual": r["annual_return"], "vol": r["annual_volatility"],
                         "sharpe": r["sharpe"], "dd": r["max_drawdown"],
                         "trades": r["n_trades"], "在场周": r["weeks_in_market"],
                         "自检": ("" if ok is None else ("✓" if ok else "✗"))})
    T = pd.DataFrame(rows)
    T.to_csv(HERE / f"matrix{tag}.csv", index=False)
    print("== 3×2 主矩阵（引擎口径 · trades）==")
    print(T.to_string(index=False))

    # ── 诊断：exposure 差异 ──
    print("\n== 诊断：簇约束列 vs 原 top3 列的 exposure 差异 ==")
    for rule, rn in (("base", "基线"), ("r007", "007"), ("r008", "008")):
        fo = flags_for(mt_orig, rule)
        fc = flags_for(mt_clu, rule)
        common = [t for t in fo if t in fc]
        diff = [t for t in common if fo[t] != fc[t]]
        n_rev = sum(1 for t in diff if mt_clu.loc[t, "regime"] == "reversal")
        print(f"  {rn:<5} 原在场 {sum(fo[t] for t in common):>3} 周 → 簇约束在场 "
              f"{sum(fc[t] for t in common):>3} 周｜exposure 不同的周 = {len(diff)}"
              f"（其中反转周 {n_rev}）")
    return T


def mode_live(K=K_DEF):
    """★ 隔离版：只在"原规则本周本来会满仓"的周替换（切断暴露通道），看 3 行各自变化。"""
    labels = pd.read_parquet(CACHE / f"industry_cluster_weekly_K{K}_complete_w252.parquet")
    labels.index = pd.to_datetime(labels.index)
    mk, cfg, period, cal = _engine_ctx()
    B.pick_industries = BTC.make_pick_live(labels)
    BTC._LOG["mod"] = []
    sig, mt = BTC.build_sig_cluster()
    meta = mt.set_index("date")
    _, sig_dates, w0, ep, daily = (meta,) + prepare(sig, cal)
    print(f"隔离版：触发替换 {len(BTC._LOG['mod'])} 周（= 原 47 周里「本会满仓」的那部分）")
    rows = []
    for rule, rn in (("base", "基线"), ("r007", "007"), ("r008", "008")):
        r = run_flags(sig_dates, w0, ep, daily, flags_for(meta, rule), mk, cfg, period)
        rows.append({"暴露规则": rn, "行业选择": "簇约束(隔离版)", "nav": r["final_nav"],
                     "annual": r["annual_return"], "vol": r["annual_volatility"],
                     "sharpe": r["sharpe"], "dd": r["max_drawdown"], "trades": r["n_trades"],
                     "在场周": r["weeks_in_market"], "自检": ""})
    T = pd.DataFrame(rows)
    T.to_csv(HERE / "matrix_live.csv", index=False)
    print("\n== 隔离版（对照 008 = 4.5535 / 1.2754 / −0.1836）==")
    print(T.to_string(index=False))
    return T


def mode_random(K=K_DEF, seeds=20, seed0=20261016):
    """随机替换臂：同样 47 周，但换入行业从候选池**随机**抽（不是簇外最优）。"""
    labels = pd.read_parquet(CACHE / f"industry_cluster_weekly_K{K}_complete_w252.parquet")
    labels.index = pd.to_datetime(labels.index)
    mt_clu = pd.read_parquet(CACHE / f"meta_cluster009_K{K}.parquet").set_index("date")
    mk, cfg, period, cal = _engine_ctx()
    rng = np.random.default_rng(seed0)

    # 被改的 47 周（来自 meta 与 baseline 原 top3 的差异）
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    p2 = dict(zip(plan["signal_date"], plan["top3"]))
    mod_weeks = [t for t in mt_clu.index if p2.get(t) != mt_clu.loc[t, "top3"]]
    print(f"随机替换臂：{len(mod_weeks)} 个被改周 × {seeds} 种子（换入=随机行业/簇外）")

    rows = []
    for k in range(seeds):
        rnd = {}
        for t in mod_weeks:
            top3 = str(p2[t]).split(",")
            lab = labels.loc[t]
            pool = [x for x in lab.index if x not in top3]
            rnd[t] = str(rng.choice(pool))
        B.pick_industries = BTC.make_pick(labels)
        orig_pick = B.pick_industries

        def pick_rand(ind_day, t_prime, _rnd=rnd, _orig=orig_pick):
            top3, regime = _orig(ind_day, t_prime)
            t = pd.Timestamp(ind_day["date"].iloc[0])
            if t in _rnd:
                return [top3[0], top3[1], _rnd[t]], regime
            return top3, regime

        B.pick_industries = pick_rand
        BTC._LOG["mod"] = []
        sig, mt = BTC.build_sig_cluster()
        meta = mt.set_index("date")
        _, sig_dates, w0, ep, daily = (meta,) + prepare(sig, cal)
        r = run_flags(sig_dates, w0, ep, daily, flags_for(meta, "r008"), mk, cfg, period)
        rows.append({"seed": k, "nav": r["final_nav"], "sharpe": r["sharpe"], "dd": r["max_drawdown"]})
        if (k + 1) % 5 == 0:
            print(f"  … {k+1}/{seeds}", flush=True)
    R = pd.DataFrame(rows)
    R.to_csv(HERE / "ctrl_random.csv", index=False)
    real = pd.read_csv(HERE / "matrix.csv")
    rn = float(real[(real["暴露规则"] == "008") & (real["行业选择"] == "簇约束")]["nav"].iloc[0])
    rs = float(real[(real["暴露规则"] == "008") & (real["行业选择"] == "簇约束")]["sharpe"].iloc[0])
    for col, v in (("nav", rn), ("sharpe", rs), ("dd", None)):
        x = R[col].values
        pct = (x < v).mean() * 100 if v is not None else np.nan
        print(f"  {col:<7} 真实 {v if v is not None else float('nan'):>8.4f} | 随机 中位 {np.median(x):>8.4f} "
              f"P95 {np.percentile(x,95):>8.4f} | 分位 {pct:.0f}%")
    return R


def mode_loo(K=K_DEF):
    """逐周复原：47 个被改周逐个还原为原 top3。"""
    labels = pd.read_parquet(CACHE / f"industry_cluster_weekly_K{K}_complete_w252.parquet")
    labels.index = pd.to_datetime(labels.index)
    mt_clu = pd.read_parquet(CACHE / f"meta_cluster009_K{K}.parquet").set_index("date")
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    p2 = dict(zip(plan["signal_date"], plan["top3"]))
    mod_weeks = [t for t in mt_clu.index if p2.get(t) != mt_clu.loc[t, "top3"]]
    mk, cfg, period, cal = _engine_ctx()
    orig_pick = BTC.make_pick(labels)

    rows = []
    for j, t0 in enumerate(mod_weeks):
        def pick_loo(ind_day, t_prime, _t0=t0, _orig=orig_pick):
            top3, regime = _orig(ind_day, t_prime)
            t = pd.Timestamp(ind_day["date"].iloc[0])
            if t == _t0:                      # 该周复原：用原 top3（即不再替换）
                return [x for x in str(p2[t]).split(",")], regime
            return top3, regime
        B.pick_industries = pick_loo
        sig, mt = BTC.build_sig_cluster()
        meta = mt.set_index("date")
        _, sig_dates, w0, ep, daily = (meta,) + prepare(sig, cal)
        r = run_flags(sig_dates, w0, ep, daily, flags_for(meta, "r008"), mk, cfg, period)
        rows.append({"keep_out": str(pd.Timestamp(t0).date()), "nav": r["final_nav"],
                     "sharpe": r["sharpe"], "dd": r["max_drawdown"]})
        if (j + 1) % 10 == 0:
            print(f"  … {j+1}/{len(mod_weeks)}", flush=True)
    L = pd.DataFrame(rows).sort_values("sharpe")
    L.to_csv(HERE / "ctrl_loo.csv", index=False)
    print(f"Sharpe: min {L['sharpe'].min():.4f} 中位 {L['sharpe'].median():.4f} max {L['sharpe'].max():.4f}"
          f" | > 008(1.2754) 的 {int((L['sharpe'] > 1.2754).sum())}/{len(L)}")
    print(f"nav: min {L['nav'].min():.4f} 中位 {L['nav'].median():.4f} max {L['nav'].max():.4f}"
          f" | < 008(4.5535) 的 {int((L['nav'] < 4.5535).sum())}/{len(L)}（复原=回到 008 或更好）")
    return L


def mode_placebo(K=K_DEF):
    """安慰剂反向：同样 47 周，**故意**换成同簇行业（加强同质暴露）。"""
    labels = pd.read_parquet(CACHE / f"industry_cluster_weekly_K{K}_complete_w252.parquet")
    labels.index = pd.to_datetime(labels.index)
    mt_clu = pd.read_parquet(CACHE / f"meta_cluster009_K{K}.parquet").set_index("date")
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    p2 = dict(zip(plan["signal_date"], plan["top3"]))
    mod_weeks = [t for t in mt_clu.index if p2.get(t) != mt_clu.loc[t, "top3"]]
    mk, cfg, period, cal = _engine_ctx()
    orig_pick = BTC.make_pick(labels)
    swaps = {}
    for t in mod_weeks:
        top3 = [x for x in str(p2[t]).split(",")]
        lab = labels.loc[t]
        cl = lab.get(top3[0], -1)
        same = [x for x in lab.index if lab.get(x, -2) == cl and x not in top3]
        if not same:
            continue
        s = pd.read_parquet(CACHE / "industry_index.parquet")
        s["date"] = pd.to_datetime(s["date"])
        m = s[s["date"] == t].set_index("ind_name")["mom_60"].astype(float)
        m = m.reindex(same).dropna()
        if len(m):
            swaps[t] = m.idxmin()               # 同簇里"最弱"的那个（反转周的同类替换）

    def pick_placebo(ind_day, t_prime, _s=swaps, _orig=orig_pick):
        top3, regime = _orig(ind_day, t_prime)
        t = pd.Timestamp(ind_day["date"].iloc[0])
        if t in _s:
            return [top3[0], top3[1], _s[t]], regime
        return top3, regime

    B.pick_industries = pick_placebo
    sig, mt = BTC.build_sig_cluster()
    meta = mt.set_index("date")
    _, sig_dates, w0, ep, daily = (meta,) + prepare(sig, cal)
    r = run_flags(sig_dates, w0, ep, daily, flags_for(meta, "r008"), mk, cfg, period)
    print(f"安慰剂（同簇替换 {len(swaps)} 周）: nav {r['final_nav']:.4f} sharpe {r['sharpe']:.4f} "
          f"dd {r['max_drawdown']:.4f} trades {r['n_trades']}（对照 008：4.5535/1.2754/−0.1836）")
    pd.DataFrame([r]).to_csv(HERE / "ctrl_placebo.csv", index=False)
    return r


def mode_grid():
    """K∈{5,6,7} × 窗口∈{126,252,504}（事前定的防单点网格），一律看 008 行。"""
    mk, cfg, period, cal = _engine_ctx()
    rows = []
    for K in (5, 6, 7):
        for win in (126, 252, 504):
            lab_file = CACHE / f"industry_cluster_weekly_K{K}_complete_w{win}.parquet"
            if not lab_file.exists():
                subprocess.run([sys.executable, str(SHARED / "build_cluster_labels.py")],
                               env={**__import__("os").environ, "CLUSTER_K": str(K),
                                    "CLUSTER_WIN": str(win)}, check=True)
            labels = pd.read_parquet(lab_file)
            labels.index = pd.to_datetime(labels.index)
            B.pick_industries = BTC.make_pick(labels)
            BTC._LOG["mod"] = []
            sig, mt = BTC.build_sig_cluster()
            meta = mt.set_index("date")
            _, sig_dates, w0, ep, daily = (meta,) + prepare(sig, cal)
            r = run_flags(sig_dates, w0, ep, daily, flags_for(meta, "r008"), mk, cfg, period)
            rows.append({"K": K, "窗口": win, "触发周": len(BTC._LOG["mod"]), "nav": r["final_nav"],
                         "sharpe": r["sharpe"], "dd": r["max_drawdown"], "trades": r["n_trades"]})
            print(f"  K={K} win={win}: 触发 {len(BTC._LOG['mod'])} 周 nav {r['final_nav']:.4f} "
                  f"sharpe {r['sharpe']:.4f} dd {r['max_drawdown']:.4f}", flush=True)
    G = pd.DataFrame(rows)
    G.to_csv(HERE / "ctrl_grid.csv", index=False)
    print("\n== 网格（对照 008：4.5535 / 1.2754 / −0.1836）==")
    print(G.to_string(index=False))
    return G


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["matrix", "random", "loo", "placebo", "grid", "live"])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--K", type=int, default=K_DEF)
    a = ap.parse_args()
    t0 = time.time()
    if a.mode == "matrix":
        mode_matrix(a.K)
    elif a.mode == "live":
        mode_live(a.K)
    elif a.mode == "random":
        mode_random(a.K, a.seeds)
    elif a.mode == "loo":
        mode_loo(a.K)
    elif a.mode == "placebo":
        mode_placebo(a.K)
    else:
        mode_grid()
    print(f"[{a.mode}] 用时 {time.time()-t0:.0f}s")
