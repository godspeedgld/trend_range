"""analysis_010 — result_view.html：中芯国际价格+LLT+牛熊背景+三版买卖点+三版净值。

三版：raw=纯 v3 突破 / llt=牛市确认闸门（生成版）/ flip=LLT 转牛开仓（更新一，主展示）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "shared"))
from llt60_precompute import _llt                    # noqa: E402

df = pd.read_csv(HERE / "smic_daily.csv")
df["date"] = pd.to_datetime(df["date"])
df = df.set_index("date")
llt = _llt(df["close"], 60)
llt_up = (llt.diff() > 0).fillna(False)

T = {}
for tag in ("raw", "llt", "flip"):
    t = pd.read_csv(HERE / f"trades_{tag}.csv", encoding="utf-8-sig")
    for c in ("entry_date", "exit_date"):
        t[c] = pd.to_datetime(t[c])
    T[tag] = t
NAV = {tag: pd.read_csv(HERE / f"nav_{tag}.csv", index_col=0, parse_dates=True)
       for tag in ("raw", "llt", "flip")}

fig = make_subplots(rows=3, cols=1, row_heights=[0.46, 0.18, 0.36], shared_xaxes=True,
                    vertical_spacing=0.05,
                    subplot_titles=("SMIC 688981 close + LLT(60) + regime background — "
                                    "flip entries (gold triangles) vs raw (blue) vs gate (grey)",
                                    "LLT(60) trendline",
                                    "NAV: raw vs gate vs flip (update-1)"))

# 背景：LLT 牛=浅红
chg = (llt_up != llt_up.shift(1)).fillna(True)
start = 0
for i in range(1, len(llt_up) + 1):
    if i == len(llt_up) or chg.iloc[i]:
        if bool(llt_up.iloc[start]):
            fig.add_shape(type="rect", x0=llt_up.index[start], x1=llt_up.index[i - 1],
                          y0=0, y1=1, xref="x", yref="y domain",
                          fillcolor="rgba(255,120,120,0.20)", layer="below", line_width=0)
        start = i

fig.add_trace(go.Scatter(x=df.index, y=df["close"], name="close",
                         line=dict(color="#2c3e50", width=1.2)), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=llt, name="LLT(60)",
                         line=dict(color="#c0392b", width=1.4)), row=1, col=1)
# 三版买卖点
fig.add_trace(go.Scatter(x=T["raw"]["entry_date"], y=T["raw"]["entry_px"], name="raw entry",
                         mode="markers", marker=dict(symbol="triangle-up", size=10,
                         color="#2980b9")), row=1, col=1)
fig.add_trace(go.Scatter(x=T["raw"]["exit_date"], y=T["raw"]["exit_px"], name="raw exit",
                         mode="markers", marker=dict(symbol="triangle-down", size=10,
                         color="#2980b9", opacity=0.55)), row=1, col=1)
fig.add_trace(go.Scatter(x=T["llt"]["entry_date"], y=T["llt"]["entry_px"], name="gate entry",
                         mode="markers", marker=dict(symbol="x", size=9,
                         color="#7f8c8d")), row=1, col=1)
fig.add_trace(go.Scatter(x=T["flip"]["entry_date"], y=T["flip"]["entry_px"],
                         name="flip entry (update-1)", mode="markers",
                         marker=dict(symbol="triangle-up", size=11, color="#f39c12")),
              row=1, col=1)
fig.add_trace(go.Scatter(x=T["flip"]["exit_date"], y=T["flip"]["exit_px"],
                         name="flip exit", mode="markers",
                         marker=dict(symbol="triangle-down", size=11, color="#f39c12",
                                     opacity=0.6)), row=1, col=1)
fig.add_trace(go.Scatter(x=llt.index, y=llt, name="LLT(60)", showlegend=False,
                         line=dict(color="#c0392b", width=1.4)), row=2, col=1)
# NAV 三线
for tag, name, color, w in (("raw", "raw (v3 breakout only)", "#2980b9", 1.8),
                            ("flip", "flip: LLT turn-bull entry (update-1)", "#f39c12", 1.6),
                            ("llt", "gate: LLT-bull confirm (gen)", "#7f8c8d", 1.2)):
    fig.add_trace(go.Scatter(x=NAV[tag].index, y=NAV[tag]["nav"], name=name,
                             line=dict(color=color, width=w)), row=3, col=1)

fig.update_layout(template="plotly_white", height=900, hovermode="x unified",
                  margin=dict(l=50, r=20, t=60, b=30),
                  legend=dict(orientation="h", y=1.04))
fig.write_html(str(HERE / "result_view.html"))
print("result_view.html 已生成 | NAV 末值 raw %.2f / flip %.2f / gate %.2f"
      % (NAV["raw"]["nav"].iloc[-1], NAV["flip"]["nav"].iloc[-1],
         NAV["llt"]["nav"].iloc[-1]))
