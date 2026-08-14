#!/usr/bin/env python
"""Regime 可视化生成器（skill-regime-Identifier Step 4b）。

加载 regime_impl.py 的 classify_regime(df)，对每种方法输出三件套：
  1. regime_segments.md  — 表格化各时间段划分
  2. regime_stats.json   — 各状态天数/占比统计
  3. regime_view.html    — close 曲线 + 状态背景着色

状态划分严格按研报/论文——状态值由 regime_impl.py 返回的
state_labels 决定，颜色按语义自动映射（上涨红/下跌绿/震荡蓝/其他色板）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False


# ── 语义颜色映射 ────────────────────────────────────────
# 按状态标签语义自动映射；无法识别的用扩展色板
SEMANTIC_COLORS = [
    ("上涨|牛市|趋势上升|up|bull|trend_up", "rgba(255, 153, 153, 0.30)"),    # 浅红
    ("下跌|熊市|趋势下降|down|bear|trend_down", "rgba(144, 238, 144, 0.30)"),  # 浅绿
    ("震荡|盘整|中性|range|sideways|neutral|震荡市", "rgba(173, 216, 230, 0.30)"),  # 浅蓝
]
FALLBACK_PALETTE = [
    "rgba(255, 228, 153, 0.30)",   # 浅黄
    "rgba(221, 160, 221, 0.30)",   # 浅紫
    "rgba(255, 200, 128, 0.30)",   # 浅橙
    "rgba(211, 211, 211, 0.35)",   # 浅灰
    "rgba(188, 234, 213, 0.30)",   # 浅青
]


def pick_color(label: str, used: dict) -> str:
    """按状态标签语义选色；未匹配的用扩展色板。"""
    import re
    low = str(label).lower()
    for pattern, color in SEMANTIC_COLORS:
        if re.search(pattern, low):
            return color
    # 扩展色板：按标签出现顺序分配
    for color in FALLBACK_PALETTE:
        if color not in used.values():
            return color
    return FALLBACK_PALETTE[0]


# ── 行情读取 ────────────────────────────────────────────
def read_table(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def normalize_market(df: pd.DataFrame) -> pd.DataFrame:
    need = ["date", "symbol", "open", "high", "low", "close"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"market data missing columns: {missing}")
    out = df[need].copy()
    out["date"] = pd.to_datetime(out["date"])
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out = out.sort_values("date").drop_duplicates(["date", "symbol"], keep="last")
    if out.empty:
        raise ValueError("market data is empty after cleaning")
    return out


# ── 策略装载 ────────────────────────────────────────────
def load_regime_impl(path: Path):
    spec = importlib.util.spec_from_file_location("regime_impl_mod", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法装载 regime_impl: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "classify_regime"):
        raise RuntimeError("regime_impl.py 必须定义 classify_regime(df) -> dict")
    return mod


# ── 区段计算 ────────────────────────────────────────────
def compute_segments(dates, state_series):
    """计算连续状态区段列表：[{start, end, state, days}]"""
    s = pd.Series(state_series).reset_index(drop=True)
    if len(s) == 0:
        return []
    blocks = (s != s.shift(1)).cumsum()
    segments = []
    for _bid, grp in s.groupby(blocks):
        idx_start, idx_end = grp.index[0], grp.index[-1]
        segments.append({
            "start": str(dates.iloc[idx_start].date()),
            "end": str(dates.iloc[idx_end].date()),
            "state": grp.iloc[0],
            "days": int(len(grp)),
        })
    return segments


def compute_stats(state_series, state_labels):
    """各状态天数/占比统计。"""
    s = pd.Series(state_series)
    total = len(s)
    stats = {"total_days": int(total), "states": {}}
    for st in s.dropna().unique():
        n = int((s == st).sum())
        label = state_labels.get(st, str(st))
        stats["states"][str(st)] = {
            "label": label,
            "days": n,
            "pct": round(n / total * 100, 1) if total else 0,
        }
    return stats


# ── 三件套输出 ──────────────────────────────────────────
def write_segments_md(all_segments, state_labels, out_path: Path):
    """表格化各时间段划分。"""
    lines = ["# Regime 时间段划分表", ""]
    for method, segs in all_segments.items():
        lines.append(f"## {method}")
        lines.append("")
        lines.append("| # | 开始 | 结束 | 状态 | 天数 |")
        lines.append("|---|------|------|------|------|")
        for i, seg in enumerate(segs, 1):
            label = state_labels.get(seg["state"], str(seg["state"]))
            lines.append(f"| {i} | {seg['start']} | {seg['end']} | {label} | {seg['days']} |")
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def generate_html(dates, close, methods, state_labels, out_path: Path):
    n = len(methods)
    if n == 0:
        raise ValueError("classify_regime 返回的方法列表为空")

    # 颜色分配（按语义）
    used_colors = {}
    state_colors = {}
    for state, label in state_labels.items():
        color = pick_color(label, used_colors)
        state_colors[state] = color
        used_colors[str(state)] = color

    subplot_titles = [f"{name}" for name in methods.keys()]

    if n == 1:
        fig = go.Figure()
        name = list(methods.keys())[0]
        _shade(fig, dates, close, methods[name], state_colors, state_labels, None)
        fig.add_trace(go.Scatter(x=dates, y=close, name="close",
                                 line=dict(color="#2980b9", width=1.4)))
        fig.update_layout(template="plotly_white", height=500, hovermode="x unified",
                          margin=dict(l=50, r=30, t=60, b=30), yaxis_title="close",
                          title=f"Regime View — {name}")
    else:
        fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=0.06,
                            subplot_titles=subplot_titles)
        for i, (name, state) in enumerate(methods.items()):
            row = i + 1
            _shade(fig, dates, close, state, state_colors, state_labels, row)
            fig.add_trace(go.Scatter(x=dates, y=close, name="close",
                                     line=dict(color="#2980b9", width=1.2),
                                     showlegend=(i == 0)), row=row, col=1)
        fig.update_layout(template="plotly_white", height=300 * n, hovermode="x unified",
                          margin=dict(l=50, r=30, t=40, b=30))

    fig.write_html(str(out_path))


def _shade(fig, dates, close, state_series, state_colors, state_labels, row):
    """对子图添加 regime 背景色块（任意状态值）。

    用 add_shape 画连续区段的 rect 背景（经过验证的正确方案）。
    """
    s = pd.Series(state_series).reset_index(drop=True)
    if len(s) == 0:
        return
    # 子图坐标轴引用：row=1 → x/y，row=i → xi/yi
    if row is None or row == 1:
        xref, yref = "x", "y domain"
    else:
        xref, yref = f"x{row}", f"y{row} domain"
    blocks = (s != s.shift(1)).cumsum()
    for _bid, grp in s.groupby(blocks):
        st = grp.iloc[0]
        color = state_colors.get(st, "rgba(211, 211, 211, 0.30)")
        idx_start, idx_end = grp.index[0], grp.index[-1]
        x0 = dates.iloc[idx_start] if idx_start < len(dates) else dates.iloc[-1]
        x1 = dates.iloc[idx_end] if idx_end < len(dates) else dates.iloc[-1]
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=0, y1=1,
                      xref=xref, yref=yref, fillcolor=color,
                      layer="below", line_width=0)


# ── manifest 更新 ───────────────────────────────────────
def update_manifest(project_dir: Path, stats: dict, market_data: str):
    mp = project_dir / "manifest.json"
    if not mp.exists():
        return
    m = json.loads(mp.read_text(encoding="utf-8-sig"))
    m["regime_engine"] = {"name": "regime-view-generator", "status": "ran",
                          "script": "scripts/generate_regime_view.py"}
    m.setdefault("run_history", []).append({
        "stage": "regime_verification", "market_data": str(market_data),
        "stats": stats})
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ── 主流程 ──────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--market-data", required=True, help="OHLCV CSV/Parquet")
    p.add_argument("--regime-impl", help="regime_impl.py 路径，默认 03_regime_analysis/regime_impl.py")
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    impl_path = Path(args.regime_impl).resolve() if args.regime_impl else \
        proj / "03_regime_analysis" / "regime_impl.py"
    market_path = Path(args.market_data).resolve()

    if not market_path.exists():
        raise FileNotFoundError(f"market data 不存在: {market_path}")
    if not impl_path.exists():
        raise FileNotFoundError(f"regime_impl.py 不存在: {impl_path}")
    if not _HAS_PLOTLY:
        raise ImportError("plotly 未安装，请 pip install plotly")

    # 1. 加载数据
    market = normalize_market(read_table(market_path))
    df = market.sort_values("date").reset_index(drop=True)
    print(f"数据: {len(df)} 行, {df['date'].min().date()} ~ {df['date'].max().date()}")

    # 2. 加载 regime_impl
    mod = load_regime_impl(impl_path)

    # 3. 运行分类
    result = mod.classify_regime(df)
    methods = result.get("methods", {})
    state_labels = result.get("state_labels", {})
    params = result.get("params", {})
    if not methods:
        raise ValueError("classify_regime 返回的方法列表为空")
    # 状态标签兜底：无 state_labels 时用状态值本身
    if not state_labels:
        all_states = set()
        for s in methods.values():
            all_states.update(pd.Series(s).dropna().unique())
        state_labels = {st: str(st) for st in all_states}
    print(f"方法: {list(methods.keys())}")
    print(f"状态: {state_labels}")

    out_dir = proj / "03_regime_analysis"

    # 4. 表格化时间段划分
    all_segments = {name: compute_segments(df["date"], s) for name, s in methods.items()}
    seg_path = out_dir / "regime_segments.md"
    write_segments_md(all_segments, state_labels, seg_path)
    print(f"regime_segments.md 已生成: {seg_path}")

    # 5. 统计
    all_stats = {name: compute_stats(s, state_labels) for name, s in methods.items()}
    stats_path = out_dir / "regime_stats.json"
    stats_path.write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"regime_stats.json 已生成: {stats_path}")

    # 6. 可视化
    out_html = out_dir / "regime_view.html"
    generate_html(df["date"], df["close"], methods, state_labels, out_html)
    print(f"regime_view.html 已生成: {out_html}")

    # 打印统计
    for name, st in all_stats.items():
        parts = [f"{v['label']}={v['pct']}%" for v in st["states"].values()]
        print(f"  {name}: {' | '.join(parts)}")

    # 7. 更新 manifest
    update_manifest(proj, all_stats, str(market_path))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
