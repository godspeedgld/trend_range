"""analysis_002 — 平台突破算法工作原理可视化（单股 002371.SZ 北方华创，2021 年）。

目的：同 analysis_001，直观展示 转折点识别 + HSAR 阻力位 + 突破触发 三环节在
个股 002371.SZ（北方华创）上的工作方式。用户指定单股 + 2021 年（该年有真实突破信号）。

与 analysis_001 差异：单只股票（不做全市场扫描选 TopN），聚焦两段真实突破：
  - 2021-06-17 ~ 07-19：连续突破阻力位 1134.1（23 个信号日）
  - 2021-11-11：突破阻力位 2051.6

输出：result_view.html（K线 + 转折点高低点 + 两条 HSAR 阻力位水平线 + 突破标注）
"""
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
# 公共 K 线可视化模块（与回测报告共用，样式统一）
sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))

from plateau_algo import turning_points, resistance_level, members_asof, PARAMS, LOOKBACK  # noqa: E402

SYMBOL = "002371.SZ"          # 北方华创
PLOT_START = "2020-01-01"     # K线展示起点（含突破前一年形态）
SCAN_START, SCAN_END = "2021-01-01", "2021-12-31"


def scan_signals(g: pd.DataFrame) -> list[dict]:
    """扫描 002371 2021 年突破信号（每日 ≤t 历史，无未来）。"""
    g = g.copy()
    g["date"] = pd.to_datetime(g["date"])
    d0, d1 = pd.Timestamp(SCAN_START), pd.Timestamp(SCAN_END)
    sigs = []
    for b in range(LOOKBACK, len(g)):
        d = g["date"].iloc[b]
        if not (d0 <= d <= d1):
            continue
        if SYMBOL not in members_asof(d):
            continue
        win = g.iloc[b - LOOKBACK + 1:b + 1]
        highs, _ = turning_points(win, PARAMS)
        res = resistance_level(highs, PARAMS)
        if res is None:
            continue
        c = g["close"].iloc[b]
        if c > res * (1 + PARAMS["break_pct"]):
            sigs.append({"date": d, "resistance": res, "close": float(c)})
    return sigs


def annotate_kline(g: pd.DataFrame, sigs: list[dict]) -> "go.Figure":
    """画 002371 K线 + 转折点 + HSAR 阻力位 + 突破标注。

    K 线本体/交互用公共模块 kline_viz（与回测报告统一样式：红涨绿跌 + 拖动条 +
    左键平移 + hover OHLC）；分析特有的转折点/阻力位/突破标注在此叠加。
    """
    import plotly.graph_objects as go
    from kline_viz import add_candlestick, add_hilo_annotation, add_hline, style_kline

    g = g[g["date"] >= PLOT_START].reset_index(drop=True)

    fig = go.Figure()
    # ── K线（公共模块：红涨绿跌 + 细影线 + hover 日期/OHLC）──
    add_candlestick(fig, g, name=SYMBOL)

    # ── 最高 / 最低点（公共模块：红▲/绿▼ + 价格文本）──
    add_hilo_annotation(fig, g)

    # ① 转折点识别（全图窗口高低点）
    highs, lows = turning_points(g, PARAMS)
    if highs:
        fig.add_trace(go.Scatter(
            x=[g["date"].iloc[i] for i, _ in highs], y=[p for _, p in highs],
            mode="markers", name="turning high",
            marker=dict(symbol="triangle-down", size=9, color="#e67e22"),
            hovertemplate="转折高点 %{y:.2f}<extra></extra>"))
    if lows:
        fig.add_trace(go.Scatter(
            x=[g["date"].iloc[i] for i, _ in lows], y=[p for _, p in lows],
            mode="markers", name="turning low",
            marker=dict(symbol="triangle-up", size=9, color="#2980b9"),
            hovertemplate="转折低点 %{y:.2f}<extra></extra>"))

    # ② HSAR 阻力位（每段信号的阻力位水平线，公共模块）
    seen = {}
    for s in sigs:
        r = round(s["resistance"], 1)
        if r not in seen:
            seen[r] = s
    for r in seen:
        add_hline(fig, r, label=f"HSAR resistance {r}",
                  x0=g["date"].iloc[0], x1=g["date"].iloc[-1])

    # ③ 突破日标注（开仓▲样式：K线上方 + 突破价文本 + 距阻力位幅度）
    first_days = {}
    for s in sigs:
        r = round(s["resistance"], 1)
        if r not in first_days:
            first_days[r] = s
    for r, s in first_days.items():
        fig.add_vline(x=s["date"], line_dash="dot", line_color="#8e44ad", line_width=1.5)
        pct = (s["close"] / r - 1) * 100
        fig.add_trace(go.Scatter(
            x=[s["date"]], y=[s["close"] * 1.01],
            mode="markers+text", name=f"breakout @{r:.0f}",
            marker=dict(symbol="triangle-up", size=14, color="#8e44ad",
                        line=dict(width=1, color="#ffffff")),
            text=[f"BREAK {s['close']:.0f} (+{pct:.0f}%)"],
            textposition="top center", textfont=dict(size=10, color="#8e44ad"),
            hovertemplate=(f"突破 {s['date'].date()}<br>收盘 {s['close']:.2f} "
                           f"&gt; 阻力位 {r:.2f}×1.03 (+{pct:.0f}%)<extra></extra>")))

    # 布局与交互（公共模块：拖动条 + 左键平移 + hover）
    style_kline(fig, title=f"{SYMBOL} v1·HSAR 突破 | 2021 两段突破：{len(sigs)} 个信号日",
                height=600)
    return fig


