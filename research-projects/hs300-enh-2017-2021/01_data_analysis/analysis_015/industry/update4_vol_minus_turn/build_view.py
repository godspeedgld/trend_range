"""analysis_015/industry 更新四 可视化 — 规模/活跃度错配 ma(成交量排名,10) − ma(换手率排名,10)。

布局（3 行 × 3 列）——**每种度量独占一个面板**（避免 失败率 60-72% 与 肥尾率 3-10% 共轴被压扁）：
  行1  B 正向框架 · 原始口径：均值% | 失败率% | 肥尾率%
  行2  B 正向框架 · 行业内口径：同上三格
  行3  A 反向框架 · 原始 / 行业内 指标中位数 | B 正向 · 分时段五分位均值%
配色：#2b6cb0（指标/均值） · #b7791f（失败率） · #c53030（肥尾率） · #718096（基线参考线）
三色已过 validate_palette.js：最差相邻 CVD ΔE 8.1 deutan / 正常视觉 15.4。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER, RED, GRAY = "#2b6cb0", "#b7791f", "#c53030", "#718096"
CAL = [("S10_RAW", "原始横截面排名", "10−10·原始"),
       ("S10_DM", "行业内中性化", "10−10·行业内")]


def main():
    fwd = {c: pd.read_csv(HERE / f"forward_decile_{c}.csv", index_col=0) for c, _, _ in CAL}
    ret = pd.read_csv(HERE / "ret_decile_SPR.csv", index_col=0)
    dec = pd.read_csv(HERE / "decomposition.csv", index_col=0)
    per = pd.read_csv(HERE / "period_split.csv")
    fsum = pd.read_csv(HERE / "forward_summary.csv")
    base = (HERE / "baseline.txt").read_text(encoding="utf-8")
    m_fail = re.search(r"失败率%\(ret≤0\)=([\d.]+)", base)
    m_fat = re.search(r"肥尾率%\(ret≥30\)=([\d.]+)", base)
    m_mu = re.search(r"均值%=([\-\d.]+)", base)
    b_fail, b_fat, b_mu = float(m_fail.group(1)), float(m_fat.group(1)), float(m_mu.group(1))

    titles = []
    for _, lab, _ in CAL:
        titles += [f"【B 正向·{lab[:2]}】单笔均值%（柱）",
                   f"【B 正向·{lab[:2]}】失败率%（柱）",
                   f"【B 正向·{lab[:2]}】肥尾率%（柱）"]
    titles += ["【A 反向·原始】按收益分档 · 指标中位数",
               "【A 反向·行业内】按收益分档 · 指标中位数",
               "【B 正向·原始】分时段五分位 · 均值%"]

    fig = make_subplots(rows=3, cols=3, subplot_titles=titles,
                        row_heights=[0.32, 0.32, 0.36],
                        vertical_spacing=0.135, horizontal_spacing=0.075)

    # ── 行1/2：正向框架三度量 ──
    for i, (c, lab, tag) in enumerate(CAL):
        f = fwd[c]
        row = i + 1
        x = [f"D{int(k)}" for k in f.index]
        # 均值%
        fig.add_bar(x=x, y=f["均值%"], marker_color=BLUE, marker_line_width=0,
                    text=[f"{v:+.1f}" for v in f["均值%"]], textposition="outside",
                    textfont=dict(size=10, color="#2d3748"), cliponaxis=False, showlegend=False,
                    row=row, col=1, hovertemplate="%{x} 均值 %{y:+.2f}%<extra></extra>")
        fig.add_hline(y=0, line=dict(color="#4a5568", width=1.5), row=row, col=1)
        fig.add_hline(y=b_mu, line=dict(color=GRAY, width=1, dash="dash"), row=row, col=1)
        # 失败率%
        fig.add_bar(x=x, y=f["失败率%(ret≤0)"], marker_color=AMBER, marker_line_width=0,
                    showlegend=False, row=row, col=2,
                    hovertemplate="%{x} 失败率 %{y:.1f}%<extra></extra>")
        fig.add_hline(y=b_fail, line=dict(color=GRAY, width=1, dash="dash"), row=row, col=2)
        # 肥尾率%
        fig.add_bar(x=x, y=f["肥尾率%(ret≥30)"], marker_color=RED, marker_line_width=0,
                    text=[f"{v:.1f}" for v in f["肥尾率%(ret≥30)"]], textposition="outside",
                    textfont=dict(size=10, color=RED), cliponaxis=False, showlegend=False,
                    row=row, col=3, hovertemplate="%{x} 肥尾率 %{y:.1f}%<extra></extra>")
        fig.add_hline(y=b_fat, line=dict(color=GRAY, width=1, dash="dash"), row=row, col=3)

    # ── 行3：A 反向 + 分时段 ──
    for j, (c, lab, tag) in enumerate(CAL):
        x = [f"D{int(k)}" for k in ret.index]
        fig.add_scatter(x=x, y=ret[f"{c}_P25"], mode="lines", line=dict(width=0),
                        showlegend=False, hoverinfo="skip", row=3, col=j + 1)
        fig.add_scatter(x=x, y=ret[f"{c}_P75"], mode="lines", line=dict(width=0),
                        fill="tonexty", fillcolor="rgba(43,108,176,0.13)",
                        showlegend=False, hoverinfo="skip", row=3, col=j + 1)
        fig.add_scatter(x=x, y=ret[f"{c}_中位"], mode="lines+markers", name="指标中位数",
                        line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=8),
                        showlegend=False, row=3, col=j + 1,
                        hovertemplate="%{x} 指标中位数 %{y:+.3f}<extra></extra>")
        fig.add_hline(y=0, line=dict(color="#4a5568", width=1.2, dash="dot"), row=3, col=j + 1)
        pk = int(ret[f"{c}_中位"].idxmax())
        fig.add_annotation(x=f"D{pk}", y=ret.loc[pk, f"{c}_中位"],
                           text=f"峰值 D{pk} {ret.loc[pk, f'{c}_中位']:+.3f}", showarrow=True,
                           arrowhead=2, ay=-30, ax=0, font=dict(size=10, color=BLUE),
                           row=3, col=j + 1)

    sub = per[(per["框架"] == "B正向") & (per["变体"] == "10−10·原始")]
    for seg, dash, sym in [("2017-2020", "solid", "circle"), ("2021-2026", "dash", "square")]:
        r = sub[sub["时段"] == seg]
        if r.empty:
            continue
        r = r.iloc[0]
        fig.add_scatter(x=[f"Q{k}" for k in range(1, 6)], y=[r[f"Q{k}"] for k in range(1, 6)],
                        mode="lines+markers", name=seg, line=dict(color=BLUE, width=2, dash=dash),
                        marker=dict(color=BLUE, size=9, symbol=sym), showlegend=False,
                        row=3, col=3, hovertemplate=f"{seg} %{{x}} %{{y:+.2f}}%<extra></extra>")
    fig.add_hline(y=0, line=dict(color="#4a5568", width=1.2, dash="dot"), row=3, col=3)

    for r_ in range(1, 4):
        for c_ in range(1, 4):
            fig.update_yaxes(title_text="%", row=r_, col=c_)
    for r_ in (1, 2):
        for c_ in range(1, 4):
            fig.update_xaxes(title_text="指标十档（D1 低 → D10 高）", row=r_, col=c_)
    for c_ in (1, 2):
        fig.update_xaxes(title_text="突破收益十档（D1 最差 → D10 最好）", row=3, col=c_)
    fig.update_xaxes(title_text="指标五分位（Q1 低 → Q5 高）", row=3, col=3)

    fig.update_layout(
        height=1380, template="plotly_white", bargap=0.34, hovermode="closest",
        title=dict(text="analysis_015 · industry 更新四 — 规模/活跃度错配 "
                        "ma(成交量排名,10) − ma(换手率排名,10)（8621 笔）<br>"
                        "<span style='font-size:12px;color:#718096'>低值 = 小而闹（小盘活跃） · "
                        "高值 = 大而静（大盘冷门）｜灰虚线 = 全体基线｜行3 实线 2017-2020 / 虚线 2021-2026</span>",
                   x=0.5, font=dict(size=16)),
        showlegend=False, margin=dict(t=170, b=60))

    fwd_html = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}><td style='padding:3px 12px'>{r['变体']}</td>"
        f"<td>{r['档↔均值']:+.2f}</td><td>{r['档↔失败率']:+.2f}</td>"
        f"<td>{r['D1均值%']:+.2f}</td><td>{r['D10均值%']:+.2f}</td>"
        f"<td><b>{r['极差均值%']:.2f}</b></td><td>D{r['最好档']}</td><td>D{r['最差档']}</td>"
        f"<td>{r['D1肥尾%']:.1f}</td><td>{r['D10肥尾%']:.1f}</td></tr>"
        for i, (_, r) in enumerate(fsum.iterrows()))

    dec_html = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}><td style='padding:3px 12px'>D{int(i)}</td>"
        f"<td>{r['成交量排名均值(10日)']:.4f}</td><td>{r['换手率排名均值(10日)']:.4f}</td>"
        f"<td><b>{r['差值(=指标)']:+.4f}</b></td><td>{r['校验:前两列之差']:+.4f}</td></tr>"
        for i, r in dec.iterrows())

    bp = per[per["框架"] == "B正向"]
    seg_html = "".join(
        f"<tr><td style='padding:3px 12px'>{r['时段']}</td><td>{r['变体']}</td>"
        f"<td>{r['档↔中位数']:+.2f}</td>"
        + "".join(f"<td>{r[f'Q{k}']:+.2f}</td>" for k in range(1, 6)) + "</tr>"
        for _, r in bp.iterrows())

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新四</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>指标</b>：<code>ma(成交量横截面排名,10) − ma(换手率横截面排名,10)</code>（sw2021 二级行业，117 个）。
成交量排名受<b>行业规模</b>主导，换手率排名是<b>相对自身盘子</b>的活跃度 →
低值 = <b>小而闹</b>（小盘活跃），高值 = <b>大而静</b>（大盘冷门）。</p>

<p><b>★ 正向框架（按指标分档 → 看绩效）是本系列目前最强的信号：</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>变体</th><th>档↔均值</th>
<th>档↔失败率</th><th>D1均值%</th><th>D10均值%</th><th>极差</th><th>最好档</th><th>最差档</th>
<th>D1肥尾%</th><th>D10肥尾%</th></tr>
{fwd_html}</table>
<p style='margin-top:8px'>原始口径 <b>Spearman 档↔均值 −0.72、档↔失败率 +0.70</b>，
最好档 D1（最"小而闹"）均值 <b>+5.05%</b>、肥尾率 <b>10.5%</b>；最差档 D8 均值 <b>−2.68%</b>、肥尾率 3.4%。
<b>极差 7.73pp 均值 —— 比更新一/二/三的任何指标都强得多。</b></p>

<p><b>⚠ 但它有两个致命问题：</b></p>
<ol>
<li><b>行业内中性化后信号归零</b>：Spearman 由 −0.72 塌到 <b>+0.09</b>，档↔失败率由 +0.70 塌到 −0.26。
   又是行业身份证——低值（小盘活跃）在 2017-2020 恰好对应科技/题材类行业，而那是它们的大年。
   一旦按行业自身历史中性化，效应消失。</li>
<li><b>时段极度不稳定</b>：正向框架五分位均值%（原始）——</li></ol>
<table style='border-collapse:collapse;font-size:13px;margin-left:22px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>时段</th><th>变体</th>
<th>档↔均值</th><th>Q1</th><th>Q2</th><th>Q3</th><th>Q4</th><th>Q5</th></tr>
{seg_html}</table>
<p style='margin-top:8px'>2017-2020 原始口径 <b>Spearman −1.0、Q1 +10.91% vs Q5 −0.99%</b>——近乎完美单调；
<b>2021-2026 完全消失（+0.1，Q1 −0.35% vs Q5 −0.22%）</b>。
行业内口径则两段<b>符号相反</b>（+1.0 → −0.4）。<b>无论哪个口径都不稳定。</b></p>

<p><b>A 反向框架（按收益分档反查指标）：</b>倒 U，峰值档 D5（原始 10−10）。
成分分解（<b>用均值</b>——均值可加，中位数不满足可加性故不用）：</p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>档</th>
<th>成交量排名均值</th><th>换手率排名均值</th><th>差值(=指标)</th><th>校验(前两列之差)</th></tr>
{dec_html}</table>
<p style='margin-top:8px'>成交量成分极差仅 <b>0.073</b>（平），换手率成分极差 <b>0.206</b>（U 型）→
差值仍由换手率主导，与更新三同理。校验列与差值列逐行一致 ✓</p>

<p><b>结论：这个指标看起来是 R6 里最强的，但两个检验都不过关（中性化后归零 + 时段翻符号），
当前证据不支持采用。最合理的解释是它捕捉的是"2017-2020 小盘题材风格"这个特定市场状态，
而非行业热度本身。</b></p>

<p style='color:#718096'>基线：失败率 {b_fail}% / 肥尾率 {b_fat}% / 均值 {b_mu:+.2f}%（灰虚线）。
行业内中性化用 causal expanding 基线（仅 t 之前历史，min_periods=250）。
数据表见同目录 CSV（<code>forward_decile_*.csv</code> / <code>forward_summary.csv</code> /
<code>ret_decile_SPR.csv</code> / <code>decomposition.csv</code> / <code>period_split.csv</code>）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
