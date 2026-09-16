"""analysis_015/industry 更新六 可视化 — 肥尾档（D10）行业排名的**密度分布**（KDE，非箱线）。

布局 2 行 × 3 列：
  行1 **原始**横截面排名：收益率排名 | 换手率排名 | 成交量排名
  行2 **行业内**中性化：同上
每格两条曲线：**蓝实线 = 肥尾档 D10**（n=855，收益中位 +35.2%）· **琥珀虚线 = 全体参照**（D1~D10，n=8550）。
单看一条分布没有参照系，故必须并列全体。竖线标各自均值，格内标"均值位移"。
配色：#2b6cb0 / #b7791f（已过 validate_palette.js，相邻 CVD ΔE 23.1）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER, GRAY = "#2b6cb0", "#b7791f", "#718096"
METRICS = [("RET", "收益率排名"), ("TURN", "换手率排名"), ("VOL", "成交量排名")]
CALIPERS = [("RAW", "原始"), ("DM", "行业内")]


def main():
    cur = pd.read_csv(HERE / "density_curves.csv")
    st = pd.read_csv(HERE / "group_stats.csv")
    base = dict(l.split("=") for l in (HERE / "baseline.txt").read_text(encoding="utf-8").strip().split("\n"))

    titles = [f"【原始】{lab} · 密度分布" for _, lab in METRICS] + \
             [f"【行业内】{lab} · 密度分布" for _, lab in METRICS]
    fig = make_subplots(rows=2, cols=3, subplot_titles=titles,
                        vertical_spacing=0.19, horizontal_spacing=0.075)

    for i, (cal, clab) in enumerate(CALIPERS):
        row = i + 1
        for j, (m, mlab) in enumerate(METRICS):
            sub = cur[(cur.指标 == mlab) & (cur.口径 == clab)]
            for gname, color, dash, fill in [("全体参照", AMBER, "dash", None),
                                             ("肥尾档D10", BLUE, "solid", "rgba(43,108,176,0.16)")]:
                g = sub[sub.组 == gname]
                fig.add_scatter(x=g["x"], y=g["密度"], mode="lines", name=gname,
                                line=dict(color=color, width=2, dash=dash),
                                fill="tozeroy" if fill else None, fillcolor=fill,
                                showlegend=(row == 1 and j == 0), legendgroup=gname,
                                row=row, col=j + 1,
                                hovertemplate="%{x:.3f} 密度 %{y:.2f}<extra>" + gname + "</extra>")
            # 均值竖线
            for gname, color in [("全体参照", AMBER), ("肥尾档D10", BLUE)]:
                mu = st[(st.指标 == mlab) & (st.口径 == clab) & (st.组 == gname)].iloc[0]["均值"]
                fig.add_vline(x=mu, line=dict(color=color, width=1.4, dash="dot"),
                              row=row, col=j + 1)
            f = st[(st.指标 == mlab) & (st.口径 == clab) & (st.组 == "肥尾档D10")].iloc[0]
            a = st[(st.指标 == mlab) & (st.口径 == clab) & (st.组 == "全体参照")].iloc[0]
            fig.add_annotation(
                x=0.5, y=0.99, xref="x domain", yref="y domain",
                text=(f"均值位移 <b>{f['均值'] - a['均值']:+.4f}</b>"
                      f"（第{a['均值名次']}名 → 第{f['均值名次']}名）"),
                showarrow=False, font=dict(size=10.5, color=BLUE), xanchor="center",
                yanchor="top", row=row, col=j + 1)

    for c_ in range(1, 4):
        for r_ in (1, 2):
            fig.update_yaxes(title_text="概率密度", row=r_, col=c_)
        fig.update_xaxes(title_text="行业排名值（0~1）", row=1, col=c_)
        fig.update_xaxes(title_text="行业排名偏离（行业内中性化）", row=2, col=c_)

    fig.update_layout(
        height=980, template="plotly_white",
        title=dict(text="analysis_015 · industry 更新六 — 肥尾档（收益 D10）的行业排名密度分布"
                        f"<br><span style='font-size:12px;color:#718096'>"
                        f"蓝实线 = 肥尾档 D10（{base['n_fat']} 笔，收益中位 "
                        f"{float(base['肥尾档收益中位%']):+.1f}%） · 琥珀虚线 = 全体参照（{base['n_all']} 笔） · "
                        "点线 = 各自均值（单看一条无参照系，故并列全体）</span>",
                   x=0.5, font=dict(size=16)),
        legend=dict(orientation="h", y=1.075, x=0.5, xanchor="center", font=dict(size=12)),
        margin=dict(t=185, b=60))

    rows = "".join(
        f"<tr{' style=background:#f7fafc' if i % 2 else ''}><td style='padding:3px 12px'>{r['指标']}</td>"
        f"<td>{r['口径']}</td><td>{r['组']}</td><td>{r['n']}</td>"
        f"<td>{r['均值']:+.4f}</td><td>{r['均值名次']}</td><td>{r['中位']:+.4f}</td>"
        f"<td>{r['标准差']:.4f}</td><td>{r['偏度']:+.2f}</td></tr>"
        for i, (_, r) in enumerate(st.iterrows()))

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新六</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：取突破收益最后一档 <b>D10（肥尾档）</b>——{base['n_fat']} 笔，收益中位
<b>{float(base['肥尾档收益中位%']):+.1f}%</b>、肥尾率 62.2%。用 <b>KDE 高斯核密度</b>画该档的行业排名分布，
并与<b>全体</b>（D1~D10，{base['n_all']} 笔）并列对照。指标 = sw2021 二级行业（117 个）日频横截面排名 → 10 日均值。</p>

<p><b>核心读数——「肥尾档的行业，比一般突破的行业更热吗？」</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:3px 12px;text-align:left'>指标</th><th>口径</th>
<th>组</th><th>n</th><th>均值</th><th>≈名次</th><th>中位</th><th>标准差</th><th>偏度</th></tr>
{rows}</table>

<p style='margin-top:12px'><b>结论：</b></p>
<ol>
<li><b>三条密度曲线都几乎完全重叠</b>——肥尾档 vs 全体，位移最大的是
   <b>换手率（原始）+0.0749</b>（≈ 第 64 名 → 第 73 名），其余全在 ±0.023 以内。
   <b>但注意：这个 +0.0749 是"原始"口径，含行业身份证。</b></li>
<li><b>行业内中性化后位移全部塌到 0.003~0.004</b>（收益率 +0.0031 / 换手率 +0.0034 / 成交量 +0.0036）
   —— 即 <b>不到 0.5 个名次</b>。第 2 行三个图看上去就是两条同一条线。这与更新一~五一致。</li>
<li><b>形状（偏度）差异比位置差异更明显</b>：换手率原始肥尾档 <b>−0.51</b>（左偏，长尾拖向低排名）、
   成交量原始 <b>−0.80</b>（强左偏）。含义：肥尾档里既有高排名行业、也拖着一条低排名的尾巴，
   而全体参照的分布更对称。<b>这正是"肥尾档结果更两极"的分布证据</b>（与更新一/二的 U 型呼应）。</li>
<li><b>密度曲线看"位置"，箱线图看"离散度"</b>——更新五已给过箱线，本更新专门看分布的
   位置与形状。两者结论一致：<b>位置几乎不动，形状略有差异，量级都不足以支撑打分。</b></li>
</ol>
<p style='color:#718096'>本更新复用 <code>../update5_dist_by_ret/dist_samples.parquet</code>（8550 笔，10 日窗口）。
密度曲线数据见 <code>density_curves.csv</code>（网格 241 点 × 3 指标 × 2 口径 × 2 组），
逐组统计见 <code>group_stats.csv</code>。名次口径 = 排名值 × 117。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