# ═══════════════════════════════════════════════════════════
# v2.7：趋势线系统可视化（线速率断线 + 单点提前成线）
#   阻力线=红色斜线（OLS 拟合高点）+ 上通道带；支撑线=绿色斜线 + 下通道带
#   断线两条件（2×dist / 速率超限）满足其一即断；速率断线的线段末端标 RATE
#   close_rate 提前成线（单点+收盘+速率）的线段起点标 ◇CR
#   突破/跌破=★（紫/灰）；转折点=▲（橙高/蓝低）
# ═══════════════════════════════════════════════════════════

def annotate_kline_v27(g: pd.DataFrame, d0, d1, events, lines, title: str) -> "go.Figure":
    """v2.7 趋势线可视化：K线 + 斜阻力/支撑线 + 通道带 + 信号★ + 转折点▲ + 速率断线/提前成线标注。"""
    import plotly.graph_objects as go
    from kline_viz import add_candlestick, style_kline

    seg = g[(g["date"] >= d0) & (g["date"] <= d1)].reset_index(drop=True)
    dates_all = g["date"].reset_index(drop=True)
    fig = go.Figure()
    add_candlestick(fig, seg, name=SYMBOL)

    D0, D1 = pd.Timestamp(d0), pd.Timestamp(d1)
    # 线结束原因（v2.6）：按 (kind, i0, i1) 匹配 resist_end/support_end 事件
    reason_by_line = {}
    for ev in events:
        if ev["type"] in ("resist_end", "support_end"):
            reason_by_line[(ev["kind"], ev["i0"], ev["i1"])] = ev.get("reason", "dist_break")
    # ── 阻力线/支撑线（斜线段；活跃线实线加粗，已结束点线）──
    for ln in lines:
        i0, i1 = ln["i0"], min(ln["i1"], len(g) - 1)
        x0, x1 = dates_all.iloc[i0], dates_all.iloc[i1]
        if pd.Timestamp(x1) < D0 or pd.Timestamp(x0) > D1:
            continue
        y0 = ln["a"] + ln["b"] * i0
        y1 = ln["a"] + ln["b"] * i1
        is_r = ln["kind"] == "R"
        color = "#c0392b" if is_r else "#27ae60"
        w = 2.4 if ln.get("active") else 1.4
        dash = "solid" if ln.get("active") else "dot"
        fig.add_shape(type="line", x0=x0, x1=x1, y0=y0, y1=y1,
                      line=dict(color=color, width=w, dash=dash))
        tag = "R" if is_r else "S"
        fig.add_annotation(x=x0, y=y0, text=f"{tag}",
                           showarrow=False, font=dict(size=10, color=color),
                           yanchor="bottom" if is_r else "top")
        # v2.6：速率断线（或两者同时）的线段末端标 RATE，与普通距离断线区分
        reason = reason_by_line.get((ln["kind"], ln["i0"], ln["i1"]))
        if reason in ("rate_break", "both") and not ln.get("active"):
            fig.add_annotation(x=x1, y=y1, text="RATE",
                               showarrow=False, font=dict(size=9, color=color),
                               yanchor="bottom" if is_r else "top", xanchor="right")
        # v2.7：close_rate 提前成线（单点+收盘+速率）的线段起点标 ◇CR（与 R/S 标签对侧避免重叠）
        if ln.get("formed") == "close_rate":
            fig.add_annotation(x=x0, y=y0, text="◇CR",
                               showarrow=False, font=dict(size=9, color="#d35400"),
                               yanchor="top" if is_r else "bottom", xanchor="right")

    # ── 突破/跌破信号 ★（每线首破）──
    for ev in events:
        d = pd.Timestamp(ev["date"])
        if not (D0 <= d <= D1):
            continue
        t = ev["type"]
        if t == "break_up":
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["price"] * 1.01], mode="markers+text", name="突破信号",
                marker=dict(symbol="star", size=15, color="rgba(142,68,173,0.4)",
                            line=dict(width=1.5, color="#8e44ad")),
                text=[f"UP {ev['price']:.0f}"], textposition="top center",
                textfont=dict(size=9, color="#8e44ad"),
                hovertemplate=(f"突破 {d.date()}<br>high {ev['price']:.0f} > "
                               f"(线{ev['line_val']:.0f}+距{ev['dist']:.0f})×1.03<extra></extra>")))
        elif t == "break_down":
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["price"] * 0.99], mode="markers+text", name="跌破信号",
                marker=dict(symbol="star", size=13, color="rgba(127,140,141,0.4)",
                            line=dict(width=1.5, color="#7f8c8d")),
                text=[f"DN {ev['price']:.0f}"], textposition="bottom center",
                textfont=dict(size=9, color="#7f8c8d"),
                hovertemplate=(f"跌破 {d.date()}<br>low {ev['price']:.0f} < "
                               f"(线{ev['line_val']:.0f}−距{ev['dist']:.0f})×0.97<extra></extra>")))

    # ── 转折点 ▲ ──
    highs, lows = turning_points(seg, PARAMS)
    if highs:
        fig.add_trace(go.Scatter(
            x=[seg["date"].iloc[i] for i, _ in highs], y=[p for _, p in highs],
            mode="markers", name="turning high",
            marker=dict(symbol="triangle-down", size=9, color="#e67e22"),
            hovertemplate="转折高点 %{y:.2f}<extra></extra>"))
    if lows:
        fig.add_trace(go.Scatter(
            x=[seg["date"].iloc[i] for i, _ in lows], y=[p for _, p in lows],
            mode="markers", name="turning low",
            marker=dict(symbol="triangle-up", size=9, color="#2980b9"),
            hovertemplate="转折低点 %{y:.2f}<extra></extra>"))

    style_kline(fig, title=title, height=600)
    return fig


