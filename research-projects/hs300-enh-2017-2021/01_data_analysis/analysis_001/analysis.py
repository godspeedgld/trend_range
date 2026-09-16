"""analysis_001 — 平台突破算法工作原理可视化。

目的：直观检验 转折点识别 + HSAR 阻力位 + 突破触发 三个环节在个股上的工作方式。

步骤：
  1. 扫描 2021-06 每个交易日 × 沪深300当日成分股，跑 entry_signal（与策略完全同口径）
  2. 收集全部满足开仓条件的信号（symbol, signal_date）
  3. 选信号日离 2021-06-30 最近的 3 只
  4. 每只画 2020-01 ~ 2021-06 K线：标注 入选日 / 转折点高低点 / HSAR 阻力位

输出：result_view.html（3 子图）+ 信号清单打印
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
STRAT_DIR = PROJ / "02_strategy_iteration" / "strategy_001" / "backtest_strategy"
sys.path.insert(0, str(STRAT_DIR))

from strategy import (turning_points, resistance_level,  # noqa: E402
                      members_asof, PARAMS, LOOKBACK)

# ── 配置 ──
SCAN_START, SCAN_END = "2021-06-01", "2021-06-30"
TOP_N = 3
PLOT_START = "2020-01-01"


def scan_signals(market: pd.DataFrame) -> list[dict]:
    """扫 2021-06 每日每成分股，返回满足开仓条件的信号。"""
    market = market.copy()
    market["date"] = pd.to_datetime(market["date"])
    scan_days = sorted(market.loc[(market["date"] >= SCAN_START)
                                  & (market["date"] <= SCAN_END), "date"].unique())
    sym_groups = {s: g.sort_values("date").reset_index(drop=True)
                  for s, g in market.groupby("symbol")}
    signals = []
    for d in scan_days:
        members = members_asof(d)
        for sym, g in sym_groups.items():
            idx = g.index[g["date"] == d]
            if len(idx) == 0:
                continue
            i = idx[0]
            if sym not in members or i + 1 < LOOKBACK:
                continue
            hd = g.iloc[:i + 1]                      # ≤d 历史（无未来）
            win = hd.iloc[-LOOKBACK:]
            highs, _ = turning_points(win, PARAMS)
            res = resistance_level(highs, PARAMS)
            if res is None:
                continue
            if hd["close"].iloc[-1] > res * (1 + PARAMS["break_pct"]):
                signals.append({"symbol": sym, "signal_date": d,
                               "resistance": res,
                               "close": float(hd["close"].iloc[-1])})
    return signals


def annotate_kline(g: pd.DataFrame, sig: dict) -> "go.Figure":
    """画单只股票 K线 + 三类标注。"""
    import plotly.graph_objects as go
    g = g[g["date"] >= PLOT_START].reset_index(drop=True)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=g["date"], open=g["open"], high=g["high"], low=g["low"], close=g["close"],
        name=sig["symbol"], increasing_line_color="#c0392b", decreasing_line_color="#27ae60"))

    # 标注①：转折点识别 的高/低点（全图窗口）
    highs, lows = turning_points(g, PARAMS)
    if highs:
        fig.add_trace(go.Scatter(
            x=[g["date"].iloc[i] for i, _ in highs], y=[p for _, p in highs],
            mode="markers", name="turning high",
            marker=dict(symbol="triangle-down", size=9, color="#e67e22"),
            hovertemplate="高点 %{y:.2f}<extra></extra>"))
    if lows:
        fig.add_trace(go.Scatter(
            x=[g["date"].iloc[i] for i, _ in lows], y=[p for _, p in lows],
            mode="markers", name="turning low",
            marker=dict(symbol="triangle-up", size=9, color="#2980b9"),
            hovertemplate="低点 %{y:.2f}<extra></extra>"))

    # 标注②：HSAR 阻力位（信号日回溯一年算出，水平线）
    sig_i = g.index[g["date"] == sig["signal_date"]]
    if len(sig_i):
        i0 = sig_i[0]
        lo_t = max(0, i0 - LOOKBACK)
        fig.add_shape(type="line",
                      x0=g["date"].iloc[lo_t], x1=g["date"].iloc[-1],
                      y0=sig["resistance"], y1=sig["resistance"],
                      line=dict(color="#c0392b", width=1.4, dash="dash"))
        fig.add_annotation(x=g["date"].iloc[lo_t], y=sig["resistance"],
                           text=f"HSAR resistance {sig['resistance']:.2f}",
                           showarrow=False, font=dict(size=10, color="#c0392b"),
                           yanchor="bottom")

    # 标注③：入选日（突破信号日，竖线 + 星标）
    fig.add_vline(x=sig["signal_date"], line_dash="dot", line_color="#8e44ad", line_width=1.5)
    if len(sig_i):
        fig.add_trace(go.Scatter(
            x=[sig["signal_date"]], y=[sig["close"]],
            mode="markers+text", name="entry signal",
            marker=dict(symbol="star", size=16, color="#8e44ad"),
            text=["BREAK"], textposition="top center",
            hovertemplate=f"入选 {sig['signal_date'].date()} 收盘 {sig['close']:.2f}<extra></extra>"))

    fig.update_layout(
        template="plotly_white", height=420, showlegend=True,
        title=dict(text=(f"{sig['symbol']}  |  signal {sig['signal_date'].date()}  "
                         f"close {sig['close']:.2f} > res {sig['resistance']:.2f} × 1.03"),
                   font=dict(size=13)),
        xaxis_rangeslider_visible=False, margin=dict(l=50, r=30, t=60, b=30))
    return fig


def main():
    market = pd.read_csv(PROJ / "_market_hs300_all.csv")
    print(f"数据 {len(market)} rows")

    signals = scan_signals(market)
    sig_df = pd.DataFrame(signals)
    print(f"\n2021-06 满足开仓条件的信号: {len(sig_df)} 个（涉及 {sig_df.symbol.nunique()} 只）")
    if sig_df.empty:
        print("无信号")
        return

    # 离 6-30 最近优先
    sig_df["dist"] = (pd.Timestamp(SCAN_END) - sig_df["signal_date"]).dt.days
    top = sig_df.sort_values("dist").head(TOP_N)
    print(f"\n入选 {TOP_N} 只（信号日离 06-30 最近优先）:")
    for _, r in top.iterrows():
        print(f"  {r.symbol}: 信号日 {r.signal_date.date()}, 阻力位 {r.resistance:.2f}, "
              f"收盘 {r.close:.2f} (突破 {(r.close/r.resistance-1)*100:+.1f}%)")

    # 画图（每只独立 figure，拼接为一个 HTML 页面）
    market["date"] = pd.to_datetime(market["date"])
    figures = []
    for _, r in top.iterrows():
        g = market[market["symbol"] == r.symbol].sort_values("date").reset_index(drop=True)
        figures.append(annotate_kline(g, r))

    parts = []
    for i, f in enumerate(figures):
        parts.append(f.to_html(full_html=False, include_plotlyjs=(i == 0),
                               div_id=f"fig_{i}"))
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>平台突破算法原理可视化 2021-06</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;background:#fff;}}</style>
</head><body>
<h1>平台突破算法工作原理 — 2021-06 信号案例（3 只）</h1>
<p>标注说明：★紫星+紫虚线=突破入选日（收盘 &gt; 阻力位×1.03）；橙色▼=转折点识别的高点；
蓝色▲=转折点低点；红色虚横线=HSAR 阻力位（信号日回溯一年计算）。</p>
{''.join(parts)}
</body></html>"""
    out = HERE / "result_view.html"
    out.write_text(body, encoding="utf-8")
    sig_df.to_csv(HERE / "_signals_202106.csv", index=False)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
