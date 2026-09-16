"""诊断图 — 对称三角形唯一一笔交易的 120 日窗口（用户指定检查项）。

画：窗口内 close + 因果口径局部高/低点（转折点）+ 拟合的 R/S 线段（现场 fit_window，
非重建）+ 信号日突破点。用户核对"压力线是否贯穿转折高点"。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "shared"))
from quantreg_sr_algo import DEFAULT_PARAMS as P, fit_window, local_extrema  # noqa: E402

warnings.filterwarnings("ignore")
BLUE, RED, GREEN, GOLD = "#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e"


def main():
    idx = pd.read_parquet(HERE.parent / "update2_pattern_backtests" / "hs300_index.parquet").set_index("date")
    tr = pd.read_csv(HERE.parent / "update2_pattern_backtests" / "runs" / "dur_对称三角形" / "trades.csv",
                     parse_dates=["entry_date"])
    e = tr["entry_date"].iloc[0]
    t = idx.index.get_loc(e) - 1
    win = idx["close"].iloc[t - P["N"] + 1:t + 1]
    dates = win.index
    w = win.to_numpy(float)

    r = fit_window(w, causal=True)
    y = w / w[0] * 100.0
    hi, lo = local_extrema(y, P["w"], causal=True)
    x = np.arange(P["N"], dtype=float)
    sr, ss = r["p1"] * w[0] / 100, r["p2"] * w[0] / 100       # 价格斜率
    b0r, b0s = r["R"] - sr * (P["N"] - 1), r["S"] - ss * (P["N"] - 1)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=w, name="沪深300 收盘", line=dict(color=BLUE, width=1.6)))
    fig.add_trace(go.Scatter(x=dates[hi], y=w[hi], mode="markers", name=f"局部高点×{len(hi)}（转折点）",
                             marker=dict(symbol="circle", size=10, color=RED, opacity=0.85)))
    fig.add_trace(go.Scatter(x=dates[lo], y=w[lo], mode="markers", name=f"局部低点×{len(lo)}（转折点）",
                             marker=dict(symbol="circle", size=10, color=GREEN, opacity=0.85)))
    fig.add_trace(go.Scatter(x=dates, y=b0r + sr * x, name=f"压力线 τ=0.9（p1={r['p1']:+.4f} → {sr:+.2f}点/日）",
                             line=dict(color=RED, width=2.5)))
    fig.add_trace(go.Scatter(x=dates, y=b0s + ss * x, name=f"支撑线 τ=0.1（p2={r['p2']:+.4f} → {ss:+.2f}点/日）",
                             line=dict(color=GREEN, width=2.5, dash="dash")))
    fig.add_trace(go.Scatter(x=[dates[-1]], y=[w[-1]], mode="markers+text", name="信号日收盘（突破）",
                             marker=dict(symbol="triangle-up", size=14, color=GOLD,
                                         line=dict(width=2, color="#1a202c")),
                             text=[f"close {w[-1]:.0f} > R {r['R']:.0f}"], textposition="top right"))
    fig.add_trace(go.Scatter(x=[dates[hi[0]]], y=[w[hi[0]]], mode="markers+text",
                             name="离群高点（钉住压力线左端）", showlegend=True,
                             marker=dict(symbol="star", size=14, color="#744210"),
                             text=[f"{w[hi[0]]:.0f} 股灾前高"], textposition="middle right"))
    fig.update_layout(
        height=620, template="plotly_white", hovermode="x unified",
        title=dict(text="诊断 · 对称三角形唯一一笔：120 日窗口 2015-12-29 ~ 2016-06-27（含 2016-01 熔断）", x=0.5),
        yaxis_title="沪深300 点位", legend=dict(orientation="h", y=-0.18))
    html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    (HERE / "diag_symtriangle.html").write_text(
        f"<!DOCTYPE html><html><head><meta charset='utf-8'></head><body"
        f" style='font-family:system-ui;max-width:1280px;margin:auto'>{html}"
        f"<p style='color:#555;font-size:13px'>红色圆点=局部高点（w=5 因果口径），绿色=局部低点；实线=τ=0.9 压力线，"
        f"虚线=τ=0.1 支撑线。压力线左端被 2015-12-30 离群高点（{w[hi[0]]:.0f}）钉住，右端触 2016-06-03 高点后下斜至 R={r['R']:.0f}，"
        f"信号日收盘 {w[-1]:.0f} 在线上方突破。窗口起点价 {w[0]:.0f}（熔断前），故线段左端视觉上'在天上'——"
        f"这是窗口含股灾的真实结果，非画图错误。</p></body></html>", encoding="utf-8")
    print("写出:", HERE / "diag_symtriangle.html")


if __name__ == "__main__":
    main()
