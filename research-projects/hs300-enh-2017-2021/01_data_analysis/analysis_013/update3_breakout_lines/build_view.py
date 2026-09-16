"""analysis_013 更新三 — 多形态合一净值图 + 各形态突破当时的压力/支撑线（可开关）。

图结构（单张 plotly，双 y 轴）：
  左轴（净值）：12 个回测的净值曲线 + 沪深300 买入持有（黑粗线）
  右轴（指数点位）：每个回测的每笔交易，在【信号日】(entry 前一交易日) 画出当时
    120 日窗口拟合出的压力线段（实线）与支撑线段（虚线），段长=整窗 120 日；
    并在该日收盘价标 ▲（突破时刻）
  开关：每形态一个 legendgroup（净值+R线+S线+▲ 联动），点击图例整组显隐；
    "全部对照" 默认收起（线太多，可手动展开）

线段重建（免重拟合）：由当日已存的 p1,R_t（价格单位）反解截距
  b0 = R_t − p1·(N−1)，R(x) = b0 + p1·x，x=0..N−1 映射到 [t−119, t] 的日期。
数据依赖：../update2_pattern_backtests/（runs/*/trades.csv, nav.csv, hs300_index.parquet）
+ 重算一次因果口径信号（缓存 lines_causal.parquet）。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
U2 = HERE.parent / "update2_pattern_backtests"
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ / "shared"))
from quantreg_sr_algo import DEFAULT_PARAMS as P, breakout_signals, rolling_lines  # noqa: E402

warnings.filterwarnings("ignore", module="statsmodels.*")
PALETTE = ["#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e", "#805ad5", "#dd6b20",
           "#319795", "#b83280", "#4a5568", "#38b2ac", "#c53030", "#718096"]


def load_signals(idx: pd.DataFrame) -> pd.DataFrame:
    cache = HERE / "lines_causal.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    sig = breakout_signals(rolling_lines(idx, causal=True), idx["close"])
    sig.to_parquet(cache)
    return sig


def segments(sig_day: pd.Series, dates: pd.DatetimeIndex, close: pd.Series, n_win: int):
    """信号日 → 该日窗口的 R/S 线段 (dates_win, R_seg, S_seg)。

    斜率单位换算（修复 09-09 单位 bug）：p1/p2 是归一化斜率（首日=100 的 %/日），
    价格斜率 = p × win0/100（win0=窗口起点收盘价）。段末端恒等于 R_t/S_t。
    """
    t = dates.get_loc(sig_day.name)
    win0 = float(close.iloc[t - n_win + 1])
    x = np.arange(n_win, dtype=float)
    sr = sig_day["p1"] * win0 / 100.0
    ss = sig_day["p2"] * win0 / 100.0
    b0r = sig_day["R"] - sr * (n_win - 1)
    b0s = sig_day["S"] - ss * (n_win - 1)
    return dates[t - n_win + 1:t + 1], b0r + sr * x, b0s + ss * x


def main():
    idx = pd.read_parquet(U2 / "hs300_index.parquet").set_index("date")
    sig = load_signals(idx)
    tb = pd.read_csv(U2 / "summary_table.csv")

    fig = go.Figure()
    bench_nav = idx["close"] / idx["close"].iloc[0]
    fig.add_trace(go.Scatter(x=idx.index, y=bench_nav, name="沪深300 买入持有", legendgroup="bench",
                             line=dict(color="#1a202c", width=3), yaxis="y1"))

    for i, row in tb.iterrows():
        run_id, name, col = row["run_id"], row["形态"], PALETTE[i % len(PALETTE)]
        grp = f"g{i}"
        hide = run_id == "all_全部对照"
        nav = pd.read_csv(U2 / "runs" / run_id / "nav.csv", parse_dates=["date"])
        fig.add_trace(go.Scatter(
            x=nav["date"], y=nav["nav"], name=f"{name}({int(row['n_trades'])}笔)",
            legendgroup=grp, line=dict(color=col, width=1.3), yaxis="y1",
            visible="legendonly" if hide else True))
        tr = pd.read_csv(U2 / "runs" / run_id / "trades.csv", parse_dates=["entry_date"])
        # 每笔交易：信号日=入场日前一交易日 → 当时窗口的 R/S 线段 + 突破点
        xs_r, ys_r, xs_s, ys_s, xs_m, ys_m = [], [], [], [], [], []
        for e in tr["entry_date"]:
            t = idx.index.get_loc(e) - 1 if e in idx.index else None
            if t is None or t < P["N"]:
                continue
            day = sig.loc[idx.index[t]]          # 信号日=入场日前一交易日（按日期标签取）
            if not np.isfinite(day["R"]):
                continue
            dw, r_seg, s_seg = segments(day, idx.index, idx["close"], P["N"])
            xs_r += list(dw) + [None]; ys_r += list(r_seg) + [None]
            xs_s += list(dw) + [None]; ys_s += list(s_seg) + [None]
            xs_m.append(dw[-1]); ys_m.append(day["close"])
        fig.add_trace(go.Scatter(
            x=xs_r, y=ys_r, name=f"{name} 突破时压力线", legendgroup=grp, showlegend=False,
            line=dict(color=col, width=1.0, shape="spline", smoothing=0.3), opacity=0.55,
            yaxis="y2", visible="legendonly" if hide else True, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=xs_s, y=ys_s, name=f"{name} 突破时支撑线", legendgroup=grp, showlegend=False,
            line=dict(color=col, width=1.0, dash="dash"), opacity=0.45,
            yaxis="y2", visible="legendonly" if hide else True, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=xs_m, y=ys_m, name=f"{name} 突破点", legendgroup=grp, showlegend=False,
            mode="markers", marker=dict(symbol="triangle-up", size=8, color=col,
                                        line=dict(width=1, color="#1a202c")),
            yaxis="y2",
            text=[f"{d.date()} {name} 突破" for d in xs_m], hoverinfo="text",
            visible="legendonly" if hide else True))

    fig.update_layout(
        height=760, template="plotly_white", hovermode="x unified",
        title=dict(text="analysis_013 更新三 · 净值 + 各形态突破当时的压力/支撑线（左轴净值，右轴指数点位）",
                   x=0.5, font=dict(size=15)),
        legend=dict(orientation="h", y=-0.12, font=dict(size=11)),
        yaxis=dict(title="净值（左）"),
        yaxis2=dict(title="沪深300 点位（右）", overlaying="y", side="right"),
        margin=dict(l=60, r=60, t=80, b=80))

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>analysis_013 更新三</title></head>
<body style="font-family:system-ui;max-width:1280px;margin:auto;background:#fff">
{fig.to_html(full_html=False, include_plotlyjs="cdn")}
<p style="color:#555;font-size:13px">实线=突破信号日当时窗口拟合的压力线段（120日整窗），同色虚线=支撑线段，
▲=突破日收盘（右轴）。<b>点击图例整组开关某形态</b>（净值曲线+其全部画线联动）；双击图例可独显；
"全部对照"默认收起（54 段线太密，点开可看全貌）。线段由当日 p1/R 反解截距重建，与引擎信号同源。</p>
</body></html>"""
    out = HERE / "breakout_lines_view.html"
    out.write_text(html, encoding="utf-8")
    print("写出:", out)


if __name__ == "__main__":
    main()
