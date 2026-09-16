"""analysis_006 — v3 水平阻力带/支撑带算法 多标的测试（5 只沪深300成分）。

目的：v2.7（plateau_algo_v2.py）锁死后，用户指定 v3 新范式——转折点价格聚类的**水平带**
（±5% 带宽 + 递归合并 + 计数=突破程度）。在 5 只标的上做首测：
  002371 北方华创（analysis_002 基准股）+ analysis_003 同组四标的（600362/688981/601336/300059），
便于与 v2.7 的信号分布直接对照。

每只一张全历史 K 线图，标注：
  · 阻力带=红色半透明横矩形 / 支撑带=绿色半透明横矩形（实边=活跃带，虚边=已被合并剔除的旧带）
    标签 R×n / S×n = 带计数（n 个转折高点/低点合并）
  · ★紫=向上突破（收盘 > 阻力带上边界，标签 U×n=突破程度）/ ★灰=向下跌破（D×n）
  · ▲橙=转折高点 / ▲蓝=转折低点（同 v2.7 转折点）

输出：result_view.html（统计表 + 五标的各一张图）
"""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))

from plateau_algo_v3 import run_band_breakout, BandBreakout  # noqa: E402
from kline_viz import add_candlestick, style_kline           # noqa: E402

SYMBOLS = [
    ("002371.SZ", "北方华创"),
    ("600362.SH", "江西铜业"),
    ("688981.SH", "中芯国际"),
    ("601336.SH", "新华保险"),
    ("300059.SZ", "东方财富"),
]

R_FILL = "rgba(192,57,43,0.10)"     # 阻力带填充
S_FILL = "rgba(39,174,96,0.10)"     # 支撑带填充


def annotate_v3(g: pd.DataFrame, name: str, title: str):
    """单标的 v3 带状可视化。返回 (fig, stats_dict)。"""
    import plotly.graph_objects as go

    g = g.reset_index(drop=True)
    events, bands, bb = run_band_breakout(g)
    ups = [e for e in events if e["type"] == "break_up"]
    dns = [e for e in events if e["type"] == "break_down"]

    # 转折点（同 v2.7 逻辑，重跑一遍只取点位用于标注）
    tp_bb = BandBreakout()
    tps = []          # (i, price, kind)
    for _, row in g.iterrows():
        tp_bb.i += 1
        c, h, l = float(row["close"]), float(row["high"]), float(row["low"])
        if not tp_bb._started:
            tp_bb._started = True
            tp_bb._bars.append(c)
            continue
        tp_bb._bars.append(c)
        s = pd.Series(__import__("numpy").array(tp_bb._bars))
        ma, sd = s.rolling(20).mean().iloc[-1], s.rolling(20).std().iloc[-1]
        ev = tp_bb._turning_step(h, l, ma + 1.0 * sd, ma - 1.0 * sd)
        if ev is not None:
            tps.append(ev)

    fig = go.Figure()
    add_candlestick(fig, g, name=name)

    # ── 带矩形（横跨 最早点日 → 结束/当前）──
    for b in bands:
        color = R_FILL if b["kind"] == "R" else S_FILL
        edge = "#c0392b" if b["kind"] == "R" else "#27ae60"
        dash = "solid" if b["active"] else "dot"
        w = 1.6 if b["active"] else 0.7
        fig.add_shape(type="rect", x0=b["d0"], x1=b["d1"], y0=b["lo"], y1=b["hi"],
                      fillcolor=color, line=dict(color=edge, width=w, dash=dash),
                      layer="below")
        if b["count"] >= 2 or b["active"]:      # 单点旧带不标字，避免过密
            fig.add_annotation(x=b["d0"], y=b["hi"],
                               text=f"{b['kind']}×{b['count']}", showarrow=False,
                               font=dict(size=9, color=edge), yanchor="bottom")

    # ── 突破/跌破事件 ──
    for ev in ups:
        d = pd.Timestamp(ev["date"])
        fig.add_trace(go.Scatter(
            x=[d], y=[ev["hi"]], mode="markers+text", name="突破",
            marker=dict(symbol="star", size=13, color="rgba(142,68,173,0.45)",
                        line=dict(width=1.5, color="#8e44ad")),
            text=[f"U×{ev['degree']}"], textposition="top center",
            textfont=dict(size=9, color="#8e44ad"),
            hovertemplate=(f"突破 {d.date()}<br>收盘 {ev['close']:.2f} > 上界 {ev['hi']:.2f}"
                           f"<br>带计数 {ev['count']}<extra></extra>")))
    for ev in dns:
        d = pd.Timestamp(ev["date"])
        fig.add_trace(go.Scatter(
            x=[d], y=[ev["lo"]], mode="markers+text", name="跌破",
            marker=dict(symbol="star", size=12, color="rgba(127,140,141,0.45)",
                        line=dict(width=1.5, color="#7f8c8d")),
            text=[f"D×{ev['degree']}"], textposition="bottom center",
            textfont=dict(size=9, color="#7f8c8d"),
            hovertemplate=(f"跌破 {d.date()}<br>收盘 {ev['close']:.2f} < 下界 {ev['lo']:.2f}"
                           f"<br>带计数 {ev['count']}<extra></extra>")))

    # ── 转折点 ──
    hi_tps = [(i, p) for i, p, k in tps if k == "H"]
    lo_tps = [(i, p) for i, p, k in tps if k == "L"]
    dates_all = g["date"]
    if hi_tps:
        fig.add_trace(go.Scatter(
            x=[dates_all.iloc[i] for i, _ in hi_tps], y=[p for _, p in hi_tps],
            mode="markers", name="转折高点",
            marker=dict(symbol="triangle-down", size=7, color="#e67e22", opacity=0.8),
            hovertemplate="转折高点 %{y:.2f}<extra></extra>"))
    if lo_tps:
        fig.add_trace(go.Scatter(
            x=[dates_all.iloc[i] for i, _ in lo_tps], y=[p for _, p in lo_tps],
            mode="markers", name="转折低点",
            marker=dict(symbol="triangle-up", size=7, color="#2980b9", opacity=0.8),
            hovertemplate="转折低点 %{y:.2f}<extra></extra>"))

    style_kline(fig, title=title, height=600)

    import numpy as np
    deg_up = pd.Series([e["degree"] for e in ups])
    dist = "/".join(str(int(((deg_up == 1).sum(),
                             (deg_up == 2).sum(),
                             deg_up.between(3, 5).sum(),
                             (deg_up >= 6).sum())[i])) for i in range(4))
    stats = {
        "区间": f"{g['date'].min().date()}~{g['date'].max().date()}",
        "转折点H/L": f"{len(hi_tps)}/{len(lo_tps)}",
        "带总数(含合并前)": len(bands),
        "活跃带R/S": f"{len(bb.r_bands)}/{len(bb.s_bands)}",
        "最大带计数": max((b['count'] for b in bands), default=0),
        "向上突破": len(ups),
        "向下跌破": len(dns),
        "突破程度分布(1/2/3-5/6+)": dist,
    }
    return fig, stats


