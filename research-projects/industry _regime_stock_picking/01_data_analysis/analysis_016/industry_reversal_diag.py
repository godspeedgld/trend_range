"""行业层诊断（只读缓存，不改任何冻结件）—— 2026-10-16

回答两个问题：
  Q1（用户设想）：反转周里，「60 日涨幅不大 / 但近 5 日涨幅大」的行业，下周是否更好？
  Q2（理解核对）：007 的拥挤度闸门，靠的是「top3 行业自身的拥挤度」还是「全市场活跃度」？

口径：行业层周频，信号日 t 选行业，持有到下一信号日（close_t → close_{t+1}）。
      行业池 = 申万 L1 31 个（industry_index.parquet）；regime/top3 来自 weekly_plan.parquet。
      纯观测（不构成可交易结论），无成本。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]        # 归档后位于 <PROJ>/01_data_analysis/analysis_016/
CACHE = PROJ / "shared" / "_cache"

ind = pd.read_parquet(CACHE / "industry_index.parquet")
plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
crowd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")

px = ind.pivot(index="date", columns="ind_name", values="close").sort_index()
m240 = ind.pivot(index="date", columns="ind_name", values="mom_240").sort_index()
m60 = ind.pivot(index="date", columns="ind_name", values="mom_60").sort_index()
m20 = px.pct_change(20)
m5 = px.pct_change(5)
m1 = px.pct_change(1)

sigs = sorted(pd.to_datetime(plan["signal_date"]))
sigs = [d for d in sigs if d in px.index]
fwd = {a: (px.loc[b] / px.loc[a] - 1) for a, b in zip(sigs[:-1], sigs[1:])}

regime = dict(zip(pd.to_datetime(plan["signal_date"]), plan["regime"]))
top3 = {d: str(t).split(",") for d, t in
        zip(pd.to_datetime(plan["signal_date"]), plan["top3"])}

# 拥挤度：周 → 行业 → signal_count
sc = {(pd.Timestamp(w), i): float(s) for w, i, s in
      zip(crowd["week"], crowd["ind"], crowd["signal_count"])}

N_POOL = 10          # 候选池 = 按主排序取 10 个（top3 的 ~3 倍）


def pool_of(t: str) -> list[str]:
    """反转周：mom_60 最低 10 个；动量周：mom_240 最高 10 个。"""
    if regime[t] == "reversal":
        return m60.loc[t].nsmallest(N_POOL).index.tolist()
    return m240.loc[t].nlargest(N_POOL).index.tolist()


rows = []
for t in sigs[:-1]:
    if t not in fwd:
        continue
    f = fwd[t]
    pool = pool_of(t)
    if not all(i in f.index for i in pool):
        continue
    sc_all = np.mean([sc.get((t, i), np.nan) for i in px.columns])
    sc_pool = np.mean([sc.get((t, i), np.nan) for i in pool])
    sc_top3 = np.mean([sc.get((t, i), np.nan) for i in top3[t]])
    for i in pool:
        rows.append({
            "date": t, "regime": regime[t], "ind": i, "fwd": f[i],
            "mom_60": m60.at[t, i], "mom_240": m240.at[t, i],
            "mom_20": m20.at[t, i], "mom_5": m5.at[t, i], "mom_1": m1.at[t, i],
            "sc": sc.get((t, i), np.nan), "sc_pool": sc_pool, "sc_all": sc_all,
            "sc_top3": sc_top3, "is_top3": i in top3[t],
        })
df = pd.DataFrame(rows).dropna(subset=["mom_60", "mom_5", "fwd"])
print(f"样本 {len(df):,} 行 / {df['date'].nunique()} 信号日 / "
      f"动量周 {df[df.regime=='momentum']['date'].nunique()} · "
      f"反转周 {df[df.regime=='reversal']['date'].nunique()}")


def bucket_stats(d: pd.DataFrame, by: str, q: int = 3, label: str = "") -> pd.DataFrame:
    """每个信号日内按 by 因子分位切 q 档，报各档下周收益（周内先分档再取均值 → 剔除时间效应）。"""
    d = d.dropna(subset=[by]).copy()
    d["bkt"] = d.groupby("date")[by].transform(
        lambda s: pd.qcut(s.rank(method="first"), q, labels=False))
    g = d.groupby("bkt")["fwd"].agg(["mean", "count"])
    g["mean_%"] = (g["mean"] * 100).round(3)
    g.index = [f"{label}Q{int(i)+1}" for i in g.index]
    return g[["mean_%", "count"]]


def ic(d: pd.DataFrame, by: str) -> tuple[float, float]:
    """逐周截面 Spearman（池内），返回 (IC 均值, t 值)。"""
    d = d.dropna(subset=[by])
    r = d.groupby("date").apply(
        lambda g: g[by].corr(g["fwd"], method="spearman") if len(g) > 3 else np.nan,
        include_groups=False).dropna()
    return float(r.mean()), float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))


print("\n" + "=" * 78)
print("Q1 · 反转周（top3 = mom_60 最低 3 个）—— 候选池 10 个内，短周期动量有无用？")
print("=" * 78)
rev = df[df.regime == "reversal"]
print(f"\n反转周候选池整体下周收益 {rev['fwd'].mean()*100:+.3f}%  "
      f"（实际 top3 口径 {rev[rev.is_top3]['fwd'].mean()*100:+.3f}%）\n")
for f in ["mom_5", "mom_1", "mom_20"]:
    lo, hi = ic(rev, f)
    print(f"  {f:>7}  池内 IC {lo:+.4f} (t {hi:+.2f})")
print()
for f in ["mom_5", "mom_1", "mom_20"]:
    print(bucket_stats(rev, f, 3, f).to_string(), "\n")

print("  ── 用户设想的直接切法：mom_60 低 + mom_5 高 ──")
rev2 = rev.copy()
rev2["sig"] = np.sign(rev2["mom_5"])
print(rev2.groupby("sig")["fwd"].agg(["mean", "count"]).assign(
    pct=lambda x: (x["mean"] * 100).round(3))[["pct", "count"]].to_string())
q60 = rev2["mom_60"].quantile(0.5)
sub = rev2[rev2["mom_60"] <= q60]
print("\n  ── 只在「深度超跌」一半（mom_60 低于中位）里，再看 mom_5 符号 ──")
print(sub.groupby("sig")["fwd"].agg(["mean", "count"]).assign(
    pct=lambda x: (x["mean"] * 100).round(3))[["pct", "count"]].to_string())

print("\n" + "=" * 78)
print("对照 · 动量周（top3 = mom_240 最高 3 个）")
print("=" * 78)
mom = df[df.regime == "momentum"]
print(f"\n动量周候选池整体下周收益 {mom['fwd'].mean()*100:+.3f}%  "
      f"（实际 top3 口径 {mom[mom.is_top3]['fwd'].mean()*100:+.3f}%）\n")
for f in ["mom_5", "mom_1", "mom_20"]:
    lo, hi = ic(mom, f)
    print(f"  {f:>7}  池内 IC {lo:+.4f} (t {hi:+.2f})")
print()
print(bucket_stats(mom, "mom_5", 3, "mom_5").to_string())

print("\n" + "=" * 78)
print("Q2 · 拥挤度闸门：是「top3 自身拥挤」还是「全市场活跃」？")
print("=" * 78)
mw = mom.drop_duplicates("date")[["date", "sc_pool", "sc_all", "sc_top3"]]
mw["top3_fwd"] = mom[mom.is_top3].groupby("date")["fwd"].mean().reindex(mw["date"]).values
mw = mw.dropna()
for col in ["sc_top3", "sc_pool", "sc_all"]:
    med = mw[col].median()
    a = mw[mw[col] >= med]["top3_fwd"]
    b = mw[mw[col] < med]["top3_fwd"]
    t = (a.mean() - b.mean()) / np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    print(f"  按 {col:>8} 中位(={med:.2f})切：高 {a.mean()*100:+.3f}%(n={len(a)})  "
          f"低 {b.mean()*100:+.3f}%(n={len(b)})  差 {(a.mean()-b.mean())*100:+.3f}pp  t {t:+.2f}")
print("\n  ── 2×2：top3 拥挤 × 全市场活跃 ──")
mw["hi_top3"] = mw["sc_top3"] >= mw["sc_top3"].median()
mw["hi_all"] = mw["sc_all"] >= mw["sc_all"].median()
print(mw.groupby(["hi_all", "hi_top3"])["top3_fwd"].agg(["mean", "count"]).assign(
    pct=lambda x: (x["mean"] * 100).round(3))[["pct", "count"]].to_string())

df.to_csv(HERE / "_industry_diag_panel.csv", index=False)
mw.to_csv(HERE / "_industry_diag_weeks.csv", index=False)
print(f"\n面板 → {HERE/'_industry_diag_panel.csv'}")
