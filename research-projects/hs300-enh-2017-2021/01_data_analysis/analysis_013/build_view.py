"""analysis_013 可视化 — 每标的独立一张图（result_view.html）。

每图两行：
  上：全史收盘价 + 逐日滚动压力线 R（红虚）/支撑线 S（绿虚）+ 突破标记
      （忠实口径=金色▲，因果口径=灰色○；悬停看形态标签）
  下：最近 250 交易日 + 当下(末日) 120 日窗口内实际画出的 R/S 线段（由斜率+末端值重建）
      + 参与回归的局部极值点（H●红 / L●绿）
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "shared"))
from quantreg_sr_algo import DEFAULT_PARAMS, fit_window, local_extrema  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = {"688981.SH": ("中芯国际 688981", "smic"),
           "001979.SZ": ("招商蛇口 001979", "shekou"),
           "600519.SH": ("贵州茅台 600519", "gzmt")}
warnings.filterwarnings("ignore")

BLUE, RED, GREEN, GOLD, GRAY = "#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e", "#a0aec0"
P = DEFAULT_PARAMS
VIEW_START = "2024-01-01"     # 主图展示区间（用户 09-09 指定：全史太长看不清，改 2024 至今）


def last_window_segment(close: pd.Series):
    """末日 120 日窗口：返回 (窗口日期, R线段价, S线段价, 高点/低点 (date,price))。"""
    win = close.iloc[-P["N"]:].to_numpy(float)
    y = win / win[0] * 100.0
    r = fit_window(win, causal=False)
    hi, lo = local_extrema(y, P["w"], causal=False)
    seg_x = np.arange(P["N"], dtype=float)
    b0r = (r["R"] / win[0] * 100.0) - r["p1"] * (P["N"] - 1)   # 归一截距重建
    b0s = (r["S"] / win[0] * 100.0) - r["p2"] * (P["N"] - 1)
    dates = close.index[-P["N"]:]
    R_seg = (b0r + r["p1"] * seg_x) / 100.0 * win[0]
    S_seg = (b0s + r["p2"] * seg_x) / 100.0 * win[0]
    return dates, R_seg, S_seg, r, dates[hi], y[hi] / 100 * win[0], dates[lo], y[lo] / 100 * win[0]


def build_figure(sym: str, title: str, csv_name: str) -> go.Figure:
    full = pd.read_csv(HERE / f"{csv_name}_lines.csv", index_col=0, parse_dates=True)
    d = full[full.index >= VIEW_START]          # 展示 2024 至今（线的计算仍用全史滚动）
    fig = make_subplots(rows=2, cols=1, shared_xaxes=False, row_heights=[0.62, 0.38],
                        vertical_spacing=0.06,
                        subplot_titles=(f"滚动压力线/支撑线（N={P['N']}, w={P['w']}, τ={P['tau_r']}/{P['tau_s']}）——{VIEW_START} 至今",
                                        "当下窗口：末日 120 日实际拟合线段 + 局部极值点"))
    # ── 上：全史 ──
    fig.add_trace(go.Scatter(x=d.index, y=d["close"], name="收盘价(后复权)", line=dict(color=BLUE, width=1.2)), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["R"], name="压力线 R(t)", line=dict(color=RED, width=1.1, dash="dash")), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["S"], name="支撑线 S(t)", line=dict(color=GREEN, width=1.1, dash="dash")), 1, 1)
    bf = d[d["breakout_f"]]
    fig.add_trace(go.Scatter(
        x=bf.index, y=bf["close"], mode="markers", name=f"突破(忠实) n={int(d['breakout_f'].sum())}",
        marker=dict(symbol="triangle-up", size=9, color=GOLD, line=dict(width=1, color="#744210")),
        text=[f"{i.date()} {r.dur}/{r.chan}<br>close {r.close:.1f} > R {r.R:.1f}"
              for i, r in bf.iterrows()], hoverinfo="text"), 1, 1)
    bc = d[d["breakout_c"]]
    fig.add_trace(go.Scatter(
        x=bc.index, y=bc["close"], mode="markers", name=f"突破(因果) n={int(d['breakout_c'].sum())}",
        marker=dict(symbol="circle", size=5, color=GRAY, opacity=0.6),
        text=[f"{i.date()} 因果口径突破" for i, r in bc.iterrows()], hoverinfo="text"), 1, 1)
    # ── 下：末日窗口 ──
    dates, R_seg, S_seg, r, hd, hp, ld, lp = last_window_segment(d["close"])
    w = d.loc[d.index >= dates[0]]
    fig.add_trace(go.Scatter(x=w.index, y=w["close"], name="收盘(近窗)", showlegend=False,
                             line=dict(color=BLUE, width=1.4)), 2, 1)
    fig.add_trace(go.Scatter(x=dates, y=R_seg, name=f"压力线段 p1={r['p1']:+.4f}", line=dict(color=RED, width=2)), 2, 1)
    fig.add_trace(go.Scatter(x=dates, y=S_seg, name=f"支撑线段 p2={r['p2']:+.4f}", line=dict(color=GREEN, width=2)), 2, 1)
    fig.add_trace(go.Scatter(x=hd, y=hp, mode="markers", name="局部高点(回归点集)",
                             marker=dict(symbol="circle", size=7, color=RED, opacity=0.75)), 2, 1)
    fig.add_trace(go.Scatter(x=ld, y=lp, mode="markers", name="局部低点(回归点集)",
                             marker=dict(symbol="circle", size=7, color=GREEN, opacity=0.75)), 2, 1)
    fig.update_layout(
        height=760, template="plotly_white",
        title=dict(text=f"analysis_013 · {title} · 分位数回归压力/支撑线", x=0.5,
                   font=dict(size=16)),
        legend=dict(orientation="h", y=1.04, x=0.5, xanchor="center", font=dict(size=11)),
        hovermode="x unified", margin=dict(l=60, r=30, t=90, b=40))
    fig.update_yaxes(title_text="价格(后复权)")
    return fig


def main():
    figs = [build_figure(sym, t, c) for sym, (t, c) in TARGETS.items()]
    parts = [f.to_html(full_html=False, include_plotlyjs=("cdn" if i == 0 else False))
             for i, f in enumerate(figs)]
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>analysis_013 · 分位数回归阻力线（三标的）</title></head>
<body style="font-family:system-ui;max-width:1280px;margin:auto;background:#fff">
<h2 style="text-align:center">analysis_013 · quantreg_sr_algo 压力/支撑线可视化</h2>
<p style="text-align:center;color:#555">Lang(2012)+渤海证券路线：局部极值(w=5) → N=120 分位回归(τ=0.9/0.1)。
上=滚动线值（展示 2024 至今，线的计算仍用全史前 120 日滚动窗口）；下=末日窗口实际线段与回归点集。金色▲=忠实口径突破（含末端极值确认），灰色○=因果口径突破。</p>
{''.join(f'<div>{p}</div><hr>' for p in parts)}
</body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出:", HERE / "result_view.html")


if __name__ == "__main__":
    main()
