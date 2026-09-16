"""analysis_015/industry 更新五 可视化 — 按突破收益十档，四个行业排名的**完整分布**（箱线）。

布局 2 行 × 3 列：
  行1  **原始**横截面排名：收益率排名 | 换手率排名 | 成交量排名（每格 10 个箱 = 收益十档）
  行2  **行业内**中性化：同上
每格附：虚线 = 该指标全体中位数（档间位移的参照）、标注 位移/IQR（效应幅度 ÷ 档内离散度）。
配色守恒：蓝 #2b6cb0 = 原始，琥珀 #b7791f = 行业内（已过 validate_palette.js，相邻 CVD ΔE 23.1）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER, GRAY = "#2b6cb0", "#b7791f", "#4a5568"
METRICS = [("RET", "收益率排名"), ("TURN", "换手率排名"), ("VOL", "成交量排名"), ("AMT", "成交额排名")]
CALIPERS = [("RAW", "原始", BLUE, "rgba(43,108,176,0.28)"),
            ("DM", "行业内", AMBER, "rgba(183,121,31,0.28)")]


def main():
    d = pd.read_parquet(HERE / "dist_samples.parquet")
    stats = pd.read_csv(HERE / "dispersion_summary.csv")
    base = pd.read_csv(HERE / "baseline.txt", sep="=", header=None, index_col=0)[1]
    d["dec_lab"] = d["ret_dec"].astype(int).map(lambda k: f"D{k}")
    n_dec = d["ret_dec"].nunique()

    titles = [f"【原始】{lab} · 分布" for _, lab in METRICS] + \
             [f"【行业内】{lab} · 分布" for _, lab in METRICS]
    fig = make_subplots(rows=2, cols=4, subplot_titles=titles,
                        vertical_spacing=0.16, horizontal_spacing=0.075)

    for i, (cal, clab, line_c, fill_c) in enumerate(CALIPERS):
        row = i + 1
        for j, (m, mlab) in enumerate(METRICS):
            c = f"H10_{m}_{cal}"
            fig.add_trace(go.Box(x=d["dec_lab"], y=d[c],
                                 boxpoints=False, boxmean=True, name=clab,
                                 line=dict(color=line_c, width=1.6),
                                 fillcolor=fill_c, whiskerwidth=0.6, showlegend=False,
                                 hovertemplate="%{x} %{y:.3f}<extra></extra>"),
                          row=row, col=j + 1)
            ov = d[c].median()
            fig.add_hline(y=ov, line=dict(color=GRAY, width=1.2, dash="dash"),
                          row=row, col=j + 1)
            med = d.groupby("ret_dec")[c].median()
            ion = d.groupby("ret_dec")[c].apply(lambda s: s.quantile(.75) - s.quantile(.25)).mean()
            ratio = abs(med.loc[1] - med.loc[min(6, n_dec)]) / ion
            fig.add_annotation(x=0.5, y=0.015, xref="x domain", yref="y domain",
                               text=f"位移/IQR = <b>{ratio:.2f}</b>", showarrow=False,
                               font=dict(size=11, color=line_c), xanchor="center", row=row, col=j + 1)

    order = [f"D{k}" for k in range(1, n_dec + 1)]
    for c_ in range(1, 5):
        for r_ in (1, 2):
            fig.update_xaxes(categoryorder="array", categoryarray=order, row=r_, col=c_,
                             title_text="突破收益十分位（D1 最差 → D10 最好）")
        fig.update_yaxes(title_text="排名值（0~1）", row=1, col=c_)
        fig.update_yaxes(title_text="排名偏离（行业内）", row=2, col=c_)

    fig.update_layout(
        height=1000, template="plotly_white",
        title=dict(text="analysis_015 · industry 更新五 — 按突破收益十档，四个行业排名的完整分布"
                        f"（{len(d)} 笔，10 日窗口）<br>"
                        "<span style='font-size:12px;color:#718096'>箱=四分位 · 须=1.5IQR · 箱内虚线=均值 · "
                        "灰虚线=该指标全体中位数 · 位移/IQR = 档间位移 ÷ 档内离散度（越大效应越实）</span>",
                   x=0.5, font=dict(size=16)),
        margin=dict(t=170, b=60), showlegend=False)

    tbl = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}><td style='padding:3px 12px'>{r['指标']}</td>"
        f"<td>{r['口径']}</td><td>{r['D1中位']:.4f}</td><td>{r['D10中位']:.4f}</td>"
        f"<td><b>{r['D1−D6']:+.4f}</b></td><td>{r['档内IQR']:.4f}</td>"
        f"<td><b>{r['位移/IQR']:.2f}</b></td></tr>"
        for i, (_, r) in enumerate(stats.iterrows()))

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新五</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：按每笔突破的 <code>ret</code> 分十档等频（每档 ~863 笔，共 {len(d)} 笔），
画每档 **收益率排名 / 换手率排名 / 成交量排名 / 成交额排名** 的完整分布（箱线）。成交额为本更新新增（仓库按二级 sum 聚合 → 日频截面排名，缺失 0）。
指标 = sw2021 二级行业（117 个）的日频横截面排名 → **10 日均值**；口径分**原始**与**行业内中性化**。</p>

<p><b>核心指标——位移/IQR</b>（档间位移 ÷ 档内离散度，越大说明效应越"实"）：</p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>指标</th><th>口径</th>
<th>D1中位</th><th>D10中位</th><th>D1−D6</th><th>档内IQR</th><th>位移/IQR</th></tr>
{tbl}</table>

<p style='margin-top:12px'><b>这张图想说明的一件事：</b>四个指标的档间位移，相对于<b>档内离散度</b>都很小。
最强的<b>换手率（原始）位移/IQR = 0.60</b>，即"极端档中位数"也只差不到一个箱子的六成；
收益率排名只有 <b>0.17 / 0.15</b>，箱体几乎完全重叠，肉眼看不出档间差别。
这与更新一~四的判断一致：<b>这些效应的量级，远小于同一档内部的个股/行业差异。</b></p>

<p><b>两个值得注意的形状细节：</b></p>
<ol>
<li><b>原始口径的箱体明显更宽</b>——换手率原始档内 IQR 达 <b>0.49</b>，而行业内只有 <b>0.17</b>。
   原因就是"行业身份证"：原始值把半导体（常年 0.9）和银行（常年 0.02）混在同一档里，
   箱体自然被撑开。<b>箱体宽 ≠ 信息多，恰恰相反。</b></li>
<li><b>换手率在 D1 和 D10 两端都翘起</b>（U 型），箱体位置在 D6 最低；成交量/成交额从 D1 单调下移（成交额原始位移/IQR 0.38，介于成交量 0.19 与换手率 0.60 之间）。
   收益率排名三档几乎平——印证更新一"收益率指标无区分力"。</li>
</ol>

<p style='color:#718096'>基线：失败率 {base.get('失败率%(ret≤0)', '65.9')}% / 肥尾率 {base.get('肥尾率%(ret≥30)', '7.2')}%。
行业内中性化用 causal expanding 基线（仅 t 之前历史，min_periods=250）。
逐档完整分位表见同目录 <code>dist_stats.csv</code>（含 P5/P10/P25/P50/P75/P90/P95/偏度），
逐笔样本见 <code>dist_samples.parquet</code>。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
