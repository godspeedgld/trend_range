"""v4 生命周期可视化：价格 + 活带红线段 + 死带灰线段（终于死亡日）+ 突破事件标记。

线段范围：d0（带内最早转折点）→ d_born（带最后合并日，活带）/ d_dead（死带）。
红线 = 活带（当前仍参与合并/突破）；灰线 = 死亡带（收盘>hi×2 持续60日退役）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
NAMES = {"smic": "SMIC 688981", "shekou": "Shekou 001979"}

figs_html = []
for tag, title in NAMES.items():
    g = pd.read_csv(HERE / f"{tag}_daily.csv")
    g["date"] = pd.to_datetime(g["date"])
    bands = pd.read_csv(HERE / f"{tag}_v4_bands.csv", encoding="utf-8-sig")
    for c in ("d0", "d_born", "dead_date"):
        bands[c] = pd.to_datetime(bands[c])

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=g["date"], y=g["close"], name="close",
                             line=dict(color="#2c3e50", width=1.1)))
    last_date = g["date"].iloc[-1]
    for _, b in bands.iterrows():
        if b["kind"] != "R":                    # 只显示阻力带（R）
            continue
        x0 = b["d0"]
        if b["dead"]:
            x1 = b["dead_date"]
            col, lab, dash = "#95a5a6", "DEAD R", "dot"
        else:
            x1 = last_date                    # 活带 → 画到数据末日（仍有效）
            col, lab, dash = "#c0392b", "ALIVE R", "solid"
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[b["line"], b["line"]],
            mode="lines", line=dict(color=col, width=2.5, dash=dash),
            hovertemplate=(f"{lab} line={b['line']:.2f} pts={b['count']}<br>"
                           f"{b['d0'].date()} → {pd.Timestamp(x1).date()}"),
            showlegend=False))
    ev = HERE / f"{tag}_v4_events.csv"
    if ev.exists():
        e = pd.read_csv(ev, encoding="utf-8-sig")
        e["date"] = pd.to_datetime(e["date"])
        fig.add_trace(go.Scatter(x=e["date"], y=e["close"], name="break_up event",
                                 mode="markers", marker=dict(symbol="triangle-up",
                                 size=8, color="#f39c12")))
    fig.update_layout(template="plotly_white", height=560,
                      title=f"{title} — v4 resistance bands (red=alive segment, grey=dead dotted, "
                            "ends at death date; gold=break events)",
                      margin=dict(l=50, r=20, t=60, b=30),
                      legend=dict(orientation="h", y=1.06))
    figs_html.append(fig.to_html(full_html=False, include_plotlyjs=False,
                                 div_id=f"fig_{tag}"))

html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>v4 lifecycle</title>'
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body>'
        '<h2>analysis_012 — v4 阻力带生命周期测试（死亡：收盘>hi×2 持续60日）</h2>'
        '<div style="color:#6b7480;font-size:13px">仅显示阻力带(R)。红实线=活阻力带（d0 最早'
        '转折点→born 最后合并日）；灰点线=死亡阻力带（→死亡日截止）。金三角=突破事件。</div>'
        + figs_html[0] + figs_html[1] + '</body></html>')
(HERE / "v4_view.html").write_text(html, encoding="utf-8")
print("v4_view.html 已生成")
