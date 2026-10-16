"""strategy_008 · 对照组——验收镜像闸门的三道关卡（进程内引擎）。

对照 1（随机周空仓）：从「反转周 & 满仓（007 之后未被关）」的同一合格池里，随机关掉与真实
  闸门**同数量**的周（30 种子）→ 主回测须超过随机分布 **P95**（本工程既定门槛，007/004 同款）。
  ★ 同时比较 **nav 与 Sharpe 两个维度** —— 随机关同样多的周本身会降低波动，
    只看 nav 无法排除「少在场」的平凡解释。
对照 2（安慰剂 · 反向）：关掉 sc_max **最低**的同数量反转周（方向反过来）→ 应显著变差，
  否则说明闸门没有方向信息。
对照 3（留一 · 2026-10-16 新增纪律）：对每个被关周逐个「留一」（即保留该周），
  看 Sharpe 是否仍高于 007。防止「全部增益来自单周异常」——
  实测教训：镜像闸门 nav 级留一曾假阳性（2024-09-30 单周驱动），故**必须逐周做**。

★ 口径要点：exposure 必须在**周频**施加后再 expand —— `expand_to_daily` 在周界日会把
 「只存在于上一周」的股票按旧权重留下（实测 2017-05-26 权重和 0.8228 而 weekly_plan 说该周空仓）。
 先展开再缩放会对不上冻结件（自检 1.34 vs 3.6001 暴露过）。

用法：python controls.py
产物：controls_summary.csv
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
ENGINE_DIR = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(ENGINE_DIR))

from build_weekly_targets import (                     # noqa: E402
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily       # noqa: E402
from local_weight_backtest import (                    # noqa: E402
    TradingDaysRebalance, WeightBacktestConfig, nav_from_trades, run_weight_backtest,
)

PANEL = CACHE / "signal_panel_weekly_indpre.parquet"
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"
CROWD = CACHE / "industry_crowding_weekly.parquet"
SC_THR, SC_MAX_THR = 2.0, 3.0
N_SEEDS, SEED0 = 30, 20261016


def build_all_on(panel, ind, reg, crowd):
    """一遍建**全开**周频持仓表（exposure≡1）+ 每周元数据（股票选择与 exposure 无关）。"""
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
        meta[t] = {"regime": regime,
                   "sc_mean": float(np.mean(scs)) if scs else np.nan,
                   "sc_max": float(np.max(scs)) if scs else np.nan,
                   "stable": (prev_top3 is None or set(top3) == set(prev_top3))}
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
    return pd.concat(frames, ignore_index=True), meta


def main() -> int:
    t0 = time.time()
    panel = pd.read_parquet(PANEL)
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cd = pd.read_parquet(CROWD)
    crowd = {(pd.Timestamp(w), i): float(s) for w, i, s in
             zip(cd["week"], cd["ind"], cd["signal_count"])}
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))
    mk = pd.read_parquet(MARKET)
    mk["date"] = pd.to_datetime(mk["date"])

    sig, meta = build_all_on(panel, ind, reg, crowd)
    sig_dates = list(sig["date"].unique())
    s = sig.copy()
    s["_wk"] = s["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})
    tag = expand_to_daily(s[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}), cal)
    wgt = expand_to_daily(s[["date", "instrument", "weight"]], cal)
    # 行序一致性自检
    assert (tag[["date", "instrument"]].values == wgt[["date", "instrument"]].values).all()
    tag["date"] = pd.to_datetime(tag["date"])
    wgt["date"] = pd.to_datetime(wgt["date"])
    ep = tag["weight"].values.astype(int) - 1          # 每行贡献周（周界残留 = 上一周）
    w0 = wgt["weight"].values
    daily = wgt.rename(columns={"instrument": "symbol"})

    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = TradingDaysRebalance(1)
    idx = {t: i for i, t in enumerate(sig_dates)}

    def run(flags: dict) -> dict:
        a = np.array([flags.get(t, 1) for t in sig_dates], dtype=float)
        d = daily.copy()
        d["weight"] = w0 * a[ep]
        _, tr, _ = run_weight_backtest(mk, d, cfg, period)
        _, m = nav_from_trades(mk, tr, cfg.initial_cash)
        return {"nav": m["final_nav"], "sharpe": m["sharpe"], "dd": m["max_drawdown"]}

    # ── 规则 ──
    def f_base():
        return {t: (1 if meta[t]["stable"] else 0) for t in meta}

    def f_007():
        f = f_base()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "momentum" and pd.notna(m["sc_mean"]) and m["sc_mean"] < SC_THR:
                f[t] = 0
        return f

    def f_008():
        f = f_007()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "reversal" and pd.notna(m["sc_max"]) and m["sc_max"] >= SC_MAX_THR:
                f[t] = 0
        return f

    print("== 自检（应回：基线 3.6001 / 007 4.5663）==")
    r0, r7, r8 = run(f_base()), run(f_007()), run(f_008())
    print(f"  基线          nav {r0['nav']:.4f}  sharpe {r0['sharpe']:.4f}  dd {r0['dd']:.4f}")
    print(f"  007           nav {r7['nav']:.4f}  sharpe {r7['sharpe']:.4f}  dd {r7['dd']:.4f}")
    print(f"  008 镜像闸门   nav {r8['nav']:.4f}  sharpe {r8['sharpe']:.4f}  dd {r8['dd']:.4f}\n")

    f7 = f_007()
    pool = [t for t in sig_dates if meta[t]["regime"] == "reversal" and f7[t] == 1]
    closed = [t for t in pool if meta[t]["sc_max"] >= SC_MAX_THR]
    print(f"反转周合格池 {len(pool)} 周；008 关掉 {len(closed)} 周\n")

    rows = []
    # ── 对照 1：随机周空仓 ──
    rng = np.random.default_rng(SEED0)
    ids = np.array([idx[t] for t in pool])
    navs, shs = [], []
    for _ in range(N_SEEDS):
        a = np.array([f7.get(t, 1) for t in sig_dates], dtype=float)
        a[rng.choice(ids, size=len(closed), replace=False)] = 0
        m = run({t: float(v) for t, v in zip(sig_dates, a)})
        navs.append(m["nav"]); shs.append(m["sharpe"])
    navs, shs = np.array(navs), np.array(shs)
    print(f"== 对照 1 · 随机周空仓（{N_SEEDS} 种子，随机关 {len(closed)} 个反转周）==")
    print(f"  nav   : 中位 {np.median(navs):.4f}  P95 {np.percentile(navs,95):.4f}  "
          f"最大 {navs.max():.4f}  | 真实 {r8['nav']:.4f} → 分位 {(navs<r8['nav']).mean()*100:.0f}%")
    print(f"  sharpe: 中位 {np.median(shs):.4f}  P95 {np.percentile(shs,95):.4f}  "
          f"最大 {shs.max():.4f}  | 真实 {r8['sharpe']:.4f} → 分位 {(shs<r8['sharpe']).mean()*100:.0f}%")
    rows.append({"control": f"随机周空仓({N_SEEDS}种子)", "n_weeks": len(closed),
                 "nav_median": np.median(navs), "nav_p95": np.percentile(navs, 95),
                 "sharpe_median": np.median(shs), "sharpe_p95": np.percentile(shs, 95),
                 "real_nav": r8["nav"], "real_sharpe": r8["sharpe"]})

    # ── 对照 2：安慰剂（反向：关 sc_max 最低的同样多周）──
    pool_sorted = sorted(pool, key=lambda t: (meta[t]["sc_max"], t))
    placebo_weeks = pool_sorted[:len(closed)]
    f_pl = dict(f7)
    for t in placebo_weeks:
        f_pl[t] = 0
    rp = run(f_pl)
    print(f"\n== 对照 2 · 安慰剂（关 sc_max 最低的 {len(placebo_weeks)} 周）==")
    print(f"  nav {rp['nav']:.4f}  sharpe {rp['sharpe']:.4f}  dd {rp['dd']:.4f}   "
          f"→ 相对 007 nav {rp['nav']-r7['nav']:+.4f} / sharpe {rp['sharpe']-r7['sharpe']:+.4f}")
    rows.append({"control": "安慰剂·关最低sc_max", "n_weeks": len(placebo_weeks),
                 "nav_median": np.nan, "nav_p95": np.nan, "sharpe_median": np.nan,
                 "sharpe_p95": np.nan, "real_nav": rp["nav"], "real_sharpe": rp["sharpe"]})

    # ── 对照 3：留一 ──
    res = []
    for keep in closed:
        f = dict(f_008()); f[keep] = 1
        m = run(f)
        res.append((keep, m["nav"], m["sharpe"], m["dd"]))
    d = pd.DataFrame(res, columns=["keep_week", "nav", "sharpe", "dd"]).sort_values("nav")
    n_beats_sharpe = int((d["sharpe"] > r7["sharpe"]).sum())
    print(f"\n== 对照 3 · 留一（逐个保留被关周，共 {len(closed)} 次）==")
    print(f"  sharpe: min {d['sharpe'].min():.4f}  中位 {d['sharpe'].median():.4f}  "
          f"max {d['sharpe'].max():.4f}  | 007 = {r7['sharpe']:.4f} → "
          f"{n_beats_sharpe}/{len(closed)} 次仍高于 007")
    print(f"  nav   : min {d['nav'].min():.4f}  中位 {d['nav'].median():.4f}  max {d['nav'].max():.4f}")
    print("  贡献最大 5 周（保留后 nav 最低）：")
    for _, x in d.head(5).iterrows():
        print(f"    {pd.Timestamp(x['keep_week']).date()}  nav {x['nav']:.4f} "
              f"(贡献 {r8['nav']-x['nav']:+.4f})  sharpe {x['sharpe']:.4f}  dd {x['dd']:.4f}")
    rows.append({"control": f"留一({len(closed)}次)", "n_weeks": len(closed),
                 "nav_median": d["nav"].median(), "nav_p95": np.nan,
                 "sharpe_median": d["sharpe"].median(), "sharpe_p95": np.nan,
                 "real_nav": r8["nav"], "real_sharpe": r8["sharpe"]})
    d.to_csv(HERE / "control_leave_one_out.csv", index=False)

    pd.DataFrame(rows).to_csv(HERE / "controls_summary.csv", index=False)
    print(f"\n产物 → {HERE/'controls_summary.csv'} / control_leave_one_out.csv  "
          f"（用时 {time.time()-t0:.0f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
