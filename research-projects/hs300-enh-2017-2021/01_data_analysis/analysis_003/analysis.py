"""analysis_003 — 平台突破 v2.7 多标的测试（4 只沪深300成分）。

目的：算法 v2.7（趋势线系统 + 线速率断线 + 单点提前成线）锁定后，在 4 只标的
上做可复现性测试：江西铜业 / 中芯国际 / 新华保险 / 东方财富。
每只一张全历史 K 线 + v2.7 趋势线图（红涨绿跌 + 拖动条缩放），标注：
  · 阻力线=红斜线 / 支撑线=绿斜线（实线=活跃，点线=已结束）
  · ◇CR=close_rate 提前成线（单点+收盘+速率）；RATE=速率断线
  · ★=突破/跌破信号（紫/灰）；▲=转折高低点（橙高/蓝低）

输出：result_view.html（四标的各一张图 + 统计）
"""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))

from plateau_algo import turning_points, PARAMS          # noqa: E402
from plateau_algo_v2 import run_trendline_breakout       # noqa: E402

SYMBOLS = [
    ("600362.SH", "江西铜业"),
    ("688981.SH", "中芯国际"),
    ("601336.SH", "新华保险"),
    ("300059.SZ", "东方财富"),
]


def annotate_v27(g: pd.DataFrame, name: str, title: str):
    """单标的 v2.7 趋势线可视化。返回 (fig, stats_dict)。"""
    import plotly.graph_objects as go
    from kline_viz import add_candlestick, style_kline

    events, lines, _ = run_trendline_breakout(g)
    ups = [e for e in events if e["type"] == "break_up"]
    dns = [e for e in events if e["type"] == "break_down"]
    ends = [e for e in events if e["type"] in ("resist_end", "support_end")]
    rate_ends = [e for e in ends if e.get("reason") in ("rate_break", "both")]
    cr_lines = [l for l in lines if l.get("formed") == "close_rate"]

    reason_by_line = {}
    for ev in ends:
        reason_by_line[(ev["kind"], ev["i0"], ev["i1"])] = ev.get("reason", "dist_break")

    g = g.reset_index(drop=True)
    dates_all = g["date"]
    n = len(g)
    fig = go.Figure()
    add_candlestick(fig, g, name=name)

    for ln in lines:
        i0, i1 = ln["i0"], min(ln["i1"], n - 1)
        x0, x1 = dates_all.iloc[i0], dates_all.iloc[i1]
        y0 = ln["a"] + ln["b"] * i0
        y1 = ln["a"] + ln["b"] * i1
        is_r = ln["kind"] == "R"
        color = "#c0392b" if is_r else "#27ae60"
        w = 2.4 if ln.get("active") else 1.4
        dash = "solid" if ln.get("active") else "dot"
        fig.add_shape(type="line", x0=x0, x1=x1, y0=y0, y1=y1,
                      line=dict(color=color, width=w, dash=dash))
        fig.add_annotation(x=x0, y=y0, text="R" if is_r else "S",
                           showarrow=False, font=dict(size=10, color=color),
                           yanchor="bottom" if is_r else "top")
        reason = reason_by_line.get((ln["kind"], ln["i0"], ln["i1"]))
        if reason in ("rate_break", "both") and not ln.get("active"):
            fig.add_annotation(x=x1, y=y1, text="RATE",
                               showarrow=False, font=dict(size=9, color=color),
                               yanchor="bottom" if is_r else "top", xanchor="right")
        if ln.get("formed") == "close_rate":
            fig.add_annotation(x=x0, y=y0, text="◇CR",
                               showarrow=False, font=dict(size=9, color="#d35400"),
                               yanchor="top" if is_r else "bottom", xanchor="right")

    for ev in events:
        d = pd.Timestamp(ev["date"])
        if ev["type"] == "break_up":
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["price"] * 1.01], mode="markers+text", name="突破信号",
                marker=dict(symbol="star", size=14, color="rgba(142,68,173,0.4)",
                            line=dict(width=1.5, color="#8e44ad")),
                text=[f"UP {ev['price']:.0f}"], textposition="top center",
                textfont=dict(size=9, color="#8e44ad"),
                hovertemplate=(f"突破 {d.date()}<br>high {ev['price']:.0f} > "
                               f"(线{ev['line_val']:.0f}+距{ev['dist']:.0f})×1.03<extra></extra>")))
        elif ev["type"] == "break_down":
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["price"] * 0.99], mode="markers+text", name="跌破信号",
                marker=dict(symbol="star", size=13, color="rgba(127,140,141,0.4)",
                            line=dict(width=1.5, color="#7f8c8d")),
                text=[f"DN {ev['price']:.0f}"], textposition="bottom center",
                textfont=dict(size=9, color="#7f8c8d"),
                hovertemplate=(f"跌破 {d.date()}<br>low {ev['price']:.0f} < "
                               f"(线{ev['line_val']:.0f}−距{ev['dist']:.0f})×0.97<extra></extra>")))

    highs, lows = turning_points(g, PARAMS)
    if highs:
        fig.add_trace(go.Scatter(
            x=[dates_all.iloc[i] for i, _ in highs], y=[p for _, p in highs],
            mode="markers", name="转折高点",
            marker=dict(symbol="triangle-down", size=8, color="#e67e22"),
            hovertemplate="转折高点 %{y:.2f}<extra></extra>"))
    if lows:
        fig.add_trace(go.Scatter(
            x=[dates_all.iloc[i] for i, _ in lows], y=[p for _, p in lows],
            mode="markers", name="转折低点",
            marker=dict(symbol="triangle-up", size=8, color="#2980b9"),
            hovertemplate="转折低点 %{y:.2f}<extra></extra>"))

    style_kline(fig, title=title, height=600)

    stats = {"lines": len(lines), "ups": len(ups), "dns": len(dns),
             "cr": len(cr_lines), "rate": len(rate_ends)}
    return fig, stats


