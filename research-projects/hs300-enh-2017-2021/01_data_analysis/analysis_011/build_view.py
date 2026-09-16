"""analysis_011 — result_view.html：十分位 × 成功/失败分布（三段对照）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
stats = pd.read_csv(HERE / "decile_stats.csv")
SEGS = ["S1_2015-2020", "S2_2021-2026", "S3_全期"]
SEG_NAME = {"S1_2015-2020": "S1 2015-20", "S2_2021-2026": "S2 2021-26", "S3_全期": "S3 full"}
COLORS = {"S1_2015-2020": "#2980b9", "S2_2021-2026": "#27ae60", "S3_全期": "#8e44ad"}

fig = make_subplots(rows=3, cols=1, row_heights=[0.34, 0.34, 0.32], shared_xaxes=True,
                    vertical_spacing=0.07,
                    subplot_titles=("Success cases by breakout-price decile (past 1y window) — count",
                                    "Failure cases by decile — count",
                                    "Win rate by decile (3 segments) + full-period avg return"))

for seg in SEGS:
    s = stats[stats["segment"] == seg]
    fig.add_trace(go.Bar(x=s["decile"], y=s["n_ok"], name=f"{SEG_NAME[seg]} ok",
                         marker_color=COLORS[seg], opacity=0.85), row=1, col=1)
    fig.add_trace(go.Bar(x=s["decile"], y=s["n_bad"], name=f"{SEG_NAME[seg]} bad",
                         marker_color=COLORS[seg], opacity=0.45), row=2, col=1)
    fig.add_trace(go.Scatter(x=s["decile"], y=s["win_rate"] * 100, name=f"{SEG_NAME[seg]} win%",
                             mode="lines+markers", line=dict(color=COLORS[seg], width=1.8)), row=3, col=1)

s3 = stats[stats["segment"] == "S3_全期"]
fig.add_trace(go.Bar(x=s3["decile"], y=s3["avg_ret"], name="full avg ret %/trade",
                     marker_color="#f39c12", opacity=0.6, yaxis="y4"), row=3, col=1)
fig.update_layout(template="plotly_white", height=920, hovermode="x unified",
                  margin=dict(l=50, r=55, t=60, b=40),
                  legend=dict(orientation="h", y=1.04), barmode="group",
                  yaxis4=dict(overlaying="y3", side="right", title="avg ret %",
                              showgrid=False))

# 表格（HTML）
rows = "".join(
    f"<tr><td>{r.segment}</td><td>{int(r.decile)}</td><td>{int(r.n_ok)}</td>"
    f"<td>{int(r.n_bad)}</td><td>{r.ok_share*100:.1f}%</td><td>{r.bad_share*100:.1f}%</td>"
    f"<td>{r.win_rate*100:.1f}%</td><td>{r.avg_ret:+.2f}%</td></tr>"
    for r in stats.itertuples())

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_011 — 突破价十分位分布</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
table{{border-collapse:collapse;margin:14px 0;font-size:13px;}}
th,td{{border:1px solid #d6dae1;padding:4px 10px;text-align:center;}}
th{{background:#f3f5f8;}}
</style></head><body>
<h2>analysis_011 — A_v2 突破价在过去 1 年价格分布的十分位 × 成功/失败</h2>
<div class="note">十分位 = 信号日收盘在该股过去 252 个交易日收盘分布中的分位档（1=最低10%，10=最高10%）；
成功 = return_pct &gt; 0。三段（按信号日）对照防上帝视角：S1 2015-20（实际 2017-04 起）/
S2 2021-26 / S3 全期。历史窗口≥200 根占比 100%。</div>
{fig.to_html(full_html=False, include_plotlyjs=False, div_id='fig')}
<h3>明细表</h3>
<table><tr><th>段</th><th>分位档</th><th>成功数</th><th>失败数</th><th>占成功%</th>
<th>占失败%</th><th>档内成功率</th><th>档内均收益</th></tr>{rows}</table>
</body></html>"""
(HERE / "result_view.html").write_text(html, encoding="utf-8")
print("result_view.html 已生成")
