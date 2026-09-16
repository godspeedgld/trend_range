"""alpha 检验可视化：v3 vs 随机 收益率分布 + 年度 alpha + 显著检验。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
v = pd.read_parquet(HERE / "v3_ret.parquet")
r = pd.read_parquet(HERE / "random_ret.parquet")
for d in (v, r):
    d["ret_pct"] = d["ret"] * 100
alpha = pd.read_csv(HERE / "alpha_summary.csv")

fig = make_subplots(rows=2, cols=2, row_heights=[0.5, 0.5],
                    subplot_titles=("Ret distribution: v3 signals vs random stocks (clip ±50%)",
                                    "Annual mean ret % (v3 vs random)",
                                    "Ret by exit reason (v3)",
                                    "Cumulative: alpha (v3−random, day-mean)"))
# 1) 分布直方（截断 ±50% 便于看主体）
for d, nm, col in ((v, "v3 signals", "#2980b9"), (r, "random stocks", "#95a5a6")):
    c = d["ret_pct"].clip(-50, 50)
    fig.add_trace(go.Histogram(x=c, name=nm, opacity=0.6, nbinsx=60,
                               marker_color=col), row=1, col=1)

# 2) 年度
v["y"], r["y"] = v["date"].dt.year, r["date"].dt.year
yv = v.groupby("y")["ret_pct"].mean()
yr = r.groupby("y")["ret_pct"].mean()
fig.add_trace(go.Bar(x=yv.index, y=yv.values, name="v3", marker_color="#2980b9"), row=1, col=2)
fig.add_trace(go.Bar(x=yr.index, y=yr.values, name="random", marker_color="#95a5a6",
                     opacity=0.7), row=1, col=2)

# 3) v3 离场构成
reason = v.groupby("reason")["ret_pct"].agg(["count", "mean"]).reset_index()
fig.add_trace(go.Bar(x=reason["reason"], y=reason["count"], name="count",
                     marker_color="#c0392b", yaxis="y3"), row=2, col=1)
fig.add_trace(go.Scatter(x=reason["reason"], y=reason["mean"], name="mean ret%",
                         mode="markers+lines", marker=dict(size=10, color="#f39c12"),
                         yaxis="y4"), row=2, col=1)

# 4) 按信号日对齐的累积 alpha
v_by_day = v.groupby("date")["ret_pct"].mean()
r_by_day = r.groupby("date")["ret_pct"].mean()
j = v_by_day.sub(r_by_day, fill_value=0).sort_index().cumsum()
fig.add_trace(go.Scatter(x=j.index, y=j.values, name="cum alpha (v3−random)",
                         line=dict(color="#27ae60", width=1.6)), row=2, col=2)

fig.update_layout(template="plotly_white", height=820, hovermode="x unified",
                  margin=dict(l=50, r=55, t=60, b=30),
                  barmode="group",
                  legend=dict(orientation="h", y=1.04),
                  yaxis3=dict(overlaying="y", side="right", showgrid=False, title="count"),
                  yaxis4=dict(overlaying="y3", side="right", showgrid=False))
fig.write_html(str(HERE / "alpha_view.html"))

rows = "".join(
    f"<tr><td>{int(r.v3_n)}</td><td>{int(r.random_n)}</td><td>{r.v3_mean_ret*100:+.2f}%</td>"
    f"<td>{r.random_mean_ret*100:+.2f}%</td><td>{r.day_diff_mean_pp:+.2f}pp</td>"
    f"<td>{r.t_p:.4f}</td></tr>" for r in alpha.itertuples())
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_007 u5 — v3 alpha 检验</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body>
<h2>analysis_007 更新五 — v3 事件 alpha 检验（随机股 + 同规则）</h2>
<div style="color:#6b7480;font-size:13px">随机组：每信号日抽当日成分(非本事件股)10 只伪事件，
同 4×ATR 吊灯 + 信号价×0.95 止损规则（v3 用阻力线）。检验：按信号日配对 v3 vs 随机。</div>
<table style="border-collapse:collapse;margin:10px 0"><tr style="background:#f3f5f8">
<th>v3 事件数</th><th>随机伪事件数</th><th>v3 均值</th><th>随机均值</th>
<th>日差</th><th>t-p值</th></tr>{rows}</table>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "alpha_view.html").write_text(html, encoding="utf-8")
print("alpha_view.html 已生成")
