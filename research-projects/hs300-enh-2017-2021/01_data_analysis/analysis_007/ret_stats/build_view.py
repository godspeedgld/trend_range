"""ret_stats 可视化：总体瓦片 + ret桶分布 + degree/十分位 箱线+均值期望。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
overall = pd.read_csv(HERE / "overall.csv").iloc[0]
bucket = pd.read_csv(HERE / "by_retbucket.csv", encoding="utf-8-sig")
deg = pd.read_csv(HERE / "by_degree.csv", encoding="utf-8-sig")
dci = pd.read_csv(HERE / "by_decile.csv", encoding="utf-8-sig")
inp = pd.read_csv(HERE / "stats_input.csv", encoding="utf-8-sig")
inp["g_deg"] = inp["degree"].clip(upper=20).map(lambda d: "6+" if d > 6 else str(d))
inp = inp[inp["decile"].notna()]

fig = make_subplots(rows=2, cols=2, row_heights=[0.5, 0.5],
                    subplot_titles=("Ret distribution by 5% bucket (n)",
                                    "By degree: median(IQR) box + mean dot",
                                    "By decile (past-1y price pos): box + mean dot",
                                    "Expected ret (mean%) by decile & degree"))
# 1) 桶分布柱
fig.add_trace(go.Bar(x=bucket["bucket"], y=bucket["n"], name="count",
                     marker_color="#2980b9"), row=1, col=1)
# 2) degree 箱线(截度>=11? 全) — 用 2..20 + 6+ 归并避免过密
degv = inp[inp["degree"] <= 20].copy()
order = [str(i) for i in range(2, 7)] + ["6+"]
for g in order:
    y = degv[degv["g_deg"] == g]["ret_pct"]
    if len(y):
        fig.add_trace(go.Box(y=y, name=f"deg {g}", boxpoints=False,
                             line=dict(width=1), marker_color="#7f8c8d"), row=1, col=2)
mean_deg = inp.groupby("g_deg")["ret_pct"].mean()
fig.add_trace(go.Scatter(x=order, y=[mean_deg.get(g, None) for g in order],
                         name="mean", mode="markers",
                         marker=dict(color="#c0392b", size=9)), row=1, col=2)
# 3) 十分位箱线
dord = list(range(1, 11))
for d in dord:
    y = inp[inp["decile"] == d]["ret_pct"]
    fig.add_trace(go.Box(y=y, name=f"dec {d}", boxpoints=False,
                         line=dict(width=1), marker_color="#8e44ad"), row=2, col=1)
fig.add_trace(go.Scatter(x=dord, y=dci["mean"], name="mean",
                         mode="markers+lines", marker=dict(color="#f39c12", size=8)),
              row=2, col=1)
# 4) 期望：degree 档（2..11）vs decile 档（1..10）同框对照
dcols = list(range(1, 11))
fig.add_trace(go.Scatter(x=dcols, y=dci["mean"], name="mean% by decile(1..10)",
                         mode="lines+markers", line=dict(color="#8e44ad")), row=2, col=2)
mdeg = deg.set_index("degree")["mean"].reindex(range(2, 12))
fig.add_trace(go.Scatter(x=list(range(2, 12)), y=mdeg, name="mean% by degree(2..11)",
                         mode="lines+markers", line=dict(color="#27ae60")), row=2, col=2)

fig.update_layout(template="plotly_white", height=880, hovermode="closest",
                  margin=dict(l=50, r=20, t=60, b=30),
                  showlegend=True, boxmode="overlay",
                  legend=dict(orientation="h", y=1.04))

tiles = (f"<div class='item'><span>胜率</span><b>{overall.win_rate*100:.1f}%</b></div>"
         f"<div class='item'><span>盈亏比</span><b>{overall.payoff:.2f}</b></div>"
         f"<div class='item'><span>期望/笔</span><b>{overall.mean_ret_pct:+.2f}%</b></div>"
         f"<div class='item'><span>中位</span><b>{overall.median_ret_pct:+.2f}%</b></div>"
         f"<div class='item'><span>笔数</span><b>{int(overall.n)}</b></div>")

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_007 ret_stats</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:10px 4px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;color:#2980b9;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
</style></head><body>
<h2>analysis_007 更新六 — 交易结果统计（m=4 吊灯 + degree≥2，12900 已判定事件）</h2>
<div class="note">ret 分布 5% 桶：<b>-10~-5% 最密（5004 笔，均 -7.1%）</b>=止损集中带；&gt;=55% 358 笔均 +105%（右尾巨赢）。
degree 期望自 2 档 +2.6% 递减至 11+ 转负；十分位 1-3 档(一年低位)负期望、6 档最高 +3.3%、第10档占 56% 但均仅 +1.6%。</div>
<div class="metrics">{tiles}</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "ret_stats_view.html").write_text(html, encoding="utf-8")
print("ret_stats_view.html 已生成")
