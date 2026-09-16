"""6 标的支撑带可视化（v4 对称逻辑）——验证支撑带生命周期。

蓝实线 = 活支撑带（画到数据末日）；浅灰点线 = 死支撑带（截止死亡日）；黑线=收盘。
规则对称：死 = 累计90日 close<line×0.90 或 单日 close<line×0.70。
数据复用各 *_daily.csv + *_v4_bands.csv（含 kind=S）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
TAGS = [("smic", "中芯国际 688981"), ("shekou", "招商蛇口 001979"),
        ("zjjc", "中际旭创 300308"), ("ndsd", "宁德时代 300750"),
        ("gzmt", "贵州茅台 600519"), ("zgpa", "中国平安 601318")]

htmls = []
for tag, title in TAGS:
    g = pd.read_csv(HERE / f"{tag}_daily.csv")
    g["date"] = pd.to_datetime(g["date"])
    b = pd.read_csv(HERE / f"{tag}_v4_bands.csv", encoding="utf-8-sig")
    b = b[b["kind"] == "S"]                      # 只取支撑带
    for c in ("d0", "dead_date"):
        b[c] = pd.to_datetime(b[c])
    last_date = g["date"].iloc[-1]
    n_alive = int((~b["dead"]).sum())
    n_dead = int(b["dead"].sum())

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=g["date"], y=g["close"], name="close",
                             line=dict(color="#2c3e50", width=1.0)))
    for _, bb in b.iterrows():
        x0 = bb["d0"]
        if bb["dead"]:
            x1, col, dash = bb["dead_date"], "#bdc3c7", "dot"
        else:
            x1, col, dash = last_date, "#3498db", "solid"
        fig.add_trace(go.Scatter(
            x=[x0, x1], y=[bb["line"], bb["line"]], mode="lines",
            line=dict(color=col, width=2.5, dash=dash),
            hovertemplate=(f"line={bb['line']:.2f} pts={bb['count']}<br>"
                           f"{x0.date()} → {x1.date()}"),
            showlegend=False))
    fig.update_layout(template="plotly_white", height=520,
                      title=f"{title} — v4 SUPPORT bands (blue alive, grey dead; "
                            f"alive {n_alive}, dead {n_dead})",
                      margin=dict(l=50, r=20, t=55, b=30))
    htmls.append(fig.to_html(full_html=False, include_plotlyjs=False, div_id=f"fig_{tag}"))

html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>v4 support bands</title>'
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body>'
        '<h2>analysis_012 — v4 支撑带生命周期（对称规则，6 标的）</h2>'
        '<div style="color:#6b7480;font-size:13px">对称死亡规则：累计90日 close&lt;line×0.90 '
        '或 单日 close&lt;line×0.70。蓝实线=活支撑（到末日）；浅灰点线=死支撑（截止死亡日）。</div>'
        + "".join(htmls) + '</body></html>')
(HERE / "v4_support_view.html").write_text(html, encoding="utf-8")
print("v4_support_view.html 已生成")
