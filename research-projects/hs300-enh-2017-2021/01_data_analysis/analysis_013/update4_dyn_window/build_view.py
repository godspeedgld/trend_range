"""更新四可视化（与更新二/更新三同款）：
  1) summary_view.html —— A/B 统计表（v1 固定窗 vs v2 动态窗并排）+ v2 净值曲线统一图（基准=沪深300）
  2) breakout_lines_view.html —— 双轴图：净值（左）+ 各形态突破当时的 R/S 线段（右，按实际
     win_len 重建），legendgroup 整组开关，同更新三
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
U2 = HERE.parent / "update2_pattern_backtests"
PALETTE = ["#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e", "#805ad5", "#dd6b20",
           "#319795", "#b83280", "#4a5568", "#38b2ac", "#c53030", "#718096"]


def bench(idx: pd.DataFrame):
    r = idx["close"].pct_change().fillna(0)
    nav = (1 + r).cumprod()
    return nav, {"总收益%": round((nav.iloc[-1] - 1) * 100, 1),
                 "年化%": round((nav.iloc[-1] ** (252 / len(r)) - 1) * 100, 2),
                 "Sharpe": round(r.mean() / r.std() * np.sqrt(252), 2),
                 "maxDD%": round((nav / nav.cummax() - 1).min() * 100, 1)}


def summary_view():
    ab = pd.read_csv(HERE / "summary_table.csv")
    show = ab[["形态", "n_trades_v2", "total_return_pct_v2", "annual_pct", "sharpe_v2",
               "maxDD_pct_v2", "win_rate_pct_v2", "n_trades_v1", "total_return_pct_v1",
               "sharpe_v1", "maxDD_pct_v1", "win_rate_pct_v1"]]
    show.columns = ["形态", "笔数v2", "总收益%v2", "年化%v2", "Sharpe v2", "maxDD%v2", "胜率%v2",
                    "笔数v1", "总收益%v1", "Sharpe v1", "maxDD%v1", "胜率%v1"]
    idx = pd.read_parquet(U2 / "hs300_index.parquet").set_index("date")
    bnav, bs = bench(idx)
    bench_row = {c: "—" for c in show.columns}
    bench_row.update({"形态": "沪深300买入持有", "总收益%v2": bs["总收益%"], "年化%v2": bs["年化%"],
                      "Sharpe v2": bs["Sharpe"], "maxDD%v2": bs["maxDD%"]})
    tbl = pd.concat([show, pd.DataFrame([bench_row])], ignore_index=True)\
        .to_html(index=False, border=0, classes="tbl", na_rep="—", float_format=lambda x: f"{x:g}")

    fig = go.Figure()
    tb2 = pd.read_csv(HERE / "summary_v2_only.csv")
    for i, row in tb2.iterrows():
        nav = pd.read_csv(HERE / "runs" / row["run_id"] / "nav.csv", parse_dates=["date"])
        fig.add_trace(go.Scatter(x=nav["date"], y=nav["nav"],
                                 name=f"{row['形态']}({int(row['n_trades'])}笔)",
                                 line=dict(color=PALETTE[i % 12], width=1.3)))
    fig.add_trace(go.Scatter(x=bnav.index, y=bnav, name="沪深300 买入持有",
                             line=dict(color="#1a202c", width=3)))
    fig.update_layout(height=620, template="plotly_white", hovermode="x unified",
                      title="更新四 · v2 动态窗口（LOO 离群截断）12 回测净值",
                      legend=dict(orientation="h", y=-0.15), yaxis_title="净值（起点=1）")
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>更新四汇总</title>
<style>body{{font-family:system-ui;max-width:1280px;margin:auto;background:#fff}}
.tbl{{border-collapse:collapse;font-size:12px;margin:14px 0}}
.tbl th,.tbl td{{padding:4px 10px;text-align:right;border-bottom:1px solid #e2e8f0}}
.tbl th:first-child,.tbl td:first-child{{text-align:left}}h2{{text-align:center}}</style></head><body>
<h2>analysis_013 更新四 · 动态窗口 v2 A/B（v1=固定120 / v2=LOO 截断动态窗）</h2>
<p style="color:#555;font-size:13px">机制：截断率 33.1%、win_len 中位 120（p10=90）、有效线日 2704 不减（N_min=60 兜底回退）。
交易规则同更新二（3×ATR 止损/止盈、满仓、单边 10bps）。</p>
{tbl}{fig.to_html(full_html=False, include_plotlyjs="cdn")}</body></html>"""
    (HERE / "summary_view.html").write_text(html, encoding="utf-8")
    print("写出:", HERE / "summary_view.html")


