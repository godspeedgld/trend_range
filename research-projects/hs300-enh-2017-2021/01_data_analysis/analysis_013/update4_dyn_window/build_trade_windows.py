"""更新四·补充 — 逐笔突破窗口画册（用户指定：每个形态的每次突破，把窗口压力/支撑线画出来）。

产物 trade_windows/{run_id}.html（12 个）+ index.html：
每笔交易一张子图：信号日 v2 实际窗口（win_len 可 <120=截断）的收盘价、压力线段（红实）、
支撑线段（绿虚）、参与回归的因果局部高/低点（圆点）、突破日收盘 ▲。
线段由当日 p1/R_t×win0 重建（与引擎信号同源）；转折点在窗口上现场重算（与 v2 拟合一致）。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
U2 = HERE.parent / "update2_pattern_backtests"
sys.path.insert(0, str(HERE.parents[2] / "shared"))
from quantreg_sr_algo import local_extrema  # noqa: E402

warnings.filterwarnings("ignore")
BLUE, RED, GREEN, GOLD = "#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e"


def main():
    idx = pd.read_parquet(U2 / "hs300_index.parquet").set_index("date")
    sig = pd.read_parquet(HERE / "signals_v2.parquet")
    tb = pd.read_csv(HERE / "summary_v2_only.csv")
    outd = HERE / "trade_windows"
    outd.mkdir(exist_ok=True)

    for _, row in tb.iterrows():
        run_id, name = row["run_id"], row["形态"]
        tr = pd.read_csv(HERE / "runs" / run_id / "trades.csv", parse_dates=["entry_date"])
        n = len(tr)
        ncol = 3 if n > 2 else n
        nrow = int(np.ceil(n / ncol))
        titles, metas = [], []
        for k, e in enumerate(tr["entry_date"]):
            t = idx.index.get_loc(e) - 1
            day = sig.loc[idx.index[t]]
            titles.append(f"#{k+1} {e.date()} {tr['ret_pct'].iloc[k]:+.1f}% "
                          f"窗{int(day['win_len'])}{'✂' if bool(day['truncated']) else ''}")
            metas.append((t, day))
        titles += [""] * (nrow * ncol - n)
        fig = make_subplots(rows=nrow, cols=ncol, subplot_titles=titles,
                            horizontal_spacing=0.02,
                            vertical_spacing=min(0.06, 0.9 / max(nrow, 2)))
        for k, (t, day) in enumerate(metas):
            r_, c_ = divmod(k, ncol)
            n_w, win0 = int(day["win_len"]), float(day["win0"])
            win = idx["close"].iloc[t - n_w + 1:t + 1].to_numpy(float)
            dw = idx.index[t - n_w + 1:t + 1]
            x = np.arange(n_w, dtype=float)
            sr, ss = day["p1"] * win0 / 100, day["p2"] * win0 / 100
            y = win / win0 * 100
            hi, lo = local_extrema(y, 5, causal=True)
            fig.add_trace(go.Scatter(x=dw, y=win, line=dict(color=BLUE, width=1),
                                     showlegend=False, hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.add_trace(go.Scatter(x=dw, y=day["R"] - sr * (n_w - 1) + sr * x,
                                     line=dict(color=RED, width=2), showlegend=False,
                                     hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.add_trace(go.Scatter(x=dw, y=day["S"] - ss * (n_w - 1) + ss * x,
                                     line=dict(color=GREEN, width=2, dash="dash"),
                                     showlegend=False, hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.add_trace(go.Scatter(x=dw[hi], y=win[hi], mode="markers",
                                     marker=dict(size=6, color=RED, opacity=0.8),
                                     showlegend=False, hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.add_trace(go.Scatter(x=dw[lo], y=win[lo], mode="markers",
                                     marker=dict(size=6, color=GREEN, opacity=0.8),
                                     showlegend=False, hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.add_trace(go.Scatter(x=[dw[-1]], y=[win[-1]], mode="markers",
                                     marker=dict(symbol="triangle-up", size=11, color=GOLD,
                                                 line=dict(width=1, color="#1a202c")),
                                     showlegend=False, hoverinfo="skip"), r_ + 1, c_ + 1)
            fig.update_xaxes(showticklabels=False, row=r_ + 1, col=c_ + 1)
            fig.update_yaxes(showticklabels=False, row=r_ + 1, col=c_ + 1)
        height = max(360, nrow * 230)
        fig.update_layout(height=height, template="plotly_white",
                          title=dict(text=f"{name}（{run_id}）· {n} 笔突破窗口  "
                                          f"红实=压力线 绿虚=支撑线 圆点=转折点 ▲=突破", x=0.5,
                                     font=dict(size=14)),
                          margin=dict(l=20, r=20, t=60, b=20))
        fig.write_html(outd / f"{run_id}.html", include_plotlyjs="cdn")
        print(f"{run_id}: {n} 笔 → {run_id}.html")

    # 索引页
    rows_html = "".join(
        f"<tr><td><a href='{r.run_id}.html'>{r.形态}</a></td><td>{int(r.n_trades)}</td>"
        f"<td>{r.total_return_pct:+.1f}%</td><td>{r.sharpe}</td><td>{r.maxDD_pct}%</td></tr>"
        for _, r in tb.iterrows())
    (outd / "index.html").write_text(f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>更新四·逐笔窗口画册</title><style>body{{font-family:system-ui;max-width:900px;margin:auto}}
td,th{{padding:5px 16px;text-align:right;border-bottom:1px solid #ddd}}td:first-child{{text-align:left}}</style>
</head><body><h2>更新四 · 每形态每笔突破的窗口画册（v2 动态窗）</h2>
<table><tr><th>形态（点击进入）</th><th>笔数</th><th>总收益</th><th>Sharpe</th><th>maxDD</th></tr>
{rows_html}</table>
<p style="color:#555;font-size:13px">每笔一张子图：窗口收盘（蓝）、压力线（红实）、支撑线（绿虚）、
参与回归的因果转折点（圆点）、突破日收盘（▲）。窗长 <120 = 发生过 LOO 截断（✂）。</p></body></html>""",
        encoding="utf-8")
    print("index.html 写出")


if __name__ == "__main__":
    main()
