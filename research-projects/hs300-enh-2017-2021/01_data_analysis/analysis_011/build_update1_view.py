"""analysis_011 更新一 — NAV 对比视图（decile≥4 过滤 vs A_v2 原版）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
A2_NAV = PROJ / "02_strategy_iteration/strategy_006/ab_tests/A_v2/backtest_logs/nav_from_trades.csv"

n1 = pd.read_csv(A2_NAV)
n1["date"] = pd.to_datetime(n1["date"])
n2 = pd.read_csv(HERE / "gates_decile4/nav_from_trades.csv")
n2["date"] = pd.to_datetime(n2["date"])

fig = go.Figure()
fig.add_trace(go.Scatter(x=n1["date"], y=n1["nav"], name="A_v2 原版",
                         line=dict(color="#95a5a6", width=1.5)))
fig.add_trace(go.Scatter(x=n2["date"], y=n2["nav"], name="decile>=4 过滤",
                         line=dict(color="#c0392b", width=1.8)))
fig.update_layout(template="plotly_white", height=500,
                  title="analysis_011 更新一 — decile≥4 过滤 vs A_v2（NAV, trades 口径）",
                  hovermode="x unified", margin=dict(l=50, r=20, t=60, b=30),
                  legend=dict(orientation="h", y=1.05))

html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<title>analysis_011 u1</title>'
        '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body>'
        '<h2>analysis_011 更新一 — 十分位≥4 过滤（剔除 1~3 档负期望区）</h2>'
        '<div style="color:#6b7480;font-size:13px">剔除 99 笔合计 -175.7pp（均值 -1.77%/笔）'
        '→ 总收益 +109.7%→+130.3%，Sharpe 0.37→0.47，maxDD -41.5%→-35.9%。'
        '静态筛选不重排坑位（保守估计）。</div>'
        + fig.to_html(full_html=False, include_plotlyjs=False) + '</body></html>')
(HERE / "update1_view.html").write_text(html, encoding="utf-8")
print("update1_view.html 已生成 | 末值 raw %.2f / decile≥4 %.2f"
      % (n1["nav"].iloc[-1], n2["nav"].iloc[-1]))