# ═══════════════════════════════════════════════════════════
# v2：平台重锚定区间突破（plateau_algo_v2）可视化
#   平台=半透明矩形；转折点=▲（橙高/蓝低）；突破=★紫；最高/最低=●（红/绿）
# ═══════════════════════════════════════════════════════════

def annotate_kline_v2(g: pd.DataFrame, d0, d1, events, platforms, title: str) -> "go.Figure":
    """v2 平台可视化：K线 + 平台矩形 + 转折点▲ + 突破★ + 最高最低●（形状区分）。"""
    import plotly.graph_objects as go
    from kline_viz import add_candlestick, style_kline

    seg = g[(g["date"] >= d0) & (g["date"] <= d1)].reset_index(drop=True)
    fig = go.Figure()
    add_candlestick(fig, seg, name=SYMBOL)

    # ── 平台支撑线/阻力线（线段：平台起止范围内；新平台新的线段；无矩形）──
    D0, D1 = pd.Timestamp(d0), pd.Timestamp(d1)
    for p in platforms:
        s, e = p.get("start_date"), p.get("end_date")
        if s is None or e is None or pd.Timestamp(e) < D0 or pd.Timestamp(s) > D1:
            continue
        rs, re_ = max(pd.Timestamp(s), D0), min(pd.Timestamp(e), D1)   # 裁剪到窗口
        # 阻力线 R（红实线段，平台长度）
        if p.get("R"):
            fig.add_shape(type="line", x0=rs, x1=re_, y0=p["R"], y1=p["R"],
                          line=dict(color="#c0392b", width=2.2))
            fig.add_annotation(x=rs, y=p["R"], text=f"R {p['R']:.0f}",
                               showarrow=False, font=dict(size=11, color="#c0392b"), yanchor="bottom")
        # 支撑线 S（绿实线段，平台长度）
        if p.get("S"):
            fig.add_shape(type="line", x0=rs, x1=re_, y0=p["S"], y1=p["S"],
                          line=dict(color="#27ae60", width=2.2))
            fig.add_annotation(x=rs, y=p["S"], text=f"S {p['S']:.0f}",
                               showarrow=False, font=dict(size=11, color="#27ae60"), yanchor="top")

    # ── v2.4 突破事件三态：pending(★信号) / revoked(×假突破回退) / confirmed(★真突破确立) ──
    for ev in events:
        d = pd.Timestamp(ev["date"])
        if not (pd.Timestamp(d0) <= d <= pd.Timestamp(d1)):
            continue
        t = ev["type"]
        if t == "pending_break":
            up = ev["btype"] == "up"
            ref = f"R {ev['R']:.0f}" if (up and ev.get("R")) else (f"S {ev['S']:.0f}" if ev.get("S") else "")
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["close"] * (1.01 if up else 0.99)], mode="markers+text",
                name="v2.4 突破信号",
                marker=dict(symbol="star", size=15,
                            color="rgba(142,68,173,0.35)" if up else "rgba(127,140,141,0.35)",
                            line=dict(width=1.5, color="#8e44ad" if up else "#7f8c8d")),
                text=[f"SIG {ev['close']:.0f}"], textposition="top center" if up else "bottom center",
                textfont=dict(size=9, color="#8e44ad" if up else "#7f8c8d"),
                hovertemplate=(f"突破信号 {d.date()}<br>收盘 {ev['close']:.2f} vs "
                               + (f"阻力位 {ev['R']:.2f}×1.03" if up else f"支撑位 {ev['S']:.2f}×0.97")
                               + "<extra></extra>")))
        elif t == "break_revoked":
            fig.add_trace(go.Scatter(
                x=[d], y=[seg["low"].min() * 1.02], mode="markers",
                name="假突破回退",
                marker=dict(symbol="x", size=10, color="#95a5a6"),
                hovertemplate=f"假突破回退 {d.date()}（旧平台恢复）<extra></extra>"))
        elif t in ("up_break", "down_break"):
            up = t == "up_break"
            fig.add_trace(go.Scatter(
                x=[d], y=[ev["U"] if up else ev["L"]], mode="markers+text",
                name="真突破确立",
                marker=dict(symbol="star", size=16, color="#8e44ad" if up else "#34495e",
                            line=dict(width=2, color="#ffffff")),
                text=["CONFIRMED"], textposition="top center",
                textfont=dict(size=9, color="#8e44ad" if up else "#34495e"),
                hovertemplate=(f"新平台确立 {d.date()}<br>U={ev['U']:.0f} L={ev['L']:.0f} "
                               f"BP={ev['bp']:.0f}<extra></extra>")))

    # ── 转折点 ▲（v1 同款：橙高/蓝低，三角形族）──
    highs, lows = turning_points(seg, PARAMS)
    if highs:
        fig.add_trace(go.Scatter(
            x=[seg["date"].iloc[i] for i, _ in highs], y=[p for _, p in highs],
            mode="markers", name="turning high",
            marker=dict(symbol="triangle-down", size=9, color="#e67e22"),
            hovertemplate="转折高点 %{y:.2f}<extra></extra>"))
    if lows:
        fig.add_trace(go.Scatter(
            x=[seg["date"].iloc[i] for i, _ in lows], y=[p for _, p in lows],
            mode="markers", name="turning low",
            marker=dict(symbol="triangle-up", size=9, color="#2980b9"),
            hovertemplate="转折低点 %{y:.2f}<extra></extra>"))

    # ── 最高/最低 ●（圆形族，与三角/星形区分）──
    hi_i, lo_i = int(seg["high"].idxmax()), int(seg["low"].idxmin())
    fig.add_trace(go.Scatter(
        x=[seg["date"].iloc[hi_i]], y=[seg["high"].iloc[hi_i]],
        mode="markers+text", name="period high",
        marker=dict(symbol="circle", size=12, color="#e74c3c",
                    line=dict(width=1.5, color="#ffffff")),
        text=[f"最高 {seg['high'].iloc[hi_i]:.0f}"], textposition="top center",
        textfont=dict(size=10, color="#e74c3c")))
    fig.add_trace(go.Scatter(
        x=[seg["date"].iloc[lo_i]], y=[seg["low"].iloc[lo_i]],
        mode="markers+text", name="period low",
        marker=dict(symbol="circle", size=12, color="#2ecc71",
                    line=dict(width=1.5, color="#ffffff")),
        text=[f"最低 {seg['low'].iloc[lo_i]:.0f}"], textposition="bottom center",
        textfont=dict(size=10, color="#2ecc71")))

    style_kline(fig, title=title, height=600)
    return fig


