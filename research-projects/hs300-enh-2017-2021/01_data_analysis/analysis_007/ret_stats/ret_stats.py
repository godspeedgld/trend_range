"""analysis_007 更新六 — 交易结果深度统计。

输入：breakout_detail_v3.parquet（12977 事件，m=4/degree≥2，已判定 12900）。
输出四部分：
  1. 总体：胜率 / 盈亏比
  2. ret 分布：5% 一桶（-50%..+50% 各桶 + 尾部）
  3. degree 分布：逐 degree 平均/中位/分布/期望
  4. 十分位分布：突破价在过去 252 日收盘分布的十分位，逐档平均/中位/分布/期望
     （复用 analysis_011 decile 口径；每事件用 v3_events_cache.sig_i 定位历史）
全部输出 CSV + ret_stats_view.html 可视化。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
A7 = HERE.parent
PROJ = A7.parents[1]

det = pd.read_parquet(A7 / "breakout_detail_v3.parquet")
det["date"] = pd.to_datetime(det["date"])
det["ret_pct"] = det["ret"] * 100
dec = det[det["result"].isin(["success", "fail"])].copy()   # 已判定 12900
print(f"已判定 {len(dec)}（成功 {(dec.result=='success').sum()} / 失败 {(dec.result=='fail').sum()}）")

# ── 1. 总体 ──
wins, losses = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
wr = len(wins) / len(dec)
payoff = wins.mean() / abs(losses.mean())
print(f"胜率 {wr*100:.1f}% | 盈亏比 {payoff:.2f} | 期望 {dec['ret'].mean()*100:+.2f}%")

# ── 2. ret 5% 桶分布 ──
# 桶：<-50、[-50,-45)…[50,55)、>=55（含 5% 步长 + 两端开放尾）
edges = list(range(-50, 56, 5))                    # -50..55, 21 个内边界
labels = [f"<{edges[0]}"] + [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges) - 1)] \
         + [f">={edges[-1]}"]
bins_all = [-np.inf] + edges + [np.inf]
dec["bucket"] = pd.cut(dec["ret_pct"], bins=bins_all, labels=labels, right=False)
bucket = (dec.groupby("bucket", observed=False)["ret_pct"]
          .agg(n="count", mean="mean").reset_index())
tail_lo = int((dec["ret_pct"] < -50).sum())
tail_hi = int((dec["ret_pct"] >= 55).sum())
print(f"\n[2] ret 5% 桶：{len(labels)} 桶；尾部 <-50 {tail_lo} 笔 / >=55 {tail_hi} 笔")
print(bucket.to_string(index=False))
bucket.to_csv(HERE / "by_retbucket.csv", index=False, encoding="utf-8-sig")

# ── 3. degree 分布 ──
deg = (dec.groupby("degree")["ret_pct"]
       .agg(n="count", mean="mean", median="median", std="std",
            p10=lambda s: s.quantile(0.1), p90=lambda s: s.quantile(0.9),
            q1=lambda s: s.quantile(0.25), q3=lambda s: s.quantile(0.75)).reset_index())
deg.to_csv(HERE / "by_degree.csv", index=False, encoding="utf-8-sig")
print(f"\n[3] degree 2~{deg['degree'].max()}：见 by_degree.csv（{len(deg)} 档）")
print(deg.head(10).round(3).to_string(index=False))

# ── 4. 十分位（事件过去 252 日收盘分布）──
ev = pd.read_parquet(A7 / "v3_events_cache.parquet")
ev["date"] = pd.to_datetime(ev["date"])
ev = ev[ev["degree"] >= 2]                       # 与 detail 同过滤
# 用 symbol+date merge 取 sig_i（detail 无 sig_i，cache 有）
m = dec.merge(ev[["symbol", "date", "sig_i"]], on=["symbol", "date"], how="left")

panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
by_sym_close = {s: g["close"].to_numpy(float) for s, g in panel.groupby("symbol")}
WINDOW = 252

decile_list = []
for r in m.itertuples():
    arr = by_sym_close.get(r.symbol)
    if arr is None or pd.isna(r.sig_i):
        decile_list.append(np.nan)
        continue
    i = int(r.sig_i)
    lo = max(0, i - WINDOW + 1)
    win = arr[lo:i + 1]
    pct = float((win < arr[i]).mean())
    decile_list.append(min(int(pct * 10) + 1, 10))
m["decile"] = decile_list

dc = (m.groupby("decile")["ret_pct"]
      .agg(n="count", mean="mean", median="median", std="std",
           p10=lambda s: s.quantile(0.1), p90=lambda s: s.quantile(0.9),
           q1=lambda s: s.quantile(0.25), q3=lambda s: s.quantile(0.75)).reset_index())
dc.to_csv(HERE / "by_decile.csv", index=False, encoding="utf-8-sig")
print(f"\n[4] 十分位 1~10：见 by_decile.csv")
print(dc.round(3).to_string(index=False))

# 落盘分位数据（供可视化箱线）
m[["symbol", "date", "degree", "ret_pct", "decile"]].to_csv(
    HERE / "stats_input.csv", index=False, encoding="utf-8-sig")

# 总览写 summary
pd.DataFrame([{"win_rate": wr, "payoff": payoff, "mean_ret_pct": dec["ret_pct"].mean(),
               "median_ret_pct": dec["ret_pct"].median(), "n": len(dec)}]).to_csv(
    HERE / "overall.csv", index=False)
print("\n写出 ret_stats/: overall.csv / by_degree.csv / by_decile.csv / stats_input.csv")
