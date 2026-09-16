"""v4 记录统计可视化（独立 fig 版，避免 subplot 丢 trace）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
dec = pd.read_parquet(HERE.parent / "detail_v4.parquet")
dec["date"] = pd.to_datetime(dec["date"])
dec = dec[dec["result"].isin(["success", "fail"])].copy()
dec["ret_pct"] = dec["ret"] * 100
overall = pd.read_csv(HERE / "overall.csv").iloc[0]
split = pd.read_csv(HERE / "exit_split.csv", encoding="utf-8-sig")
ic = pd.read_csv(HERE / "ic_summary.csv", encoding="utf-8-sig")
fx = pd.read_parquet(HERE / "features_v4.parquet")

figs = []
# ── 图1：离场成本拆分 ──
f = go.Figure()
f.add_trace(go.Bar(x=split["reason"], y=split["n"], name="n (count)",
                   marker_color="#2980b9"))
f.add_trace(go.Scatter(x=split["reason"], y=split["mean"], name="mean ret%",
                       mode="markers+lines", marker=dict(size=11, color="#c0392b"),
                       yaxis="y2"))
f.update_layout(template="plotly_white", height=400,
                title="Exit-reason cost split (bars=n, line=mean ret%): "
                      "stop_4atr=hard-stop cost, chan_nonpos=chandelier small-loss, chan_pos=take-profit",
                yaxis2=dict(overlaying="y", side="right", title="mean ret%"),
                margin=dict(l=50, r=60, t=70, b=30))
figs.append(f)

# ── 图2：ret 5% 桶 ──
edges = list(range(-50, 56, 5))
labels = [f"<{edges[0]}"] + [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges)-1)] + [f">={edges[-1]}"]
dec["bucket"] = pd.cut(dec["ret_pct"], bins=[-float("inf")]+edges+[float("inf")],
                       labels=labels, right=False)
b = dec.groupby("bucket", observed=False)["ret_pct"].agg(n="count").reset_index()
f = go.Figure(go.Bar(x=b["bucket"].astype(str), y=b["n"], marker_color="#8e44ad"))
f.update_layout(template="plotly_white", height=380, title="Ret 5% bucket distribution",
                xaxis_title="bucket", yaxis_title="n", margin=dict(l=50, r=20, t=60, b=60))
figs.append(f)

# ── 图3：特征 IC ──
s = ic.sort_values("ic_mean")
f = go.Figure()
f.add_trace(go.Bar(x=s["ic_mean"], y=s["feature"], orientation="h", name="IC mean",
                   marker_color=["#c0392b" if v < 0 else "#27ae60" for v in s["ic_mean"]]))
f.add_trace(go.Scatter(x=s["IR"], y=s["feature"], name="IR", mode="markers",
                       marker=dict(symbol="diamond", size=9, color="#2c3e50"),
                       xaxis="x2"))
f.update_layout(template="plotly_white", height=520,
                title="Feature RankIC mean (bar) + IR (diamond) — v4 trades",
                xaxis2=dict(overlaying="x", side="top", title="IR"),
                margin=dict(l=140, r=50, t=60, b=30), legend=dict(orientation="h", y=1.1))
figs.append(f)

# ── 图4：十分位单调（5 个关键特征）──
f = go.Figure()
for col, nm in [("ma_turn20_z", "ma_turn20"), ("roc_z", "roc"), ("macd_z", "macd"),
                ("llt_z", "llt"), ("dividend_yield_ratio_z", "div_yield")]:
    sub = fx[fx[col].notna()].copy()
    q = pd.qcut(sub[col], 10, labels=False, duplicates="drop")
    ym = sub.groupby(q)["ret"].mean() * 100
    f.add_trace(go.Scatter(x=list(range(1, len(ym)+1)), y=(ym - ym.iloc[0]).values,
                           mode="lines+markers", name=nm))
f.update_layout(template="plotly_white", height=460,
                title="Decile monotonicity (mean ret% vs D1 normalized to 0)",
                xaxis_title="feature decile", yaxis_title="ret% − D1 ret%",
                margin=dict(l=60, r=20, t=60, b=40), legend=dict(orientation="h"))
figs.append(f)

htmls = "".join(x.to_html(full_html=False, include_plotlyjs=False) for x in figs)
tiles = (f"<div class='item'><span>样本</span><b>{int(overall.n)}</b></div>"
         f"<div class='item'><span>胜率</span><b>{overall.win_rate*100:.1f}%</b></div>"
         f"<div class='item'><span>期望</span><b>{overall.mean_ret:+.2f}%</b></div>"
         f"<div class='item'><span>盈亏比</span><b>{overall.payoff:.2f}</b></div>")
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v4 stats</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 140px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:8px;}}
.metrics .item b{{display:block;font-size:18px;color:#2980b9;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
</style></head><body>
<h2>analysis_012 — v4 交易记录统计（{int(overall.n)} 笔已判定）</h2>
<div class="metrics">{tiles}</div>
{htmls}
</body></html>"""
(HERE / "v4_stats_view.html").write_text(html, encoding="utf-8")
print("v4_stats_view.html 已生成")
