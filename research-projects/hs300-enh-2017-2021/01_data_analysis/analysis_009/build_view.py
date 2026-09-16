"""analysis_009 — result_view.html：指数+状态背景 / 扩散指标快慢线 / 前瞻收益对比。"""
from __future__ import annotations

import duckdb
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = __import__("pathlib").Path(__file__).resolve().parent
N1, N2 = 80, 35

st = pd.read_csv(HERE / "states_daily.csv", index_col=0, parse_dates=True)
dif = pd.read_csv(HERE / "diffusion_mcap.csv", index_col=0, parse_dates=True)["D"]
fw = pd.read_csv(HERE / "forward_returns.csv", index_col=0)

con = duckdb.connect(r"C:\Quant\trend_range\data_cache\bigquant_warehouse\bigquant_warehouse.duckdb",
                     read_only=True)
idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                  "ORDER BY date").fetchdf()
con.close()
idx["date"] = pd.to_datetime(idx["date"])
close = idx.set_index("date")["close"]

state = st["LLT扩散_市值加权_80_35"].reindex(close.index)
fast = dif.rolling(N1).mean().reindex(close.index)
slow = fast.rolling(N2).mean()

fig = make_subplots(rows=3, cols=1, row_heights=[0.5, 0.28, 0.22], shared_xaxes=True,
                    vertical_spacing=0.05,
                    subplot_titles=("CSI300 close + LLT-diffusion regime background "
                                    "(red=bull fast>slow, green=bear)",
                                    "LLT diffusion D (mcap-weighted) + fast/slow lines",
                                    "Bull-state diffusion D (mcap-weighted)"))

# 背景色块（多=红/空=绿；用 add_shape + y domain——regime_view 已验证可显示的方案）
s = state.fillna(-1)
blocks = (s != s.shift(1)).fillna(True)
start = 0
for i in range(1, len(s) + 1):
    if i == len(s) or blocks.iloc[i]:
        v = s.iloc[start]
        if v in (0.0, 1.0):
            color = "rgba(255,120,120,0.35)" if v > 0.5 else "rgba(120,220,140,0.35)"
            fig.add_shape(type="rect",
                          x0=close.index[start], x1=close.index[i - 1],
                          y0=0, y1=1, xref="x", yref="y domain",
                          fillcolor=color, layer="below", line_width=0)
        start = i

fig.add_trace(go.Scatter(x=close.index, y=close, name="CSI300 close",
                         line=dict(color="#2c3e50", width=1.3)), row=1, col=1)
fig.add_trace(go.Scatter(x=dif.index, y=dif, name="D (bull fraction)",
                         line=dict(color="#8e44ad", width=1.1)), row=2, col=1)
fig.add_trace(go.Scatter(x=fast.index, y=fast, name=f"fast MA{N1}",
                         line=dict(color="#2980b9", width=1.4)), row=2, col=1)
fig.add_trace(go.Scatter(x=slow.index, y=slow, name=f"slow MA{N2} of fast",
                         line=dict(color="#c0392b", width=1.4)), row=2, col=1)

# 前瞻收益分组柱（多头 vs 空头，K=1/5/20/60）
ks = [("1d", "1"), ("5d", "5"), ("20d", "20"), ("60d", "60")]
x = [f"K={k}" for _, k in ks]
fig.add_trace(go.Bar(x=x, y=[fw.loc["LLT扩散_市值加权_80_35", f"多头{k}d"] for _, k in ks],
                     name="bull-state fwd ann%", marker_color="#e74c3c", opacity=0.8), row=3, col=1)
fig.add_trace(go.Bar(x=x, y=[fw.loc["LLT扩散_市值加权_80_35", f"空头{k}d"] for _, k in ks],
                     name="bear-state fwd ann%", marker_color="#27ae60", opacity=0.8), row=3, col=1)

fig.update_layout(template="plotly_white", height=860, hovermode="x unified",
                  margin=dict(l=50, r=20, t=60, b=30),
                  legend=dict(orientation="h", y=1.04),
                  title="analysis_009 — LLT(d=60) diffusion regime (strict membership)")

tiles = "".join(
    f"<div class='item'><span>{i}</span><b>{r['多头60d']:+.1f}% / {r['空头60d']:+.1f}%</b>"
    f"<small>前瞻60日 多/空年化</small></div>"
    for i, r in fw.iterrows())

# 段落表（主口径状态连续段：起止/状态/天数）
s = state.dropna()
segs = []
blocks = (s != s.shift()).cumsum()
for _, g in s.groupby(blocks):
    segs.append({"start": g.index[0].date().isoformat(),
                 "end": g.index[-1].date().isoformat(),
                 "state": "多头" if g.iloc[0] > 0.5 else "空头",
                 "days": len(g)})
seg_rows = "".join(
    f"<tr><td>{i}</td><td>{r['start']}</td><td>{r['end']}</td>"
    f"<td style='color:{'#c0392b' if r['state']=='多头' else '#27ae60'}'><b>{r['state']}</b></td>"
    f"<td>{r['days']}</td></tr>"
    for i, r in enumerate(segs, 1))

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_009 — LLT 扩散指标牛熊划分</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 240px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:10px 6px;}}
.metrics .item b{{display:block;font-size:17px;margin:4px 0;color:#8e44ad;}}
.metrics .item span{{font-weight:bold;font-size:13px;}}
.metrics .item small{{color:#6b7480;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
table{{border-collapse:collapse;margin:14px 0;font-size:13px;}}
th,td{{border:1px solid #d6dae1;padding:4px 10px;text-align:center;}}
th{{background:#f3f5f8;}}
</style></head><body>
<h2>analysis_009 — LLT(d=60) 扩散指标对沪深300 的牛熊划分</h2>
<div class="note">微观（研报二）：个股 LLT(60) 切线斜率&gt;0 = 该股多头；宏观（研报一）：当日严格沪深300成分
多头占比（总市值加权）= 扩散指标 D → 快线 MA80 → 慢线 MA35（快线再平滑）；<b>快&gt;慢 = 指数多头（红），
快&lt;慢 = 空头（绿）</b>。⚠ 前瞻检验显示该划分为<b>反向信号</b>（多头日前瞻 60d 年化 -2.1% vs 空头日 +10.0%），
本图仅呈现划分形态本身。</div>
<div class="metrics">{tiles}</div>
{fig.to_html(full_html=False, include_plotlyjs=False, div_id='fig')}
<h3>划分时段明细（市值加权 80/35 主口径，{len(segs)} 段）</h3>
<table><tr><th>#</th><th>开始</th><th>结束</th><th>状态</th><th>交易日数</th></tr>{seg_rows}</table>
</body></html>"""
(HERE / "result_view.html").write_text(html, encoding="utf-8")
print(f"result_view.html 已生成（{len(segs)} 段）")
