"""v4 收益率分布可视化：直方(log)+QQ图+峰度/尾厚 诊断。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy import stats

HERE = Path(__file__).resolve().parent
d = pd.read_parquet(HERE.parent / "detail_v4.parquet")
d = d[d["result"].isin(["success", "fail"])].copy()
r = d["ret"].dropna().values
r_pct = r * 100

# ── 拟合：正态 + t(df=4 近似) ──
mu, sd = r.mean(), r.std()
xs = np.linspace(r.min(), r.max(), 500)
# 用 log 显示，仅右侧（左尾集中在 -30%~0）
bins = np.arange(-35, 100, 5)      # -35~100 桶，>100 并入尾部
hist, edges = np.histogram(r_pct, bins=list(bins) + [np.inf])
centers = (np.array(bins) + np.concatenate([bins[1:], [100]])) / 2
df_t = max(3.5, 6 / stats.kurtosis(r) + 4)

fig = make_subplots(rows=2, cols=2, subplot_titles=(
    "Ret distribution (linear-y, clipped -35~+100%, +tail)",
    "Ret distribution (log-y, zoom -30~+60%)",
    "QQ vs normal (red=norm, heavy tail visible)",
    "Tail: share of trades above threshold (log-y)"))

# 1) 线性直方
fig.add_trace(go.Bar(x=centers[:-1], y=hist[:-1], name="count", marker_color="#2980b9",
                     opacity=0.8), 1, 1)
tail = hist[-1]
fig.add_trace(go.Scatter(x=[100], y=[tail], mode="markers",
                         marker=dict(size=12, color="#c0392b"),
                         name=f">100%: {tail} ({tail/len(r_pct)*100:.1f}%)"), 1, 1)

# 2) log y 直方（放大 -30~60）
mask = (r_pct > -30) & (r_pct < 60)
b2 = np.arange(-30, 61, 3)
h2, _ = np.histogram(r_pct[mask], bins=b2)
c2 = (b2[:-1] + b2[1:]) / 2
fig.add_trace(go.Bar(x=c2, y=h2, name="count (log y)", marker_color="#8e44ad"), 1, 2)
fig.update_yaxes(type="log", row=1, col=2)

# 3) QQ vs 正态
os, or_ = np.sort(r), stats.norm.ppf(np.linspace(0.001, 0.999, len(r)))
fig.add_trace(go.Scatter(x=or_, y=os, mode="markers", marker=dict(size=2, color="#2c3e50"),
                         name="QQ"), 2, 1)
xx = np.linspace(-0.3, 0.3, 50)
fig.add_trace(go.Scatter(x=xx, y=xx, mode="lines", line=dict(color="#c0392b", width=1.5),
                         name="y=x (normal)"), 2, 1)

# 4) 尾部阈值
thr = [0.1, 0.2, 0.5, 1.0, 2.0, 3.0]
shares = [np.mean(r > t) * 100 for t in thr]
fig.add_trace(go.Scatter(x=thr, y=shares, mode="lines+markers",
                         marker=dict(size=9, color="#27ae60"),
                         text=[f"{s:.2f}%" for s in shares]), 2, 2)
fig.update_yaxes(type="log", row=2, col=2)

fig.update_layout(template="plotly_white", height=820, hovermode="x unified",
                  margin=dict(l=50, r=30, t=70, b=40), legend=dict(orientation="h", y=1.05))

summary = (f"n={len(r)} | mean {r.mean()*100:+.1f}% | median {np.median(r)*100:+.1f}% | "
           f"std {r.std()*100:.0f}% | skew {stats.skew(r):.1f} | excess kurt {stats.kurtosis(r):.0f} | "
           f"|z|>3: {np.mean(np.abs(r-r.mean())>3*r.std())*100:.2f}% (norm 0.27%) | t-df≈{df_t:.1f}")
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v4 return dist</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.note{{color:#6b7480;font-size:14px;margin:8px 0 16px;}}</style></head><body>
<h2>analysis_012 — v4 交易收益率分布形态</h2>
<div class="note">{summary}</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "dist_view.html").write_text(html, encoding="utf-8")
print("dist_view.html 已生成")
