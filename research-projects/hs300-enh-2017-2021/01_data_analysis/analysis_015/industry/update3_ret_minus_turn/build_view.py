"""analysis_015/industry 更新三 可视化 — 价量背离指标 ma(收益率排名,10) − ma(换手率排名,10)。

形状是**倒 U（∩）而非单调**，且指标跨越 0，故：
  · 行1 十档中位数 + 零参考线 + P25–P75 带
  · 行2 分时段五分位验证倒 U 跨时段稳定性
  · 页脚给**成分分解表**——这是本更新的关键：收益率成分几乎平坦（极差 0.024），
    换手率成分是 U（极差 0.296），故差值 ≈ −换手率
配色沿用已过 validate_palette.js 的 #2b6cb0(10−10) / #b7791f(20−20)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER, GRAY = "#2b6cb0", "#b7791f", "#718096"
PAIRS = [("S10_RAW", "S20_RAW", "原始横截面排名"), ("S10_DM", "S20_DM", "行业内中性化")]


def main():
    t = pd.read_csv(HERE / "ret_decile_SPR.csv", index_col=0)
    dec = pd.read_csv(HERE / "decomposition.csv", index_col=0)
    per = pd.read_csv(HERE / "period_split.csv")
    summ = pd.read_csv(HERE / "summary.csv")
    base = (HERE / "baseline.txt").read_text(encoding="utf-8")
    m_fail = re.search(r"失败率%\(ret≤0\)=([\d.]+)", base)
    m_fat = re.search(r"肥尾率%\(ret≥30\)=([\d.]+)", base)

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("原始横截面排名 · 十档（零线=价量平衡）",
                        "行业内中性化 · 十档（零线=行业自身常态）",
                        "原始 · 分时段五分位", "行业内 · 分时段五分位"),
        vertical_spacing=0.17, horizontal_spacing=0.09)

    x = [f"D{int(i)}" for i in t.index]
    for j, (c10, c20, lab) in enumerate(PAIRS):
        # IQR 带（仅 10−10）
        fig.add_scatter(x=x, y=t[f"{c10}_P25"], mode="lines", line=dict(width=0),
                        showlegend=False, hoverinfo="skip", row=1, col=j + 1)
        fig.add_scatter(x=x, y=t[f"{c10}_P75"], mode="lines", line=dict(width=0),
                        fill="tonexty", fillcolor="rgba(43,108,176,0.13)",
                        showlegend=False, hoverinfo="skip", row=1, col=j + 1)
        fig.add_scatter(x=x, y=t[f"{c10}_中位"], mode="lines+markers", name="10−10 窗口",
                        line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=9),
                        legendgroup="w10", showlegend=(j == 0), row=1, col=j + 1,
                        hovertemplate="%{x} 10−10 %{y:.3f}<extra></extra>")
        fig.add_scatter(x=x, y=t[f"{c20}_中位"], mode="lines+markers", name="20−20 窗口",
                        line=dict(color=AMBER, width=2, dash="dot"),
                        marker=dict(color=AMBER, size=9, symbol="square"),
                        legendgroup="w20", showlegend=(j == 0), row=1, col=j + 1,
                        hovertemplate="%{x} 20−20 %{y:.3f}<extra></extra>")
        fig.add_hline(y=0, line=dict(color="#4a5568", width=1.5), row=1, col=j + 1)
        peak = int(t[f"{c10}_中位"].idxmax())
        fig.add_annotation(x=f"D{peak}", y=t.loc[peak, f"{c10}_中位"],
                           text=f"峰值 D{peak} {t.loc[peak, f'{c10}_中位']:+.3f}", showarrow=True,
                           arrowhead=2, ay=-34, ax=0, font=dict(size=10.5, color=BLUE),
                           row=1, col=j + 1)

    # ── 行2：分时段五分位（蓝=同一指标，线型=时段）──
    for j, (_, _, lab) in enumerate(PAIRS):
        var = ["10−10·原始", "10−10·行业内"][j]
        sub = per[per["变体"] == var]
        for seg, dash, sym in [("2017-2020", "solid", "circle"), ("2021-2026", "dash", "square")]:
            r = sub[sub["时段"] == seg]
            if r.empty:
                continue
            r = r.iloc[0]
            fig.add_scatter(x=[f"Q{k}" for k in range(1, 6)],
                            y=[r[f"Q{k}"] for k in range(1, 6)], mode="lines+markers",
                            name=seg, line=dict(color=BLUE, width=2, dash=dash),
                            marker=dict(color=BLUE, size=8, symbol=sym), showlegend=False,
                            row=2, col=j + 1,
                            hovertemplate=f"{seg} %{{x}} %{{y:.3f}}<extra></extra>")
        fig.add_hline(y=0, line=dict(color="#4a5568", width=1.2, dash="dot"), row=2, col=j + 1)

    for r_ in (1, 2):
        for c_ in (1, 2):
            fig.update_yaxes(title_text="指标中位数（排名差）", row=r_, col=c_)
    for c_ in (1, 2):
        fig.update_xaxes(title_text="突破收益十分位（D1 最差 → D10 最好）", row=1, col=c_)
        fig.update_xaxes(title_text="突破收益五分位（Q1 最差 → Q5 最好）", row=2, col=c_)

    fig.update_layout(
        height=880, template="plotly_white", hovermode="x unified",
        title=dict(text="analysis_015 · industry 更新三 — 价量背离 ma(收益率排名,10) − ma(换手率排名,10)"
                        "（8621 笔，倒 U 型）<br>"
                        "<span style='font-size:12px;color:#718096'>行1 十档 · 行2 分时段"
                        "（实线 2017-2020 / 虚线 2021-2026）</span>", x=0.5, font=dict(size=16)),
        legend=dict(orientation="h", y=1.095, x=0.5, xanchor="center", font=dict(size=12)),
        margin=dict(t=210, b=60))

    sum_html = "".join(
        f"<tr><td style='padding:3px 12px'>{r['变体']}</td><td>{r['档↔指标中位数']:+.2f}</td>"
        f"<td>{r['D1']:+.4f}</td><td>{r['D6']:+.4f}</td><td>{r['D10']:+.4f}</td>"
        f"<td>D{r['最高档']}</td><td>{r['D10−D1']:+.4f}</td><td><b>{r['D1−D6']:+.4f}</b></td>"
        f"<td>{r['正占比%']:.1f}%</td></tr>" for _, r in summ.iterrows())

    dec_html = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}><td style='padding:3px 12px'>D{int(i)}</td>"
        f"<td>{r['收益率排名均值(10日)']:.4f}</td><td>{r['换手率排名均值(10日)']:.4f}</td>"
        f"<td><b>{r['差值(=指标)']:+.4f}</b></td><td>{r['差值(行业内)']:+.4f}</td>"
        f"<td>{r['差值正占比%(原始)']:.1f}%</td></tr>"
        for i, r in dec.iterrows())

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新三</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>指标</b>：<code>ma(收益率横截面排名,10) − ma(换手率横截面排名,10)</code>（sw2021 二级行业，117 个）。
高值 = <b>涨了但没放量</b>（缩量走强）；低值 = <b>放量滞涨</b>（拥挤/派发）。
分析流程与更新二相同：按每笔突破的 <code>ret</code> 分十档（每档 854 笔，共 {int(t['n'].sum())} 笔）反查该指标。</p>

<p><b>形状是倒 U（∩），峰值在中段 D6，不是单调线：</b>
D1（最惨，−17.4%）<b>−0.141</b> → D6（−4.0%）<b>+0.121</b> → D10（肥尾 +35.2%）<b>−0.089</b>。
<b>两个极端档都是负值（放量滞涨），中段才是正值（缩量走强）。</b>
Spearman 报 +0.37，但同样是错的工具——它只抓住了 D1→D6 的上坡。</p>

<p><b>四变体对照：</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>变体</th><th>档↔中位数</th>
<th>D1</th><th>D6</th><th>D10</th><th>峰值档</th><th>D10−D1</th><th>D1−D6</th><th>D10正占比</th></tr>
{sum_html}</table>

<p style='margin-top:14px'><b>⚠ 成分分解——这是本更新的关键发现（原始口径，10日）：</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>档</th>
<th>收益率排名均值</th><th>换手率排名均值</th><th>差值(=指标)</th><th>差值(行业内)</th><th>差值为正占比</th></tr>
{dec_html}</table>
<p style='margin-top:8px'>收益率成分 <b>几乎平坦</b>（0.5589 ~ 0.5831，极差 <b>0.024</b>）；
换手率成分是 <b>U 型</b>（0.4301 ~ 0.7259，极差 <b>0.296</b>）。
→ <b>差值 ≈ −换手率</b>，收益率成分只贡献约 8% 的振幅。
<b>换句话说：这个"价量背离"指标实质上没有超出换手率的新信息，它基本是换手率指标的反号复制品。</b>
构造思路是对的，但在行业层面"收益率排名"对突破结果几乎不敏感，导致差值退化成单边。</p>

<p><b>其余结论：</b></p>
<ol>
<li>倒 U 跨时段稳定：2017-2020（−0.082 / +0.014 / +0.074 / +0.043 / −0.054）与
2021-2026（−0.121 / −0.006 / +0.139 / +0.101 / −0.039）两段都是两端低中间高。</li>
<li>行业内中性化后峰值从 D6 移到 D5，振幅由 0.262 降到 0.049——<b>与更新二一致，中性化后幅度大幅收缩</b>。</li>
<li>差值为正的比例：D6 最高 <b>61.5%</b>，D1 最低 <b>34.8%</b>，D10 <b>37.9%</b>。</li>
<li><b>口径提示</b>：本分析是"按收益分档反查指标"（更新二框架），只能说明<b>不同结果的信号在指标上的构成差异</b>，
不等于预测力。若要看该指标**能否预测**突破结果，应做正向框架（按指标分档 → 看收益/失败率/肥尾率），
即父目录初建的做法。</li>
</ol>
<p style='color:#718096'>基线：失败率 {m_fail.group(1) if m_fail else '65.9'}% / 肥尾率 {m_fat.group(1) if m_fat else '7.2'}%。
行业内中性化用 causal expanding 基线（仅 t 之前历史，min_periods=250）。
数据表见同目录 CSV（<code>ret_decile_SPR.csv</code> / <code>decomposition.csv</code> / <code>summary.csv</code> / <code>period_split.csv</code>）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
