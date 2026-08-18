#!/usr/bin/env python
"""生成 regime 标注（人工输入转换 或 Zig-Zag+Binseg 算法标注）。

用法：
  python zigzag_label.py {project_dir} --market-data <510300.csv>                  # 算法标注
  python zigzag_label.py {project_dir} --market-data <csv> --manual-label <md>     # 人工标注转换

输出：01_initial/regime_label.md + regime_label_view.html，更新 manifest。

Zig-Zag+Binseg 算法来源：申万宏源《趋势/震荡环境划分》（replication/sw-hy-trend-range）。
参数（原文值）：转折阈值=10%，最小年化收益=20%，指定时长=63天。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 默认参数（申万原文值）───────────────────────────────
DEFAULT_PARAMS = {
    "turn_thresh": 0.10,   # 转折阈值 10%
    "min_ann_ret": 0.20,   # 最小年化收益 20%
    "min_days": 63,        # 指定时长 63 天（约一季度）
}

STATE_LABELS = {1: "趋势", 0: "震荡"}
COLORS = {1: "rgba(255, 228, 153, 0.30)", 0: "rgba(173, 216, 230, 0.30)"}


# ═══════════════════════════════════════════════════════════
# Zig-Zag + Binseg 算法（提取自 replication/sw-hy-trend-range）
# ═══════════════════════════════════════════════════════════

def zigzag_peaks(close: pd.Series, turn_thresh: float):
    """Zig-Zag 转折点：价格从极值反向波动超阈值记转折点。返回极值点 (idx, price) 列表。"""
    extrema = []
    last_ext_idx, last_ext_price = 0, close.iloc[0]
    trend_dir = 0
    for i in range(1, len(close)):
        p = close.iloc[i]
        if trend_dir >= 0 and p > last_ext_price:
            last_ext_idx, last_ext_price, trend_dir = i, p, 1
        elif trend_dir <= 0 and p < last_ext_price:
            last_ext_idx, last_ext_price, trend_dir = i, p, -1
        elif trend_dir == 1 and p < last_ext_price * (1 - turn_thresh):
            extrema.append((last_ext_idx, last_ext_price))
            last_ext_idx, last_ext_price, trend_dir = i, p, -1
        elif trend_dir == -1 and p > last_ext_price * (1 + turn_thresh):
            extrema.append((last_ext_idx, last_ext_price))
            last_ext_idx, last_ext_price, trend_dir = i, p, 1
    return extrema


def zigzag_labels(close: pd.Series, params: dict) -> pd.Series:
    """阶段1：Zig-Zag 初步趋势标注（满足最小年化收益+时长的波段=趋势）。"""
    n = len(close)
    labels = pd.Series(0, index=close.index)
    extrema = zigzag_peaks(close, params["turn_thresh"])
    pts = [(0, close.iloc[0])] + extrema + [(n - 1, close.iloc[-1])]
    for k in range(len(pts) - 1):
        i0, i1 = pts[k][0], pts[k + 1][0]
        p0, p1 = pts[k][1], pts[k + 1][1]
        days = i1 - i0
        if days < params["min_days"]:
            continue
        ann_ret = (p1 / p0) ** (252.0 / max(days, 1)) - 1.0 if p0 > 0 else 0.0
        if abs(ann_ret) > params["min_ann_ret"]:
            labels.iloc[i0:i1 + 1] = 1
    return labels


def binseg_correction(close: pd.Series, labels: pd.Series) -> pd.Series:
    """阶段2：Binseg 断点修正——趋势内找断点，后半段斜率显著小于前半段→重标震荡。"""
    out = labels.copy()
    segments, in_trend, start = [], False, 0
    for i in range(len(labels)):
        if labels.iloc[i] == 1 and not in_trend:
            start, in_trend = i, True
        elif labels.iloc[i] == 0 and in_trend:
            segments.append((start, i - 1))
            in_trend = False
    if in_trend:
        segments.append((start, len(labels) - 1))

    for s, e in segments:
        if e - s + 1 < 20:
            continue
        best_bp, best_score = None, np.inf
        for bp in range(s + 5, e - 5):
            y1 = close.iloc[s:bp + 1].values
            y2 = close.iloc[bp + 1:e + 1].values
            if len(y1) < 3 or len(y2) < 3:
                continue
            m1, m2 = np.polyfit(np.arange(len(y1)), y1, 1)[0], np.polyfit(np.arange(len(y2)), y2, 1)[0]
            resid = (np.sum((y1 - np.polyval([m1, y1.mean()], np.arange(len(y1)))) ** 2)
                     + np.sum((y2 - np.polyval([m2, y2.mean()], np.arange(len(y2)))) ** 2))
            if resid < best_score:
                best_score, best_bp = resid, bp
        if best_bp is None:
            continue
        y1 = close.iloc[s:best_bp + 1].values
        y2 = close.iloc[best_bp + 1:e + 1].values
        if len(y1) >= 3 and len(y2) >= 3:
            r1 = np.polyfit(np.arange(len(y1)), y1, 1)[0]
            r2 = np.polyfit(np.arange(len(y2)), y2, 1)[0]
            if abs(r2) < 0.5 * abs(r1):
                out.iloc[best_bp + 1:e + 1] = 0
    return out


# ═══════════════════════════════════════════════════════════
# 人工标注解析
# ═══════════════════════════════════════════════════════════

def parse_manual_label(md_path: Path, dates: pd.Series) -> pd.Series:
    """解析人工标注 md（表格：区间 | 状态），展开为逐日序列。

    支持状态词：趋势(上升/下行/1)=1，震荡(0)=0。
    区间格式：2020-01 ~ 2020-06 / 2020-01-01 ~ 2020-06-30 / 2025-05 ~ 至今。
    """
    text = md_path.read_text(encoding="utf-8")
    rows = []
    for line in text.splitlines():
        m = re.match(r"\|\s*\d*\s*\|?\s*([0-9]{4}[-/][0-9]{1,2}([-/][0-9]{1,2})?)\s*~\s*"
                     r"((?:[0-9]{4}[-/][0-9]{1,2}([-/][0-9]{1,2})?)|至今)\s*\|([^|]+)\|", line)
        if not m:
            continue
        start_raw, end_raw, state_raw = m.group(1), m.group(3), m.group(5)
        low = state_raw.lower()
        if "震荡" in state_raw or "range" in low:
            state = 0
        else:  # 趋势/趋势上升/趋势下行
            state = 1
        rows.append((start_raw, end_raw, state, state_raw.strip()))

    if not rows:
        raise ValueError(f"人工标注 md 未解析到任何区间行: {md_path}")

    dates = pd.to_datetime(dates)
    labels = pd.Series(0, index=dates.index)  # 默认震荡（未标注区间）
    def _to_month_end(s):
        d = pd.to_datetime(s)
        return d + pd.offsets.MonthEnd(0) if d.day == 1 else d
    for start_raw, end_raw, state, _desc in rows:
        start = pd.to_datetime(start_raw)
        end = dates.iloc[-1] if end_raw == "至今" else _to_month_end(end_raw)
        mask = (dates >= start) & (dates <= end)
        labels[mask] = state
    return labels


# ═══════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════

def to_segments(dates: pd.Series, labels: pd.Series) -> list[dict]:
    s = labels.reset_index(drop=True)
    d = dates.reset_index(drop=True)
    blocks = (s != s.shift(1)).cumsum()
    segs = []
    for _bid, grp in s.groupby(blocks):
        i0, i1 = grp.index[0], grp.index[-1]
        segs.append({"start": str(d.iloc[i0].date()), "end": str(d.iloc[i1].date()),
                     "state": int(grp.iloc[0]), "days": int(len(grp))})
    return segs


def write_label_md(segs, params, source, out_path: Path):
    lines = [
        "# Regime 标注（监督学习基准）", "",
        f"> 来源：**{source}**",
    ]
    if source == "zigzag_binseg":
        lines += [
            f"> 算法：Zig-Zag（转折 {params['turn_thresh']*100:.0f}% / 最小年化 "
            f"{params['min_ann_ret']*100:.0f}% / 时长 {params['min_days']} 天）+ Binseg 断点修正",
        ]
    lines += ["", "| # | 开始 | 结束 | 状态 | 天数 |", "|---|------|------|------|------|"]
    for i, seg in enumerate(segs, 1):
        lines.append(f"| {i} | {seg['start']} | {seg['end']} | {STATE_LABELS[seg['state']]} | {seg['days']} |")
    n = sum(seg["days"] for seg in segs)
    trend_days = sum(seg["days"] for seg in segs if seg["state"] == 1)
    lines += ["", f"总天数 {n}，趋势 {trend_days}（{trend_days/n*100:.1f}%），"
              f"震荡 {n-trend_days}（{(n-trend_days)/n*100:.1f}%）"]
    out_path.write_text("\n".join(lines), encoding="utf-8")


def write_label_view(dates, close, labels, out_path: Path, title="Regime Label"):
    import plotly.graph_objects as go
    fig = go.Figure()
    s = labels.reset_index(drop=True)
    d = dates.reset_index(drop=True)
    blocks = (s != s.shift(1)).cumsum()
    for _bid, grp in s.groupby(blocks):
        st = int(grp.iloc[0])
        i0, i1 = grp.index[0], grp.index[-1]
        fig.add_shape(type="rect", x0=d.iloc[i0], x1=d.iloc[i1], y0=0, y1=1,
                      xref="x", yref="y domain", fillcolor=COLORS[st],
                      layer="below", line_width=0)
    fig.add_trace(go.Scatter(x=d, y=close.reset_index(drop=True), name="close",
                             line=dict(color="#2980b9", width=1.4)))
    fig.update_layout(template="plotly_white", height=500, hovermode="x unified",
                      margin=dict(l=50, r=30, t=60, b=30), yaxis_title="close", title=title)
    fig.write_html(str(out_path))


def update_manifest(project_dir: Path, source: str, segs: list):
    mp = project_dir / "manifest.json"
    if not mp.exists():
        return
    m = json.loads(mp.read_text(encoding="utf-8-sig"))
    m["label_source"] = source
    total = sum(s["days"] for s in segs)
    trend = sum(s["days"] for s in segs if s["state"] == 1)
    m["label_stats"] = {"segments": len(segs), "total_days": total,
                        "trend_days": trend, "trend_pct": round(trend / total * 100, 1) if total else 0}
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--market-data", required=True, help="核心数据 CSV（如 510300）")
    p.add_argument("--manual-label", help="人工标注 md 路径（提供则转换，否则算法标注）")
    p.add_argument("--turn-thresh", type=float, default=DEFAULT_PARAMS["turn_thresh"])
    p.add_argument("--min-ann-ret", type=float, default=DEFAULT_PARAMS["min_ann_ret"])
    p.add_argument("--min-days", type=int, default=DEFAULT_PARAMS["min_days"])
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    df = pd.read_csv(args.market_data)
    df["date"] = pd.to_datetime(df["date"])
    dates, close = df["date"], df["close"]

    if args.manual_label:
        labels = parse_manual_label(Path(args.manual_label), dates)
        source = "manual"
        params = {"source_md": str(args.manual_label)}
    else:
        params = {"turn_thresh": args.turn_thresh, "min_ann_ret": args.min_ann_ret,
                  "min_days": args.min_days}
        labels = zigzag_labels(close, params)
        labels = binseg_correction(close, labels)
        source = "zigzag_binseg"

    segs = to_segments(dates, labels)
    out_dir = proj / "01_initial"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_label_md(segs, params, source, out_dir / "regime_label.md")
    write_label_view(dates, close, labels, out_dir / "regime_label_view.html",
                     title=f"Regime Label ({source})")
    update_manifest(proj, source, segs)

    # 同时导出逐日标注 CSV（供 evaluate_regime 对齐用）
    pd.DataFrame({"date": dates.dt.strftime("%Y-%m-%d"), "label": labels.values}).to_csv(
        out_dir / "_label_daily.csv", index=False)

    trend_days = sum(s["days"] for s in segs if s["state"] == 1)
    total = sum(s["days"] for s in segs)
    print(json.dumps({"ok": True, "source": source, "segments": len(segs),
                      "total_days": total, "trend_pct": round(trend_days / total * 100, 1),
                      "outputs": [str(out_dir / "regime_label.md"),
                                  str(out_dir / "regime_label_view.html")]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
