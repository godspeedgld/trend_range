"""可视化：通用「主图 + 副图」plot_panels（一个函数、参数控制一切），以及混淆矩阵/特征重要性/相关性。

设计：plot_panels 一个函数承担所有 OHLCV+指标 可视化：
  - 主图：close 折线 或 K 线（main="close"|"kline"）
  - 主图可选 regime 着色（main_colored 标签 → 趋势红/震荡绿 背景；K 线则按 regime 上色）
  - 任意数量副图，每个副图可含 折线(lines) / 柱状(bars) / 水平参考线(hlines)
旧接口 plot_close_colored / plot_kline_colored 保留为薄封装（reports.py 不受影响）。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # 中文字体（Windows 用 Microsoft YaHei / SimHei；其它系统尝试 Noto CJK），避免中文图例变方框
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
                                       "WenQuanYi Zen Hei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _save(fig, path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    import matplotlib.pyplot as plt
    plt.close(fig)
    return str(path)


def _regime_segments(labels: pd.Series) -> list[tuple]:
    """把 0/非0 标签切成连续段，返回 [(start_idx, end_idx, is_trend), ...]。"""
    s = pd.Series(labels).fillna(0.0)
    is_trend = (s != 0).astype(int)
    if is_trend.empty:
        return []
    breaks = is_trend.ne(is_trend.shift()).cumsum()
    segs = []
    for _, idx in is_trend.groupby(breaks).groups.items():
        sl = is_trend.loc[idx]
        segs.append((idx[0], idx[-1], bool(sl.iloc[0])))
    return segs


def _bar_width(d: pd.DataFrame) -> float:
    """datetime index → 一根 K 线的柱宽（天）；否则 0.8。"""
    idx = d.index
    if len(idx) >= 2 and np.issubdtype(idx.dtype, np.datetime64):
        deltas = np.diff(idx.values).astype("timedelta64[D]").astype(float)
        pos = deltas[deltas > 0]
        med = float(np.median(pos)) if len(pos) else 1.0
        return max(med * 0.6, 0.5)
    return 0.8


def _draw_candles(ax, d: pd.DataFrame, main_colored):
    """向量画 K 线；main_colored 给定时按 regime 上色，否则涨红跌绿。"""
    o = d["open"].values
    c = d["close"].values
    hi = d["high"].values
    lo = d["low"].values
    if main_colored is not None:
        lab = pd.Series(main_colored).reindex(d.index).fillna(0.0).values
        colors = np.where(lab != 0, "#e74c3c", "#27ae60")
    else:
        colors = np.where(c >= o, "#c0392b", "#27ae60")
    ax.vlines(d.index, lo, hi, color=colors, linewidth=0.8)
    ax.bar(d.index, np.abs(c - o), bottom=np.minimum(o, c),
           width=_bar_width(d) * 1.3, color=colors, edgecolor=colors, alpha=0.9)


def plot_panels(
    df: pd.DataFrame,
    *,
    main: str = "close",
    main_colored: Optional[pd.Series] = None,
    panels: Optional[list[dict]] = None,
    title: Optional[str] = None,
    path: Optional[str] = None,
    last_n: Optional[int] = None,
    figsize: Optional[tuple] = None,
) -> str:
    """主图 + 副图通用可视化（一个函数、参数控制）。

    Args:
        df: OHLCV DataFrame（至少含 close；main="kline" 需 open/high/low/close）。
        main: "close"（折线）或 "kline"（K线）。
        main_colored: 可选 regime 标签 Series（0/非0）→ 主图趋势红/震荡绿（背景或 K线着色）。
        panels: 副图列表，每项 {"title":str,
                              "lines":{name:Series},   # 折线
                              "bars":{name:Series},    # 柱状（如 MACD hist）
                              "hlines":[25, ...]}      # 水平参考线（如 ADX=25、MACD=0）
        last_n: 只画最后 N 根（K线/大数据可读性）。
    """
    plt = _mpl()
    d = df.tail(last_n).copy() if last_n else df.copy()
    panels = panels or []
    n = 1 + len(panels)
    fig, axes = plt.subplots(n, 1, figsize=figsize or (13, 3.5 + 2.2 * len(panels)),
                             sharex=True,
                             gridspec_kw={"height_ratios": [3] + [1] * len(panels)})
    if n == 1:
        axes = [axes]
    ax0 = axes[0]

    if main_colored is not None:
        lab = pd.Series(main_colored).reindex(d.index).fillna(0.0)
        for s, e, is_trend in _regime_segments(lab):
            ax0.axvspan(s, e, color="#e74c3c" if is_trend else "#27ae60", alpha=0.12)
        if main != "kline":
            from matplotlib.patches import Patch
            ax0.legend(handles=[Patch(color="#e74c3c", alpha=0.3, label="趋势"),
                                Patch(color="#27ae60", alpha=0.3, label="震荡")], loc="best")

    if main == "kline" and {"open", "high", "low"}.issubset(d.columns):
        _draw_candles(ax0, d, main_colored)
    else:
        ax0.plot(d.index, d["close"].values, color="#2c3e50", linewidth=1.2, label="close")
    ax0.set_title(title or "")
    ax0.grid(alpha=0.3)

    bw = _bar_width(d)
    for ax, p in zip(axes[1:], panels):
        for name, s in (p.get("lines") or {}).items():
            ax.plot(d.index, pd.Series(s).reindex(d.index).values, label=name, linewidth=1.0)
        for name, s in (p.get("bars") or {}).items():
            ax.bar(d.index, pd.Series(s).reindex(d.index).values, label=name, width=bw, alpha=0.6)
        for h in (p.get("hlines") or []):
            ax.axhline(h, color="gray", linewidth=0.7, linestyle="--")
        ax.set_ylabel(p.get("title", ""))
        ax.grid(alpha=0.3)
        if p.get("lines") or p.get("bars"):
            ax.legend(loc="best", fontsize="small")

    return _save(fig, path)


# ─── 薄封装（向后兼容 reports.py 的旧调用）──────────────────
def plot_close_colored(close: pd.Series, labels: pd.Series, path, *, title: str = "") -> str:
    """close 折线 + regime 着色（= plot_panels(main="close", main_colored=labels)）。"""
    df = pd.Series(close).to_frame(name="close")
    return plot_panels(df, main="close", main_colored=labels, title=title, path=path)


def plot_kline_colored(df: pd.DataFrame, labels: pd.Series, path, *, last_n: int = 200,
                       title: str = "") -> str:
    """K 线 + regime 着色（= plot_panels(main="kline", main_colored=labels)）。"""
    return plot_panels(df, main="kline", main_colored=labels, title=title, path=path, last_n=last_n)


def plot_panels_html(
    df: pd.DataFrame,
    *,
    main: str = "close",
    main_colored: Optional[pd.Series] = None,
    panels: Optional[list[dict]] = None,
    title: Optional[str] = None,
    path: Optional[str] = None,
    last_n: Optional[int] = None,
    embed: bool = False,
) -> str:
    """交互式 HTML 版（plotly）。参数与 plot_panels 一致；输出可缩放/悬停/导出的独立 HTML。

    Args:
        embed: False（默认）→ 从 CDN 加载 plotly.js（HTML 小，需联网查看）；
               True → 内嵌 plotly.js（HTML 大但离线可看）。
    """
    from plotly.subplots import make_subplots
    import plotly.graph_objects as go

    d = df.tail(last_n).copy() if last_n else df.copy()
    panels = panels or []
    nrows = 1 + len(panels)
    heights = [3] + [1] * len(panels) if panels else [1]
    fig = make_subplots(
        rows=nrows, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=heights,
        subplot_titles=[title or "主图"] + [p.get("title", f"副图{i}") for i, p in enumerate(panels, 1)],
    )

    if main_colored is not None:
        lab = pd.Series(main_colored).reindex(d.index).fillna(0.0)
        for s, e, is_trend in _regime_segments(lab):
            try:
                fig.add_vrect(x0=s, x1=e, row=1, col=1,
                              fillcolor="#e74c3c" if is_trend else "#27ae60", opacity=0.10,
                              line_width=0)
            except Exception:
                pass

    if main == "kline" and {"open", "high", "low"}.issubset(d.columns):
        fig.add_trace(go.Candlestick(x=d.index, open=d["open"], high=d["high"],
                                     low=d["low"], close=d["close"], name="K线",
                                     increasing_line_color="#c0392b", decreasing_line_color="#27ae60"),
                      row=1, col=1)
    else:
        fig.add_trace(go.Scatter(x=d.index, y=d["close"], mode="lines", name="close",
                                 line=dict(color="#2c3e50", width=1.2)), row=1, col=1)

    for i, p in enumerate(panels, start=2):
        for name, s in (p.get("lines") or {}).items():
            ss = pd.Series(s).reindex(d.index)
            fig.add_trace(go.Scatter(x=d.index, y=ss, mode="lines", name=name, line=dict(width=1.2)),
                          row=i, col=1)
        for name, s in (p.get("bars") or {}).items():
            ss = pd.Series(s).reindex(d.index)
            fig.add_trace(go.Bar(x=d.index, y=ss, name=name, opacity=0.6), row=i, col=1)
        for h in (p.get("hlines") or []):
            fig.add_hline(y=h, line_dash="dash", line_color="gray", row=i, col=1)

    fig.update_layout(
        title=title or "", hovermode="x unified", template="plotly_white",
        xaxis_rangeslider_visible=False, height=300 + 220 * len(panels),
        margin=dict(l=50, r=30, t=50, b=40),
    )
    fig.write_html(path, include_plotlyjs="cdn" if not embed else True)
    return str(path)


# ─── 评估/特征诊断图 ────────────────────────────────────────
def plot_confusion(cm, classes, path, *, title: str = "混淆矩阵") -> str:
    plt = _mpl()
    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(classes)))
    ax.set_yticks(range(len(classes)))
    ax.set_xticklabels([str(c) for c in classes])
    ax.set_yticklabels([str(c) for c in classes])
    ax.set_xlabel("预测")
    ax.set_ylabel("真实")
    ax.set_title(title)
    thr = cm.max() / 2 if cm.max() else 0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > thr else "black", fontsize=9)
    fig.colorbar(im, fraction=0.046)
    return _save(fig, path)


def plot_feature_importance(importances: dict, path, *, title: str = "特征重要性", top_n: int = 20) -> str:
    plt = _mpl()
    items = sorted(importances.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    names = [k for k, _ in items][::-1]
    vals = [v for _, v in items][::-1]
    fig, ax = plt.subplots(figsize=(8, max(3, 0.3 * len(names) + 1)))
    ax.barh(names, vals, color="#2980b9")
    ax.set_xlabel("importance")
    ax.set_title(title)
    return _save(fig, path)


def plot_corr_heatmap(corr: pd.DataFrame, path, *, title: str = "特征相关性") -> str:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(max(6, 0.5 * len(corr.columns) + 2), max(5, 0.5 * len(corr.columns) + 2)))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr.columns)
    ax.set_title(title)
    fig.colorbar(im, fraction=0.046)
    return _save(fig, path)


__all__ = [
    "plot_panels", "plot_panels_html", "plot_close_colored", "plot_kline_colored",
    "plot_confusion", "plot_feature_importance", "plot_corr_heatmap",
]
