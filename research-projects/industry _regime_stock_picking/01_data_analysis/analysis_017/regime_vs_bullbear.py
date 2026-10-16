"""诊断（只读缓存）—— 2026-10-16

问题（用户）：**主线不稳定（反转周 T′ ≥ 0）一般对应牛市还是熊市？** 用创业板指 MA200 判定。
顺带回答两个衍生问题：
  ① 变盘指数 T 的**水平**（扰动强度）与牛熊的关系
  ② 007 的量能闸门（动量周 sc<2 → 空仓）是不是在**偷偷代理市场状态**（牛熊）
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]        # 归档后位于 <PROJ>/01_data_analysis/analysis_017/
REPO = PROJ.parents[1]
DB = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
CACHE = PROJ / "shared" / "_cache"

con = duckdb.connect(str(DB), read_only=True)
idx = con.execute("""SELECT instrument, date, close FROM index_bar1d
                     WHERE instrument IN ('399006.SZ','000300.SH','399001.SZ')
                     ORDER BY instrument, date""").fetchdf()
con.close()
idx["date"] = pd.to_datetime(idx["date"])

ma = {}
for inst, g in idx.groupby("instrument"):
    g = g.sort_values("date").set_index("date")["close"]
    ma[inst] = pd.DataFrame({"close": g, "ma200": g.rolling(200, min_periods=200).mean()})
    ma[inst]["bull"] = ma[inst]["close"] > ma[inst]["ma200"]

plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
plan["signal_date"] = pd.to_datetime(plan["signal_date"])
reg = pd.read_parquet(CACHE / "regime.parquet")
reg["date"] = pd.to_datetime(reg["date"])

nav = pd.read_csv(PROJ / "02_strategy_iteration/strategy_007/backtest_strategy_baseline"
                  "/backtest_logs/nav_from_trades.csv", parse_dates=["date"]).set_index("date")["nav"]
crowd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
sc = {(pd.Timestamp(a), b): float(c) for a, b, c in
      zip(crowd["week"], crowd["ind"], crowd["signal_count"])}

sd = plan["signal_date"].tolist()
nxt = dict(zip(sd[:-1], sd[1:]))
rows = []
for _, r in plan.iterrows():
    d = r["signal_date"]
    nd = nxt.get(d)
    if nd is None or d not in nav.index or nd not in nav.index:
        continue
    top3 = str(r["top3"]).split(",")
    row = {"signal_date": d, "regime": r["regime"], "exposure": r["exposure"],
           "r": nav[nd] / nav[d] - 1,
           "sc": float(np.mean([sc.get((d, i), np.nan) for i in top3]))}
    for inst in ("399006.SZ", "000300.SH", "399001.SZ"):
        m = ma[inst]
        row[f"bull_{inst}"] = bool(m["bull"].get(d, np.nan)) if d in m.index else np.nan
    if d in reg.set_index("date").index:
        row["T"] = float(reg.set_index("date").at[d, "T"])
    rows.append(row)
w = pd.DataFrame(rows)
w["T_hi"] = w["T"] > w["T"].median()

print(f"窗口 {w.signal_date.min().date()} ~ {w.signal_date.max().date()}  共 {len(w)} 周")
print(f"创业板指 MA200 有效覆盖：{w['bull_399006.SZ'].notna().mean():.1%}")
print(f"全期牛市占比（创业板 MA200）：{w['bull_399006.SZ'].mean():.1%}   "
      f"沪深300：{w['bull_000300.SH'].mean():.1%}\n")

print("=" * 76)
print("Q1 · 主线状态（T′ 符号）× 牛熊（创业板指 MA200）")
print("=" * 76)
for col, lbl in [("bull_399006.SZ", "创业板指"), ("bull_000300.SH", "沪深300"),
                 ("bull_399001.SZ", "深证成指")]:
    ct = pd.crosstab(w["regime"], w[col], normalize="index") * 100
    n = w.groupby("regime").size()
    print(f"\n  【{lbl} MA200】牛市占比 (%)")
    for rg in ("momentum", "reversal"):
        if rg in ct.index:
            b = ct.loc[rg].get(True, np.nan)
            print(f"    {rg:>8}（n={n[rg]:>3}）  牛市 {b:5.1f}%   熊市 {100-b:5.1f}%")
    d = ct.loc["reversal", True] - ct.loc["momentum", True] if "momentum" in ct.index else np.nan
    print(f"    → 反转周牛市占比 − 动量周 = {d:+.1f}pp")

print("\n" + "=" * 76)
print("Q2 · 变盘指数 **水平** T（扰动强度）× 牛熊（创业板指）")
print("=" * 76)
ct = pd.crosstab(w["T_hi"], w["bull_399006.SZ"], normalize="index") * 100
n = w.groupby("T_hi").size()
for k, lbl in ((False, "T 低（扰动弱）"), (True, "T 高（扰动强）")):
    if k in ct.index:
        print(f"  {lbl:<16} n={n[k]:>3}   牛市 {ct.loc[k].get(True, np.nan):5.1f}%")

print("\n" + "=" * 76)
print("Q3 · 策略实际周收益（冻结 nav）× regime × 牛熊（创业板指）")
print("=" * 76)
t = w.pivot_table(index="regime", columns="bull_399006.SZ", values="r", aggfunc=["mean", "count"])
for rg in ("momentum", "reversal"):
    if rg not in t.index:
        continue
    mu, ct_ = t.loc[rg]["mean"], t.loc[rg]["count"]
    print(f"  {rg:>8}:  牛市 {mu.get(True, np.nan)*100:+.3f}%/周 (n={int(ct_.get(True,0))})   "
          f"熊市 {mu.get(False, np.nan)*100:+.3f}%/周 (n={int(ct_.get(False,0))})")

print("\n  ── 只看满仓周（exposure=1）──")
f = w[w["exposure"] == 1]
t = f.pivot_table(index="regime", columns="bull_399006.SZ", values="r", aggfunc=["mean", "count"])
for rg in ("momentum", "reversal"):
    if rg not in t.index:
        continue
    mu, ct_ = t.loc[rg]["mean"], t.loc[rg]["count"]
    print(f"  {rg:>8}:  牛市 {mu.get(True, np.nan)*100:+.3f}%/周 (n={int(ct_.get(True,0))})   "
          f"熊市 {mu.get(False, np.nan)*100:+.3f}%/周 (n={int(ct_.get(False,0))})")

print("\n" + "=" * 76)
print("Q4 · 007 闸门是不是市场状态的代理？（动量周内部）")
print("=" * 76)
mo = f[f.regime == "momentum"]
mo = mo.assign(gated=mo["sc"] < 2)
ct = pd.crosstab(mo["gated"], mo["bull_399006.SZ"], normalize="index") * 100
n = mo.groupby("gated").size()
for k, lbl in ((False, "sc≥2 有量能（保留）"), (True, "sc<2 无量能（007 关掉）")):
    if k in ct.index:
        print(f"  {lbl:<24} n={n[k]:>3}   熊市占比 {ct.loc[k].get(False, np.nan):5.1f}%")
r = mo["bull_399006.SZ"].astype(float).corr(mo["sc"].astype(float))
print(f"  bull 与 sc 的相关（动量周满仓，n={len(mo)}）: {r:+.3f}")
print("\n  ── 对照：两种闸门各自关掉的周的重叠 ──")
bear = ~mo["bull_399006.SZ"].astype(bool)
gd = mo["gated"]
print(f"    量能闸关 {gd.sum()} 周；熊市闸关 {bear.sum()} 周；"
      f"重叠 {int((gd & bear).sum())} 周（占量能闸 {int((gd&bear).sum())/max(gd.sum(),1):.0%}）")

w.to_csv(HERE / "_regime_bullbear_panel.csv", index=False)
print(f"\n面板 → {HERE/'_regime_bullbear_panel.csv'}")
