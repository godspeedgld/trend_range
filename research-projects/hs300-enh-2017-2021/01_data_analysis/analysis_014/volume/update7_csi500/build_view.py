"""analysis_014/volume 更新七 可视化 — W2 配方在 沪深300池 vs 中证500池 的对照。

⚠ 口径（skill 指标铁律）：净值/指标一律取 **trades 直接推算**的口径
   （nav_from_trades / metrics_from_trades，固定名义不复利 NAV = 1 + Σ(0.1×单笔收益)），
   **不用**引擎 equity_curve.csv ——后者是复利净值路径，且自带归因近似
   （平仓仓的"决策日收盘→次日开盘"段不归因、成本时点前移一天）。
   两个口径在 2021 年前吻合、之后急剧分叉（本例 2026-08-20：trades 0.843 vs equity 1.811）。

布局 2×2：净值 / 单笔收益分布（看"右尾是否还在"）/ 年度收益 / 回撤。
配色：#2b6cb0 沪深300池W2(基准) · #b7791f 中证500池(沪深300闸门) · #c53030 中证500池(中证500闸门)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
UPD6 = HERE.parent / "update6_combo_asof"
BLUE, AMBER, RED, GRAY = "#2b6cb0", "#b7791f", "#c53030", "#718096"

RUNS = [
    ("沪深300池 · 沪深300闸门（W2 基准）", UPD6 / "runs/W2/backtest_logs", BLUE),
    ("中证500池 · 沪深300闸门", HERE / "runs/W2_HS300gate/backtest_logs", AMBER),
    ("中证500池 · 中证500闸门", HERE / "runs/W2_CSI500gate/backtest_logs", RED),
]


def load(d: Path):
    n = pd.read_csv(d / "nav_from_trades.csv")
    n["date"] = pd.to_datetime(n["date"])
    m = pd.read_csv(d / "metrics_from_trades.csv").iloc[0]
    t = pd.read_csv(d / "trades_paired.csv")["return_pct"]
    yr = pd.read_csv(d / "yearly_returns_from_trades.csv", index_col=0)["ret_pct"]
    return n, m, t, yr


def main():
    D = {lab: load(d) for lab, d, _ in RUNS}

    fig = make_subplots(rows=2, cols=2,
                        subplot_titles=("净值（trades 口径 · 固定名义不复利）",
                                        "单笔收益分布（右尾是否还在？）",
                                        "年度收益 %（trades 口径）", "回撤 %（trades 口径）"),
                        vertical_spacing=0.15, horizontal_spacing=0.09)

    # ── 净值 ──
    for lab, _, c in RUNS:
        n = D[lab][0]
        fig.add_scatter(x=n["date"], y=n["nav"], mode="lines", name=lab,
                        line=dict(color=c, width=2.2), legendgroup=lab, showlegend=True,
                        row=1, col=1,
                        hovertemplate="%{x|%Y-%m-%d} 净值 %{y:.3f}<extra>" + lab + "</extra>")
    fig.add_hline(y=1.0, line=dict(color=GRAY, width=1, dash="dot"), row=1, col=1)

    # ── 单笔收益分布 ──
    for lab, _, c in RUNS:
        r = D[lab][2].clip(-40, 80)
        fig.add_histogram(x=r, name=lab, marker_color=c, opacity=0.55,
                          xbins=dict(start=-40, end=80, size=4), legendgroup=lab,
                          showlegend=False, row=1, col=2,
                          hovertemplate="收益 %{x}% 共 %{y} 笔<extra>" + lab + "</extra>")
    for lab, _, c in RUNS:
        fig.add_vline(x=float(D[lab][2].mean()), line=dict(color=c, width=1.6, dash="dash"),
                      row=1, col=2)
    fig.add_vline(x=0, line=dict(color=GRAY, width=1), row=1, col=2)

    # ── 年度 ──
    years = sorted(set().union(*[set(D[lab][3].index) for lab, _, _ in RUNS]))
    for lab, _, c in RUNS:
        fig.add_bar(x=[str(y) for y in years], y=D[lab][3].reindex(years).values,
                    name=lab, marker_color=c, marker_line_width=0, legendgroup=lab,
                    showlegend=False, row=2, col=1,
                    hovertemplate="%{x} %{y:+.1f}%<extra>" + lab + "</extra>")
    fig.add_hline(y=0, line=dict(color="#4a5568", width=1.2), row=2, col=1)

    # ── 回撤 ──
    for lab, _, c in RUNS:
        n = D[lab][0]
        dd = (n["nav"] / n["nav"].cummax() - 1) * 100
        fig.add_scatter(x=n["date"], y=dd, mode="lines", name=lab, line=dict(color=c, width=1.6),
                        legendgroup=lab, showlegend=False, row=2, col=2,
                        hovertemplate="%{x|%Y-%m} 回撤 %{y:.1f}%<extra></extra>")

    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="笔数", row=1, col=2)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_yaxes(title_text="%", row=2, col=2)
    fig.update_xaxes(title_text="单笔收益 %", row=1, col=2)

    fig.update_layout(
        height=940, template="plotly_white", barmode="group", bargap=0.2, bargroupgap=0.08,
        hovermode="closest",
        title=dict(text="analysis_014 · volume 更新七 — W2 配方：沪深300 池 vs 中证500 池<br>"
                        "<span style='font-size:12px;color:#718096'>同一套规则（v4活带 + MA200闸门 + "
                        "COMBO优先 + 10坑×10万 + 15bps），只换股票池；净值口径 = trades 直接推算"
                        "（固定名义不复利）</span>", x=0.5, font=dict(size=16)),
        legend=dict(orientation="h", y=1.075, x=0.5, xanchor="center", font=dict(size=12)),
        margin=dict(t=175, b=60))

    rows = []
    for lab, _, _c in RUNS:
        n, m, r, _yr = D[lab]
        rows.append({"配置": lab, "笔数": int(m.n_trades), "总收益%": m.total_return * 100,
                     "年化%": m.annual_return * 100, "Sharpe": m.sharpe,
                     "最大回撤%": m.max_drawdown * 100, "交易胜率%": m.win_rate_pct,
                     "盈亏比": m.payoff, "单笔均值%": r.mean(), "单笔中位%": r.median(),
                     "肥尾率%(≥30)": (r >= 30).mean() * 100, "失败率%(≤0)": (r <= 0).mean() * 100})
    t = pd.DataFrame(rows)
    tbl = "".join(
        "<tr" + (" style=background:#f7fafc" if i % 2 else "") + ">"
        + f"<td style='padding:4px 12px'>{r['配置']}</td><td>{r['笔数']}</td>"
        + f"<td><b>{r['总收益%']:+.1f}</b></td><td>{r['年化%']:+.1f}</td><td>{r['Sharpe']:.3f}</td>"
        + f"<td>{r['最大回撤%']:.1f}</td><td>{r['交易胜率%']:.1f}</td><td>{r['盈亏比']:.2f}</td>"
        + f"<td>{r['单笔均值%']:+.2f}</td><td>{r['单笔中位%']:+.2f}</td>"
        + f"<td>{r['肥尾率%(≥30)']:.1f}</td><td><b>{r['失败率%(≤0)']:.1f}</b></td></tr>"
        for i, (_, r) in enumerate(t.iterrows()))

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_014 · volume · 更新七</title></head>
<body style='font-family:system-ui;max-width:1340px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：把已验收的 <b>W2 配方</b>原样套到中证500 成分股（<code>GATE_INDEX</code> 试两档）。
三者规则完全一致，唯一变量 = <b>股票池</b>。中证500 的 v4 事件 / COMBO 在独立目录重算与标定，
不与沪深300 混用（COMBO 的 z 标定依赖事件总体，混用会让两池不可比）。</p>
<p style='color:#c53030'><b>⚠ 口径声明</b>：净值/指标一律取 <b>trades 直接推算</b>
（<code>nav_from_trades</code> / <code>metrics_from_trades</code>，固定名义不复利
<code>NAV = 1 + Σ(0.1×单笔收益)</code>），这是项目指标铁律的口径，也是 W2 基准 +186.7% 的口径。
引擎的 <code>equity_curve.csv</code> 是<b>复利净值路径</b>且自带归因近似，两者在 2021 年前吻合、
之后急剧分叉（本例 2026-08-20：trades <b>0.843</b> vs equity <b>1.811</b>），故<b>不采用</b>。</p>

<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:4px 12px;text-align:left'>配置</th><th>笔数</th>
<th>总收益%</th><th>年化%</th><th>Sharpe</th><th>最大回撤%</th><th>交易胜率%</th><th>盈亏比</th>
<th>单笔均值%</th><th>单笔中位%</th><th>肥尾率%</th><th>失败率%</th></tr>
{tbl}</table>

<p style='margin-top:12px'><b>结论：W2 配方可以迁移到中证500——两者基本等价。</b></p>
<ol>
<li><b>收益/风险几乎相同</b>：中证500 池 <b>+176.4%</b>、Sharpe <b>0.745</b>、maxDD −25.6%，
   对比沪深300 池 +186.7%、Sharpe 0.743、maxDD −24.0%——<b>Sharpe 几乎完全一致</b>。</li>
<li><b>结构略有不同但同样成立</b>：中证500 胜率更低（30.5% vs 36.8%）、失败率更高（69.5% vs 63.2%），
   但<b>盈亏比更高（4.05 vs 3.51）</b>——「高失败 + 罕见右尾」的彩票结构<b>依然存在</b>（肥尾率 8.2% vs 7.9%）。</li>
<li><b>MA200 闸门必须用沪深300</b>：换成中证500 自身的年线后掉到 <b>+79.4%</b>（Sharpe 0.332、maxDD −40.9%）。
   中证500 的 MA200 开门日只有 1,408 天（沪深300 为 2,755 天），过滤更严且时点偏离。
   <b>市场 regime 代理应固定用沪深300，不要换成被交易指数。</b></li>
</ol>
<p style='color:#c53030'><b>⚠ 本页数字经过一次重大更正</b>：首版误用全局 ATR 缓存
（<code>shared/atr14_panel.parquet</code> 是沪深300 建的，传中证500 面板进去照样返回沪深300 的 ATR），
导致 688 只中证500 独有股票 ATR 全为 NaN → 吊灯止损与池失效条件静默失效 →
给出 <b>−15.7% / −57.0%</b> 的错误结论。修复（本目录独立 ATR 缓存）后为
<b>+176.4% / +79.4%</b>，<b>方向完全反转</b>。已改用独立缓存并写入 records。</p>
<p style='color:#718096'>机制解释：W2 的 edge 来自"大盘蓝筹突破后更容易走出趋势"（机构资金持续推动 → 右尾）。
中证500 是中盘，题材轮动快、抱团弱，突破后容易回落。交易记录见
<code>runs/*/backtest_logs/trades_paired.csv</code>，权威指标见 <code>metrics_from_trades.csv</code>，
逐日持仓明细见 <code>position_return_detail.csv</code>。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(t.to_string(index=False))


if __name__ == "__main__":
    main()