def lines_view():
    idx = pd.read_parquet(U2 / "hs300_index.parquet").set_index("date")
    sig = pd.read_parquet(HERE / "signals_v2.parquet")
    tb = pd.read_csv(HERE / "summary_v2_only.csv")
    fig = go.Figure()
    bnav = idx["close"] / idx["close"].iloc[0]
    fig.add_trace(go.Scatter(x=idx.index, y=bnav, name="沪深300 买入持有", legendgroup="bench",
                             line=dict(color="#1a202c", width=3)))
    for i, row in tb.iterrows():
        run_id, name, col = row["run_id"], row["形态"], PALETTE[i % 12]
        grp, hide = f"g{i}", run_id == "all_全部对照"
        vis = "legendonly" if hide else True
        nav = pd.read_csv(HERE / "runs" / run_id / "nav.csv", parse_dates=["date"])
        fig.add_trace(go.Scatter(x=nav["date"], y=nav["nav"], name=f"{name}({int(row['n_trades'])}笔)",
                                 legendgroup=grp, line=dict(color=col, width=1.3), visible=vis))
        tr = pd.read_csv(HERE / "runs" / run_id / "trades.csv", parse_dates=["entry_date"])
        xr, yr, xs, ys, xm, ym = [], [], [], [], [], []
        for e in tr["entry_date"]:
            t = idx.index.get_loc(e) - 1
            day = sig.loc[idx.index[t]]
            if not np.isfinite(day["R"]):
                continue
            n_w = int(day["win_len"])
            win0 = float(day["win0"])
            x = np.arange(n_win := n_w, dtype=float)
            sr, ss = day["p1"] * win0 / 100, day["p2"] * win0 / 100
            dw = idx.index[t - n_w + 1:t + 1]
            xr += list(dw) + [None]; yr += list(day["R"] - sr * (n_w - 1) + sr * x) + [None]
            xs += list(dw) + [None]; ys += list(day["S"] - ss * (n_w - 1) + ss * x) + [None]
            xm.append(dw[-1]); ym.append(day["close"])
        fig.add_trace(go.Scatter(x=xr, y=yr, legendgroup=grp, showlegend=False, visible=vis,
                                 line=dict(color=col, width=1.0), opacity=0.55, yaxis="y2", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xs, y=ys, legendgroup=grp, showlegend=False, visible=vis,
                                 line=dict(color=col, width=1.0, dash="dash"), opacity=0.45,
                                 yaxis="y2", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=xm, y=ym, legendgroup=grp, showlegend=False, visible=vis,
                                 mode="markers", yaxis="y2",
                                 marker=dict(symbol="triangle-up", size=8, color=col,
                                             line=dict(width=1, color="#1a202c")),
                                 text=[f"{d.date()} {name} 突破(win_len={int(sig.loc[d,'win_len'])})"
                                       for d in xm], hoverinfo="text"))
    fig.update_layout(
        height=760, template="plotly_white", hovermode="x unified",
        title=dict(text="更新四 · v2 净值 + 各形态突破当时的压力/支撑线（左轴净值，右轴点位）",
                   x=0.5, font=dict(size=15)),
        legend=dict(orientation="h", y=-0.12, font=dict(size=11)),
        yaxis=dict(title="净值（左）"), yaxis2=dict(title="沪深300 点位（右）", overlaying="y", side="right"),
        margin=dict(l=60, r=60, t=80, b=80))
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>更新四画线</title></head>
<body style="font-family:system-ui;max-width:1280px;margin:auto;background:#fff">
{fig.to_html(full_html=False, include_plotlyjs="cdn")}
<p style="color:#555;font-size:13px">实线=突破信号日 v2 实际窗口（win_len 可 <120，截断后）拟合的压力线段，同色虚线=支撑线段，
▲=突破日收盘。线段长度不同=动态窗证据（截断日窗变短）。点击图例整组开关；"全部对照"默认收起。</p>
</body></html>"""
    (HERE / "breakout_lines_view.html").write_text(html, encoding="utf-8")
    print("写出:", HERE / "breakout_lines_view.html")


if __name__ == "__main__":
    summary_view()
    lines_view()
