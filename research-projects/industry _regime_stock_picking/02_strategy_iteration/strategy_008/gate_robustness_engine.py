"""007 量能闸门的**引擎级**稳健性检验（2026-10-16）。

背景：nav 级近似显示 (a) 007 的增益 +7.6% 远小于引擎的 +26.8%；
(b) 留一发现最大贡献周 = 2018-09-28（国庆跳空）；(c) 只关 6 个长假跳空周 = +11.7% > 全闸门 +7.6%。
nav 近似不足以评判 007 ⇒ 用**同一引擎**跑变体。
★ 只写 temp/，不碰任何冻结件；策略逻辑逐字复用 007 的 build/pick。

变体：
  V0 无闸门（应回到基线 3.600）
  V1 007 原版（动量周 & sc<2）—— 应逐值回到 4.566
  V2 007 但**排除长假跳空周**（闸门只在非长假周生效）
  V3 只关**长假跳空周**（不看 sc）
  V4 只关动量周的**长假跳空周**（不看 sc）
  V5/V6/V7 阈值 sc<1.5 / 2.5 / 3.0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]        # 归档后位于 <PROJ>/02_strategy_iteration/strategy_008/
REPO = PROJ.parents[1]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
OUT = HERE / "_gatecheck"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(SHARED))

from build_weekly_targets import (          # noqa: E402
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily   # noqa: E402

ENGINE = REPO / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"
MODE = "baseline"
HOLIDAY_GAP = 3          # exec_date − signal_date > 3 天 ⇒ 长假跳空
# ★ 引擎级留一：这些信号日**强制不关**（即使闸门命中），用于检验单周依赖
KEEP: set = set()


def gate(name: str, regime: str, sc: float, hol: bool) -> bool:
    """返回 True = 该周空仓。"""
    if name == "V0_none":
        return False
    if name == "V1_007":            return regime == "momentum" and sc < 2.0
    if name == "V2_exholiday":      return regime == "momentum" and sc < 2.0 and not hol
    if name == "V3_hol_all":        return hol
    if name == "V4_hol_mom":        return regime == "momentum" and hol
    if name == "V5_sc15":           return regime == "momentum" and sc < 1.5
    if name == "V6_sc25":           return regime == "momentum" and sc < 2.5
    if name == "V7_sc30":           return regime == "momentum" and sc < 3.0
    raise ValueError(name)


def build_targets_for(variant: str, panel, ind, reg, cal, crowd, holiday,
                      extra: str | None = None, scmax: dict | None = None) -> pd.DataFrame:
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}
    prev_top3, held, frames = None, {}, []
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), panel_by_day.get(t)
        if day is None or cand is None:
            continue
        t_prime = float(regi.at[t, "T_prime"])
        top3, regime = pick_industries(day, t_prime)
        dirs = factor_directions(MODE, regime)
        tg = build_targets(cand, top3, dirs, held)
        exposure = 1.0 if (prev_top3 is None or set(top3) == set(prev_top3)) else 0.0
        if exposure == 1.0:
            scs = [crowd.get((t, p), np.nan) for p in top3]
            scs = [x for x in scs if pd.notna(x)]
            sc = float(np.mean(scs)) if scs else np.nan
            if (not pd.isna(sc) and gate(variant, regime, sc, bool(holiday.get(t, False)))
                    and pd.Timestamp(t) not in KEEP):
                exposure = 0.0
        # ★ 附加规则（方向 A / B 的引擎验证）
        if extra:
            nc = len(set(top3) & set(prev_top3)) if prev_top3 else 3
            smx = (scmax or {}).get(t, float("nan"))
            if extra.startswith("mirror_mean") and regime == "reversal":
                thr = float(extra.split("_")[-1])
                scm = np.mean([crowd.get((t, p), np.nan) for p in top3])
                if exposure == 1.0 and not pd.isna(scm) and scm >= thr:
                    exposure = 0.0
            elif extra.startswith("mirror_max") and regime == "reversal":
                thr = float(extra.split("_")[-1])
                if exposure == 1.0 and not pd.isna(smx) and smx >= thr:
                    exposure = 0.0
            elif extra == "rev_always" and regime == "reversal":
                exposure = 1.0
            elif extra.startswith("rev_ge") and regime == "reversal":
                k = int(extra.split("_")[-1])
                exposure = 1.0 if nc >= k else 0.0
        rows, held_next = [], {}
        for ind_name, syms in tg.items():
            if not syms:
                continue
            w = industry_weights(cand, syms)
            for s in syms:
                held_next[s] = ind_name
                rows.append({"instrument": s, "weight": float(exposure * w[s] / N_IND)})
        if rows:
            df = pd.DataFrame(rows, columns=["instrument", "weight"])
            df.insert(0, "date", t)
            frames.append(df)
        held, prev_top3 = held_next, top3
    sig = pd.concat(frames, ignore_index=True)
    return expand_to_daily(sig, cal)


def main():
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    crowd_df = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
    crowd = {(pd.Timestamp(w), i): float(s) for w, i, s in
             zip(crowd_df["week"], crowd_df["ind"], crowd_df["signal_count"])}
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(MARKET, columns=["date"])["date"]).unique()))

    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    plan["exec_date"] = pd.to_datetime(plan["exec_date"])
    holiday = dict(zip(plan["signal_date"],
                       (plan["exec_date"] - plan["signal_date"]).dt.days > HOLIDAY_GAP))
    print(f"长假跳空周（gap>{HOLIDAY_GAP}）：{sum(holiday.values())}/{len(holiday)}")

    variants = ["V0_none", "V1_007", "V2_exholiday", "V3_hol_all", "V4_hol_mom",
                "V5_sc15", "V6_sc25", "V7_sc30"]
    # ★ 留一（引擎级）：V8 = 保留最大贡献周；V9 = 保留最大两贡献周
    runs = [(v, set()) for v in variants]
    runs += [("V1_007", {pd.Timestamp("2018-09-28")}),
             ("V1_007", {pd.Timestamp("2018-09-28"), pd.Timestamp("2022-09-23")})]
    rows = []
    for variant, keep in runs:
        globals()["KEEP"] = keep
        v = f"{variant}_keep{len(keep)}" if keep else variant
        tp = OUT / f"targets_{v}.parquet"
        tg = build_targets_for(variant, panel, ind, reg, cal, crowd, holiday)
        tg.to_parquet(tp, index=False)
        od = OUT / v
        od.mkdir(exist_ok=True)
        cmd = [sys.executable, str(ENGINE), str(PROJ),
               "--market-data", str(MARKET), "--targets", str(tp),
               "--rebalance-period", "trading_days", "--period-days", "1",
               "--initial-cash", "500000", "--buy-cost-bps", "3",
               "--sell-cost-bps", "13", "--min-cost", "5", "--output-dir", str(od)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        mf = od / "backtest_logs" / "metrics_from_trades.csv"
        if not mf.exists():
            print(f"[{v}] 引擎失败：{(r.stdout or '')[-400:]} {(r.stderr or '')[-400:]}")
            continue
        m = pd.read_csv(mf).iloc[0]
        rows.append({"variant": v, "nav": m["final_nav"], "ann": m["annual_return"],
                     "sharpe": m["sharpe"], "dd": m["max_drawdown"]})
        print(f"[{v}] nav {m['final_nav']:.4f}  ann {m['annual_return']:.4f}  "
              f"sharpe {m['sharpe']:.4f}  dd {m['max_drawdown']:.4f}")
    g = pd.DataFrame(rows)
    g.to_csv(OUT / "summary.csv", index=False)
    print("\n" + g.round(4).to_string(index=False))
    print(f"\n产物 → {OUT}")


if __name__ == "__main__":
    main()
