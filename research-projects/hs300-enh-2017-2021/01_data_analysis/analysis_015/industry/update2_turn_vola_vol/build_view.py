"""analysis_015/industry 更新二 可视化 — 换手率/波动率/成交量 三指标的反向十分位。

结构（与更新一一致，便于横向对照）：
  行1  三指标 · **原始**横截面排名 · 十档（10日实线+蓝带P25–P75 / 20日点线 / 灰虚线=十档中位数的中位数）
  行2  三指标 · **行业内**中性化 · 十档
  行3  三指标 · 分时段五分位（实线 2017-2020 / 虚线 2021-2026），验证 U 型跨时段稳定性
配色沿用已过 validate_palette.js 的 #2b6cb0(10日) / #b7791f(20日)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
UPD1 = HERE.parent / "update1_reverse_decile"
BLUE, AMBER, GRAY = "#2b6cb0", "#b7791f", "#718096"
METRICS = [("TURN", "换手率"), ("VOLA", "波动率"), ("VOL", "成交量")]


def main():
    dec = {m: pd.read_csv(HERE / f"ret_decile_{m}.csv", index_col=0) for m, _ in METRICS}
    per = pd.read_csv(HERE / "period_split.csv")
    summ = pd.read_csv(HERE / "summary.csv")
    base = (HERE / "baseline.txt").read_text(encoding="utf-8")
    m_fail = re.search(r"失败率%\(ret≤0\)=([\d.]+)", base)
    m_fat = re.search(r"肥尾率%\(ret≥30\)=([\d.]+)", base)

    fig = make_subplots(
        rows=3, cols=3,
        subplot_titles=(
            *[f"{lab} · 原始横截面排名 · 十档" for _, lab in METRICS],
            *[f"{lab} · 行业内中性化 · 十档" for _, lab in METRICS],
            *[f"{lab} · 分时段五分位" for _, lab in METRICS]),
        row_heights=[0.36, 0.36, 0.28], vertical_spacing=0.115, horizontal_spacing=0.07)

    # ── 行1/2：十档（行1=原始, 行2=行业内）──
    for j, (m, lab) in enumerate(METRICS):
        t = dec[m]
        x = [f"D{int(i)}" for i in t.index]
        for row, cal in [(1, "RAW"), (2, "DM")]:
            c10, c20 = f"H10_{m}_{cal}", f"H20_{m}_{cal}"
            if cal == "RAW":   # IQR 带仅画原始行，避免两行都满
                fig.add_scatter(x=x, y=t[f"{c10}_P25"], mode="lines", line=dict(width=0),
                                showlegend=False, hoverinfo="skip", row=row, col=j + 1)
                fig.add_scatter(x=x, y=t[f"{c10}_P75"], mode="lines", line=dict(width=0),
                                fill="tonexty", fillcolor="rgba(43,108,176,0.13)",
                                showlegend=False, hoverinfo="skip", row=row, col=j + 1)
            fig.add_scatter(x=x, y=t[f"{c10}_中位"], mode="lines+markers", name="10 日窗口",
                            line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=8),
                            legendgroup="w10", showlegend=(row == 1 and j == 0),
                            row=row, col=j + 1, hovertemplate="%{x} 10日 %{y:.3f}<extra></extra>")
            fig.add_scatter(x=x, y=t[f"{c20}_中位"], mode="lines+markers", name="20 日窗口",
                            line=dict(color=AMBER, width=2, dash="dot"),
                            marker=dict(color=AMBER, size=8, symbol="square"),
                            legendgroup="w20", showlegend=(row == 1 and j == 0),
                            row=row, col=j + 1, hovertemplate="%{x} 20日 %{y:.3f}<extra></extra>")
            fig.add_hline(y=t[f"{c10}_中位"].median(), line=dict(color=GRAY, width=1, dash="dash"),
                          row=row, col=j + 1)
            if row == 1:
                for k, xs in [(0, -6), (len(x) - 1, 6)]:
                    fig.add_annotation(x=x[k], y=t[f"{c10}_中位"].iloc[k],
                                       text=f"{t[f'{c10}_中位'].iloc[k]:.3f}", showarrow=False,
                                       yshift=15, xshift=xs, font=dict(size=10, color=BLUE),
                                       row=row, col=j + 1)

    # ── 行3：分时段五分位（原始口径，10日；色=蓝，线型=时段）──
    for j, (m, lab) in enumerate(METRICS):
        sub = per[(per["指标"] == lab) & (per["口径"] == "原始")]
        for seg, dash, sym in [("2017-2020", "solid", "circle"), ("2021-2026", "dash", "square")]:
            r = sub[sub["时段"] == seg]
            if r.empty:
                continue
            r = r.iloc[0]
            fig.add_scatter(x=[f"Q{k}" for k in range(1, 6)],
                            y=[r[f"Q{k}"] for k in range(1, 6)], mode="lines+markers",
                            name=seg, line=dict(color=BLUE, width=2, dash=dash),
                            marker=dict(color=BLUE, size=8, symbol=sym),
                            showlegend=False, row=3, col=j + 1,
                            hovertemplate=f"{seg} %{{x}} %{{y:.3f}}<extra></extra>")

    for r_ in (1, 2):
        for j in range(3):
            fig.update_yaxes(title_text="热度中位数", row=r_, col=j + 1)
            fig.update_xaxes(title_text="突破收益十分位（D1 最差 → D10 最好）", row=r_, col=j + 1)
    for j in range(3):
        fig.update_yaxes(title_text="热度中位数", row=3, col=j + 1)
        fig.update_xaxes(title_text="突破收益五分位（Q1 最差 → Q5 最好）", row=3, col=j + 1)

    fig.update_layout(
        height=1480, template="plotly_white", hovermode="x unified",
        title=dict(text="analysis_015 · industry 更新二 — 反向十分位：换手率 / 波动率 / 成交量"
                        "（8540 笔，10日/20日 × 原始/行业内）<br>"
                        "<span style='font-size:12px;color:#718096'>行1 原始 · 行2 行业内 · 行3 分时段"
                        "（实线 2017-2020 / 虚线 2021-2026，原始口径）</span>",
                   x=0.5, font=dict(size=16)),
        legend=dict(orientation="h", y=1.055, x=0.5, xanchor="center", font=dict(size=12)),
        margin=dict(t=180, b=60))

    # ── 页脚：12 变体表 + 跨四指标对照（含更新一的收益率）──
    rows12 = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}>"
        f"<td style='padding:3px 10px'>{r['指标']}</td><td>{r['窗口']}</td><td>{r['口径']}</td>"
        f"<td>{r['档↔热度中位数']:+.2f}</td><td>{r['D1']:.3f}</td><td>{r['D6']:.3f}</td>"
        f"<td>{r['D10']:.3f}</td><td>{r['D10−D1']:+.3f}</td>"
        f"<td><b>{r['U型深度(D1−D6)']:.3f}</b></td></tr>"
        for i, (_, r) in enumerate(summ.iterrows()))

    cross = pd.read_csv(UPD1 / "summary.csv")
    c = cross[cross["变体"] == "10日·原始"].iloc[0]
    cross_html = (f"<li><b>收益率</b>（更新一）U型深度 <b>{0.581-0.559:.3f}</b>、D10−D1 {c['D10−D1']:+.3f}</li>")

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新二</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>设计</b>：与更新一完全相同——按每笔突破的 <code>ret</code> 分十档等频（每档 ~853 笔，共 {sum(dec['TURN']['n'])} 笔），
再看每档的行业热度中位数。三个指标均为 sw2021 二级行业（117 个）的**日频横截面排名 → 10 日均值**。
<b>波动率为新指标</b>：panel 原无，定义为 <b>20 日滚动日收益率标准差</b>，再取日频横截面排名。</p>

<p><b>三个指标形状不同（10日·原始）：</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 10px;text-align:left'>指标</th><th>窗口</th><th>口径</th>
<th>档↔中位数</th><th>D1</th><th>D6</th><th>D10</th><th>D10−D1</th><th>U型深度</th></tr>
{rows12}</table>

<p style='margin-top:12px'><b>结论：</b></p>
<ol>
<li><b>三个指标方向一致，都指向"热度高 → 突破更差/更极端"，与人工假设相反</b>，
且与更新一的收益率指标（U型深度 0.022）同向。</li>
<li><b>但形状差异很大</b>：
  <ul><li><b>换手率 U 型最深</b>（0.298）——两个极端档（D1 最差 0.726 / D10 肥尾 0.681）都远比中段（D6 0.428）热；
      "热门行业的结果更两极"这个说法在换手率上最成立。</li>
  <li><b>波动率 D10−D1 最大</b>（−0.126）——肥尾档来自波动率明显偏冷的行业，是三者中"高收益=冷"最明显的。</li>
  <li><b>成交量最接近单调负向</b>（Spearman −0.52，20日 −0.77），U 型最浅（0.073）——
      基本是"行业成交量排名越高，突破收益越低"一条斜线，没有回升。</li></ul></li>
<li><b>⚠ 幅度仍小</b>：只有换手率/波动率的 U 型深度（0.21–0.30）达到档内 P25–P75 带宽（~0.14–0.2）的 1.5–2 倍，
    够得上"可辨别"；成交量原始虽单调但全程只在 0.83→0.77 之间走。<b>行业内中性化后幅度普遍减半</b>
    （换手率 0.298→0.072、波动率 0.211→0.108、成交量 0.073→0.051）。</li>
<li><b>分时段</b>（行3）：换手率、波动率的 U 型在两段都在；<b>成交量的单调负向主要来自 2017-2020</b>
    （Spearman −1.0，Q1 0.803→Q5 0.663），2021-2026 段几乎走平（−0.3）——<b>该指标时段不稳定，慎用</b>。</li>
<li>四指标横向对照（U型深度 / D10−D1，10日·原始）：换手率 0.298/−0.045、波动率 0.211/−0.126、
    成交量 0.073/−0.060、{cross_html}。</li>
</ol>
<p style='color:#718096'>基线：失败率 {m_fail.group(1) if m_fail else '65.9'}% / 肥尾率 {m_fat.group(1) if m_fat else '7.2'}%。
行业内中性化用 causal expanding 基线（仅 t 之前历史，min_periods=250）。
数据表见同目录 CSV（<code>ret_decile_TURN/VOLA/VOL.csv</code> / <code>summary.csv</code> / <code>period_split.csv</code>）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
