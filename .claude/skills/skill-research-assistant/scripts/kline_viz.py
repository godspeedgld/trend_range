"""K线可视化公共模块（数据分析 / 回测报告共用，样式统一）。

样式基准（对齐 ssquant backtest_visualization 的观感）：
  - A股习惯：红涨 #e74c3c / 绿跌 #2ecc71，细影线（whiskerwidth 0.4，线宽 0.8）
  - 交互：底部拖动条（rangeslider）+ 按住左键拖动平移（dragmode='pan'）+
          hover tip 显示 日期/开/高/低/收（hovermode='x'）
  - 可选叠加：买卖点标记（▲开仓在K线下方偏移 / ▼平仓在上方偏移，带价格文本）、
          最高/最低点标注、水平参考线（如 HSAR 阻力位）

用法：
  from kline_viz import add_candlestick, style_kline, add_trade_markers

  fig = go.Figure()
  add_candlestick(fig, df)                     # df 需含 date/open/high/low/close
  add_trade_markers(fig, trades_df)            # 可选：trades 需含 date/price/action
  style_kline(fig, title="...", height=600)    # 统一布局/交互

单图与 make_subplots 子图均适用（row/col 透传）。
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

UP_COLOR = "#e74c3c"      # 涨：红（A股习惯）
DOWN_COLOR = "#2ecc71"    # 跌：绿


def add_candlestick(fig: go.Figure, df: pd.DataFrame, name: str = "",
                    row=None, col=1, hover_ohlc: bool = True) -> None:
    """加 K 线（红涨绿跌 + 细影线 + hover 显示日期/OHLC）。

    df 需含 date/open/high/low/close 列。
    """
    kw = dict(row=row, col=col) if row is not None else {}
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name=name or "K线",
        increasing_line_color=UP_COLOR, decreasing_line_color=DOWN_COLOR,
        increasing_line=dict(width=0.8), decreasing_line=dict(width=0.8),
        whiskerwidth=0.4,
        hovertemplate=("%{x|%Y-%m-%d}<br>开 %{open:.2f}  高 %{high:.2f}<br>"
                       "低 %{low:.2f}  收 %{close:.2f}<extra></extra>"
                       if hover_ohlc else None)), **kw)


def add_trade_markers(fig: go.Figure, trades: pd.DataFrame, row=None, col=1) -> None:
    """加买卖点标记：▲开仓（K线下方偏移，红）+ ▼平仓（上方偏移，绿），带价格文本。

    trades 需含 date/price/action 列（action: 'open'/'close'，或 '开多'/'平多'等含 开/平）。
    """
    if trades is None or not len(trades):
        return
    t = trades.copy()
    if "action" in t.columns:
        is_open = t["action"].astype(str).str.contains("开|open|buy", case=False)
        is_close = t["action"].astype(str).str.contains("平|close|sell", case=False)
    else:
        return
    kw = dict(row=row, col=col) if row is not None else {}
    ops = t[is_open]
    cls = t[is_close]
    if len(ops):
        fig.add_trace(go.Scatter(
            x=ops["date"], y=ops["price"] * 0.985, mode="markers+text",
            marker=dict(symbol="triangle-up", size=13, color=UP_COLOR,
                        line=dict(width=1, color="#ffffff")),
            text=[f"{p:.2f}" for p in ops["price"]], textposition="bottom center",
            textfont=dict(size=9, color=UP_COLOR),
            name="开仓", hovertemplate="开仓 %{x|%Y-%m-%d} @ %{y:.2f}<extra></extra>"), **kw)
    if len(cls):
        fig.add_trace(go.Scatter(
            x=cls["date"], y=cls["price"] * 1.015, mode="markers+text",
            marker=dict(symbol="triangle-down", size=13, color=DOWN_COLOR,
                        line=dict(width=1, color="#ffffff")),
            text=[f"{p:.2f}" for p in cls["price"]], textposition="top center",
            textfont=dict(size=9, color=DOWN_COLOR),
            name="平仓", hovertemplate="平仓 %{x|%Y-%m-%d} @ %{y:.2f}<extra></extra>"), **kw)


def add_hilo_annotation(fig: go.Figure, df: pd.DataFrame, row=None, col=1) -> None:
    """标全窗口最高/最低点（红▲最高 / 绿▼最低 + 价格文本，ssquant 风格）。"""
    if df is None or not len(df):
        return
    kw = dict(row=row, col=col) if row is not None else {}
    hi_i = int(df["high"].idxmax())
    lo_i = int(df["low"].idxmin())
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[hi_i]], y=[df["high"].iloc[hi_i]],
        mode="markers+text", name="最高",
        marker=dict(symbol="triangle-up", size=12, color=UP_COLOR),
        text=[f"最高 {df['high'].iloc[hi_i]:.2f}"], textposition="top center",
        textfont=dict(size=10, color=UP_COLOR),
        hovertemplate="最高 %{y:.2f}<extra></extra>"), **kw)
    fig.add_trace(go.Scatter(
        x=[df["date"].iloc[lo_i]], y=[df["low"].iloc[lo_i]],
        mode="markers+text", name="最低",
        marker=dict(symbol="triangle-down", size=12, color=DOWN_COLOR),
        text=[f"最低 {df['low'].iloc[lo_i]:.2f}"], textposition="bottom center",
        textfont=dict(size=10, color=DOWN_COLOR),
        hovertemplate="最低 %{y:.2f}<extra></extra>"), **kw)


def add_hline(fig: go.Figure, y: float, label: str = "", x0=None, x1=None,
              color: str = "#c0392b", dash: str = "dash") -> None:
    """加水平参考线（如 HSAR 阻力位）+ 左端标注。"""
    fig.add_shape(type="line", x0=x0, x1=x1, y0=y, y1=y,
                  line=dict(color=color, width=1.4, dash=dash))
    if label:
        fig.add_annotation(x=x0, y=y, text=label, showarrow=False,
                           font=dict(size=10, color=color), yanchor="bottom")


def style_kline(fig: go.Figure, title: str = "", height: int = 600,
                rangeslider: bool = True, hovermode: str = "x") -> go.Figure:
    """统一布局与交互：拖动条 + 左键拖动平移 + hover tip。"""
    fig.update_layout(
        template="plotly_white", height=height, showlegend=True,
        title=dict(text=title, font=dict(size=14)) if title else None,
        xaxis_rangeslider_visible=rangeslider,
        dragmode="pan",
        hovermode=hovermode,
        margin=dict(l=50, r=30, t=60 if title else 40, b=40))
    return fig
