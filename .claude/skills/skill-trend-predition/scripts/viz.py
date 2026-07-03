"""可视化：close/K线按 regime 着色（趋势红/震荡绿）+ 混淆矩阵 + 特征重要性 + 相关性热图。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
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
        seg_labels = is_trend.loc[idx]
        segs.append((idx[0], idx[-1], bool(seg_labels.iloc[0])))
    return segs


def plot_close_colored(close: pd.Series, labels: pd.Series, path, *, title: str = "") -> str:
    """close 折线 + 趋势段(红)/震荡段(绿) 背景着色。"""
    plt = _mpl()
    close = pd.Series(close).astype(float)
    labels = pd.Series(labels).reindex(close.index).fillna(0.0)
    fig, ax = plt.subplots(figsize=(13, 6))
    for s, e, is_trend in _regime_segments(labels):
        ax.axvspan(s, e, color="#e74c3c" if is_trend else "#27ae60", alpha=0.12)
    ax.plot(close.index, close.values, color="#2c3e50", linewidth=1.2)
    ax.set_title(title or "close 走势（红=趋势段，绿=震荡段）")
    ax.grid(alpha=0.3)
    # 简易图例
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#e74c3c", alpha=0.3, label="趋势"),
                       Patch(color="#27ae60", alpha=0.3, label="震荡")], loc="best")
    return _save(fig, path)


def plot_kline_colored(df: pd.DataFrame, labels: pd.Series, path, *,
                       last_n: int = 200, title: str = "") -> str:
    """手画 K 线（最后 last_n 根），按 regime 着色（趋势红/震荡绿）。需 open/high/low/close。"""
    plt = _mpl()
    d = df.tail(last_n).copy()
    close, *_ = _safe_ohlcv(d)
    lab = pd.Series(labels).reindex(d.index).fillna(0.0)
    up = d["open"] <= d["close"] if "open" in d.columns else pd.Series(True, index=d.index)
    fig, ax = plt.subplots(figsize=(13, 6))
    x = range(len(d))
    for i, (idx, row) in enumerate(d.iterrows()):
        c_open, c_close = row.get("open", close.loc[idx]), row["close"]
        hi, lo = row.get("high", c_close), row.get("low", c_close)
        is_trend = lab.loc[idx] != 0
        base = "#e74c3c" if is_trend else "#27ae60"
        color = base if (c_close >= c_open) else base  # regime 决定主色
        ax.vlines(i, lo, hi, color=color, linewidth=0.8)
        body_lo, body_hi = min(c_open, c_close), max(c_open, c_close)
        ax.add_patch(plt.Rectangle((i - 0.3, body_lo), 0.6, max(body_hi - body_lo, 0.0),
                                   facecolor=color, edgecolor=color, alpha=0.85))
    ax.set_xlim(-1, len(d))
    ax.set_xticks(np.linspace(0, len(d) - 1, 6))
    ax.set_xticklabels([d.index[int(i)].date() for i in np.linspace(0, len(d) - 1, 6)])
    ax.set_title(title or f"K线（近{len(d)}根，红=趋势段，绿=震荡段）")
    ax.grid(alpha=0.3)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="#e74c3c", label="趋势"), Patch(color="#27ae60", label="震荡")], loc="best")
    return _save(fig, path)


def plot_confusion(cm, classes, path, *, title: str = "混淆矩阵") -> str:
    plt = _mpl()
    cm = np.asarray(cm)
    fig, ax = plt.subplots(figsize=(4.5, 4))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(classes))); ax.set_yticks(range(len(classes)))
    ax.set_xticklabels([str(c) for c in classes]); ax.set_yticklabels([str(c) for c in classes])
    ax.set_xlabel("预测"); ax.set_ylabel("真实"); ax.set_title(title)
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
    ax.set_xlabel("importance"); ax.set_title(title)
    return _save(fig, path)


def plot_corr_heatmap(corr: pd.DataFrame, path, *, title: str = "特征相关性") -> str:
    plt = _mpl()
    fig, ax = plt.subplots(figsize=(max(6, 0.5 * len(corr.columns) + 2), max(5, 0.5 * len(corr.columns) + 2)))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns))); ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr.columns)
    ax.set_title(title)
    fig.colorbar(im, fraction=0.046)
    return _save(fig, path)


def _safe_ohlcv(df):
    close = df["close"] if "close" in df.columns else df.iloc[:, 0]
    return close, df.get("high", close), df.get("low", close)


__all__ = [
    "plot_close_colored", "plot_kline_colored", "plot_confusion",
    "plot_feature_importance", "plot_corr_heatmap",
]
