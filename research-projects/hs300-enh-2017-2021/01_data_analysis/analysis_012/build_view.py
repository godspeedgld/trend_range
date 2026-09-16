"""analysis_012 可视化：IC 汇总条形 + 分 feature 月度IC时序与累计IC + 十分位单调曲线。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
fx = pd.read_parquet(HERE / "features.parquet")
summary = pd.read_csv(HERE / "ic_summary.csv", encoding="utf-8-sig")
icm = pd.read_csv(HERE / "ic_monthly.csv", index_col=0, parse_dates=True)
FEATURES = summary["feature"].tolist()

# ── 图1：IC 汇总（按 |IC| 排序）──
s = summary.sort_values("ic_mean")
fig1 = make_subplots(rows=1, cols=2, subplot_titles=("RankIC mean (bar) + IR (dot)",
                                                     "IC>0 月占比 / 月数"))
fig1.add_trace(go.Bar(x=s["ic_mean"], y=s["feature"], orientation="h",
                      marker_color=["#c0392b" if v < 0 else "#27ae60" for v in s["ic_mean"]],
                      name="IC mean"), 1, 1)
fig1.add_trace(go.Scatter(x=s["IR"], y=s["feature"], mode="markers",
                          marker=dict(symbol="diamond", size=9, color="#2c3e50"),
                          name="IR", xaxis="x2"), 1, 1)
pos = (icm > 0).mean()
fig1.add_trace(go.Bar(x=pos[s["feature"]].values * 100, y=s["feature"], orientation="h",
                      marker_color="#2980b9", name="IC>0 months %"), 1, 2)
fig1.update_layout(template="plotly_white", height=520, hovermode="y",
                   margin=dict(l=90, r=40, t=50, b=40),
                   xaxis2=dict(overlaying="x", side="top", title="IR"),
                   legend=dict(orientation="h", y=1.08))

# ── 图2：逐 feature 月度 IC + 累计 IC（网格小图）──
n = len(FEATURES)
ncol = 4
nrow = int(np.ceil(n / ncol))
fig2 = make_subplots(rows=nrow, cols=ncol, subplot_titles=FEATURES,
                     horizontal_spacing=0.06, vertical_spacing=0.05)
colors = plt_col = ["#2980b9"] * n
for i, f in enumerate(FEATURES):
    r, c = i // ncol + 1, i % ncol + 1
    ser = icm[f].dropna()
    fig2.add_trace(go.Bar(x=ser.index, y=ser.values, marker_color="#95a5a6", opacity=0.55,
                          showlegend=False, name=f), row=r, col=c)
    cum = ser.cumsum()
    fig2.add_trace(go.Scatter(x=cum.index, y=cum.values, mode="lines",
                              line=dict(color="#c0392b", width=1.6), showlegend=False,
                              name=f), row=r, col=c)
fig2.update_layout(template="plotly_white", height=290 * nrow,
                   margin=dict(l=40, r=20, t=30, b=30),
                   title="Monthly rank IC (grey bars) & cumulative IC (red line) — per feature")

# ── 图3：十分位单调曲线（每 feature 一条线，归一到首桶=0）──
fig3 = go.Figure()
for f in FEATURES:
    v = fx[f].notna()
    try:
        q = pd.qcut(fx.loc[v, f], 10, labels=False, duplicates="drop")
        ym = fx.loc[v].groupby(q)["ret"].mean() * 100
        base = ym - ym.iloc[0]
        fig3.add_trace(go.Scatter(x=list(range(1, len(ym) + 1)), y=base.values,
                                  mode="lines+markers", name=f))
    except Exception:
        pass
fig3.update_layout(template="plotly_white", height=520,
                   title="Decile monotonicity: mean ret% by feature decile (D1 normalized to 0)",
                   xaxis_title="feature decile (D1 low → D10 high)",
                   yaxis_title="ret% − D1 ret%", hovermode="x unified",
                   margin=dict(l=60, r=20, t=60, b=40))

tiles = "".join(
    f"<div class='item'><span>{r.feature}</span><b>{r.ic_mean:+.3f}</b>"
    f"<small>IR {r.IR:+.2f} | mono {r.mono_pct*100:.0f}% | {int(r.ic_n_months)}m</small></div>"
    for r in summary.itertuples())

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_012 — 特征×收益率</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;}}
.metrics .item{{flex:1 1 150px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:8px 4px;}}
.metrics .item b{{display:block;font-size:16px;color:#8e44ad;}}
.metrics .item span{{font-weight:bold;font-size:12px;}}
.metrics .item small{{color:#6b7480;font-size:11px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
</style></head><body>
<h2>analysis_012 — 更新八交易 × t 日特征：相关 / IC·IR / 累计IC / 单调性</h2>
<div class="note">基础：analysis_007 更新八（静态4ATR止损+吊灯前日ATR）12847 笔。y=事件 ret；
x=信号日 t 值（≤t 无未来），月度截面 z-score。IC=月截面 spearman(z, ret)；
LLT 仅 43 个月（2015 起暖机后才有斜率）。估值类已 log、pe 剔负。</div>
<div class="metrics">{tiles}</div>
{fig1.to_html(full_html=False, include_plotlyjs=False, div_id='f1')}
{fig2.to_html(full_html=False, include_plotlyjs=False, div_id='f2')}
{fig3.to_html(full_html=False, include_plotlyjs=False, div_id='f3')}
</body></html>"""
(HERE / "result_view.html").write_text(html, encoding="utf-8")
print("result_view.html 已生成")