def main():
    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])

    sections, html_parts = [], []
    first = True
    for sym, disp in SYMBOLS:
        g = market[market["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if len(g) == 0:
            print(f"{sym} {disp}: ❌ 无数据")
            continue
        title = f"{sym} {disp} | v2.7 平台突破 | {g['date'].min().date()} ~ {g['date'].max().date()}（{len(g)} 根）"
        fig, st = annotate_v27(g, disp, title)
        line = (f"{disp} {sym}：线段 {st['lines']} | 向上突破 {st['ups']} | 向下跌破 {st['dns']} "
                f"| 提前成线 ◇CR {st['cr']} | 速率断线 RATE {st['rate']}")
        print(line)
        sections.append(line)
        html_parts.append(f"<h2>{sym} {disp}</h2><p class='stats'>{line}</p>")
        html_parts.append(fig.to_html(full_html=False,
                                      include_plotlyjs=first,
                                      div_id=f"fig_{sym.replace('.', '_')}"))
        first = False

    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>平台突破 v2.7 多标的测试</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;background:#fff;}}
h2{{border-bottom:1px solid #ddd;padding-bottom:6px;margin-top:36px;}}
.stats{{color:#555;font-size:13px;margin:4px 0 10px;}}</style>
</head><body>
<h1>平台突破 v2.7 多标的测试（4 只沪深300成分）</h1>
<p><b>v2.7 趋势线系统</b>：<b>红色斜线=阻力线</b>（高点 OLS；实线=活跃，点线=已结束）；<b>绿色斜线=支撑线</b>（低点 OLS）；
★紫=突破信号（high &gt; (阻力线+阻力距)×1.03），★灰=跌破信号（low &lt; (支撑线−支撑距)×0.97）；▲=转折高低点（橙高/蓝低）。</p>
<p><b>断线两条件满足其一即断</b>：① 新高点距线 &gt; 2×阻力距；② 加入新高点后拟合线速率 阻力 &gt; +1%/bar / 支撑 &lt; −1%/bar（末端标 <b>RATE</b>）。</p>
<p><b>单点提前成线</b>：单点待成线时，某根 K 线 close 超前高/前低 ±3% 且速率超 1%/bar → close 与前高/前低成线（起点标 <b>◇CR</b>）。</p>
{''.join(html_parts)}
</body></html>"""
    out = HERE / "result_view.html"
    out.write_text(body, encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