def main() -> int:
    panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])

    html_parts = []
    all_stats = []
    for sym, cname in SYMBOLS:
        g = panel[panel["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if not len(g):
            print(f"[skip] {sym} 无数据")
            continue
        fig, stats = annotate_v3(g, cname, f"{cname} {sym} — v3 水平带系统（±5% 递归合并）")
        html_parts.append(f"<h2>{cname}（{sym}）</h2>" + fig.to_html(
            full_html=False, include_plotlyjs=False))
        all_stats.append({"标的": f"{cname} {sym}", **stats})
        print(f"[done] {sym} {cname}: up {stats['向上突破']} dn {stats['向下跌破']} "
              f"max计数 {stats['最大带计数']}")

    st = pd.DataFrame(all_stats)
    table = st.to_html(index=False, border=0)
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_006 — v3 水平带算法多标的测试</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:20px;background:#fff;}}
table{{border-collapse:collapse;margin:14px 0;}}
th,td{{border:1px solid #d6dae1;padding:6px 12px;font-size:13px;}}
th{{background:#f3f5f8;}}
.note{{color:#6b7480;font-size:13px;}}
</style></head><body>
<h1>analysis_006 — v3 水平阻力带/支撑带算法 多标的测试</h1>
<div class="note">转折点同 v2.7（BB20/1.0）；转折点价 ±5% 构成带，重叠递归合并（合并后线=点均值）；
收盘 &gt; 阻力带上界 = 突破，程度 = 带计数；收盘 &lt; 支撑带下界 = 跌破。
红矩形=阻力带 / 绿矩形=支撑带（实边活跃、虚边已并入新带）；★U×n/★D×n=突破/跌破程度。</div>
<h2>统计总览</h2>
{table}
{''.join(html_parts)}
</body></html>"""
    (HERE / "result_view.html").write_text(body, encoding="utf-8")
    print(st.to_string(index=False))
    print(f"\n输出: {HERE / 'result_view.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