def main():
    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])
    g = market[market["symbol"] == SYMBOL].sort_values("date").reset_index(drop=True)
    print(f"{SYMBOL}: {len(g)} 根 | {g['date'].min().date()} ~ {g['date'].max().date()}")

    # ── v1：HSAR 滑动窗口（2021 双突破图）──
    sigs = scan_signals(g)
    print(f"\n[v1] 2021 突破信号: {len(sigs)} 个")
    if sigs:
        df = pd.DataFrame([{"date": s["date"], "resistance": s["resistance"],
                            "close": s["close"]} for s in sigs])
        print(df.groupby([df["resistance"].round(1)]).agg(
            n=("close", "count"), 首突破=("date", "min"), 末突破=("date", "max"),
            max_close=("close", "max")).to_string())

    # ── v2.7：趋势线系统（OLS 支撑/阻力线 + 通道带 + 固定 3% + 线速率断线 + 单点提前成线）──
    from plateau_algo_v2 import run_trendline_breakout
    events, lines, _ = run_trendline_breakout(g)
    ups = [e for e in events if e["type"] == "break_up"]
    dns = [e for e in events if e["type"] == "break_down"]
    ends = [e for e in events if e["type"] in ("resist_end", "support_end")]
    rate_ends = [e for e in ends if e.get("reason") in ("rate_break", "both")]
    cr_lines = [l for l in lines if l.get("formed") == "close_rate"]
    print(f"\n[v2.7] 向上突破 {len(ups)} | 向下跌破 {len(dns)} | 线段 {len(lines)} | 断线 {len(ends)}（速率断线 {len(rate_ends)}）| 提前成线 {len(cr_lines)}")
    for e in ups:
        print(f"  UP  {str(e['date'])[:10]}  line={e['line_val']:.0f} dist={e['dist']:.0f} high={e['price']:.0f}")
    for e in dns:
        print(f"  DN  {str(e['date'])[:10]}  line={e['line_val']:.0f} dist={e['dist']:.0f} low={e['price']:.0f}")
    for e in rate_ends:
        print(f"  速率断线 {e['kind']}  {str(e['date'])[:10]}  rate={e['rate']:.4f}")
    for l in cr_lines:
        print(f"  提前成线 {l['kind']}  {l['d0'].date()} → {l['d1'].date()}  rate={l['rate']:.4f}")

    # ── 可视化：v1 一张 + v2.7 两张（斜趋势线 + 通道带 + 信号★ + 速率断线/提前成线标注）──
    fig1 = annotate_kline(g, sigs)
    fig2 = annotate_kline_v27(g, "2019-07-01", "2021-12-31", events, lines,
                              f"{SYMBOL} v2.7 趋势线 | 2019-2021：2021-01-19→08-16 阻力线贯穿空窗（05-27 突破）、2021-09-01 速率断线 RATE")
    fig3 = annotate_kline_v27(g, "2022-06-01", "2026-08-21", events, lines,
                              f"{SYMBOL} v2.7 趋势线 | 2022-2026：2024-09-27 突破（9·24首日）、2025 多次突破/跌破")

    parts = [fig1.to_html(full_html=False, include_plotlyjs=True, div_id="fig_v1"),
             fig2.to_html(full_html=False, include_plotlyjs=False, div_id="fig_v27a"),
             fig3.to_html(full_html=False, include_plotlyjs=False, div_id="fig_v27b")]
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>平台突破算法原理 — {SYMBOL}</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;background:#fff;}}</style>
</head><body>
<h1>平台突破算法工作原理 — {SYMBOL}（北方华创）</h1>
<p><b>v1（HSAR 滑动窗口）</b>：红虚线=阻力位（回溯一年高点聚集）；橙▼/蓝▲=转折高低点；紫★=突破日。</p>
<p><b>v2.7（趋势线系统 + 线速率断线 + 单点提前成线）</b>：<b>红色斜线=阻力线</b>（高点 OLS 拟合；实线=当前活跃，点线=已结束）；
<b>绿色斜线=支撑线</b>（低点 OLS）；
★紫=突破信号（high &gt; (阻力线+阻力距)×1.03），★灰=跌破信号（low &lt; (支撑线−支撑距)×0.97）；
▲=转折点（橙高/蓝低，拟合线的输入点）。
<b>断线两条件满足其一即断线</b>（v2.6）：① 新高点距线 &gt; 2×阻力距；② 加入新高点后拟合线速率
阻力 &gt; +1%/bar / 支撑 &lt; −1%/bar（涨/跌太快，线段末端标 <b>RATE</b>）。
<b>单点提前成线</b>（v2.7）：单点待成线时，若某根 K 线 close 超前高/前低 ±3% 且上涨/下跌速率超 1%/bar，
该 close 与前高/前低构成线（线段起点标 <b>◇CR</b>）。</p>
{''.join(parts)}
</body></html>"""
    out = HERE / "result_view.html"
    out.write_text(body, encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
