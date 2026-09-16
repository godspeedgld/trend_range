"""analysis_015/industry 可视化 — 行业热度十档 + 行业固定效应剥离（符号翻转）。

配色（已过 validate_palette.js 六项检查，light 面色）：
  原始(水平截面排名) = #2b6cb0 蓝实线
  行业内(去均值)     = #b7791f 琥珀虚线   ← 虚线=次级编码，不依赖颜色单独区分
  最差相邻 CVD ΔE 8.1(deutan) / 正常视觉 15.4 —— 配合虚线+图例+直接标注
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER = "#2b6cb0", "#b7791f"          # 原始 / 行业内
GRAY = "#718096"
METRICS = [("RET", "收益率排名均值"), ("TURN", "换手率排名均值"), ("VOL", "成交量排名均值")]


def main():
    raw = {n: pd.read_csv(HERE / f"HEAT_{n}_decile.csv", index_col=0) for n, _ in METRICS}
    dm = {n: pd.read_csv(HERE / f"HEAT_{n}_decile_dm.csv", index_col=0) for n, _ in METRICS}
    flip = pd.read_csv(HERE / "sign_flip.csv")
    base = (HERE / "baseline.txt").read_text(encoding="utf-8")

    fig = make_subplots(
        rows=3, cols=3,
        specs=[[{"colspan": 3}, None, None], [{}, {}, {}], [{}, {}, {}]],
        subplot_titles=("【头条】剥离行业固定效应后的符号翻转：档位↔均值 Spearman",
                        *[f"{lab} 十档 · 单笔均值%" for _, lab in METRICS],
                        *[f"{lab} 十档 · 失败率%" for _, lab in METRICS]),
        row_heights=[0.30, 0.35, 0.35], vertical_spacing=0.11, horizontal_spacing=0.07)

    # ── 行1：符号翻转（分组柱，颜色=口径，正负由几何表达）──
    xcat = flip["特征"].tolist()
    for series, col_name, color, line in [
            ("原始（水平截面排名）", "原始_档↔均值", BLUE, None),
            ("行业内（去均值）", "行业内_档↔均值", AMBER, None)]:
        fig.add_bar(x=xcat, y=flip[col_name], name=series, marker_color=color,
                    marker_line_width=0, text=[f"{v:+.2f}" for v in flip[col_name]],
                    textposition="outside", textfont=dict(size=12, color="#2d3748"),
                    cliponaxis=False, legendgroup=series, showlegend=False,
                    row=1, col=1)
    fig.add_hline(y=0, line=dict(color="#4a5568", width=1.5), row=1, col=1)
    fig.update_yaxes(range=[-1.15, 1.15], title_text="Spearman", row=1, col=1)
    fig.update_xaxes(tickfont=dict(size=13), row=1, col=1)

    # ── 行2/3：十档曲线（同一子图内单一度量，无双轴）──
    xd = [f"D{k}" for k in range(1, 11)]
    for i, (name, lab) in enumerate(METRICS):
        for row, col_key, ttl in [(2, "均值%", "均值"), (3, "失败率%(ret≤0)", "失败率")]:
            r_, d_ = raw[name][col_key], dm[name][col_key]
            fig.add_scatter(x=xd, y=r_, mode="lines+markers", name="原始（水平截面排名）",
                            line=dict(color=BLUE, width=2), marker=dict(color=BLUE, size=8),
                            legendgroup="原始（水平截面排名）", showlegend=(row == 2 and i == 0),
                            row=row, col=i + 1, hovertemplate="%{x} 原始 %{y:.2f}<extra></extra>")
            fig.add_scatter(x=xd, y=d_, mode="lines+markers", name="行业内（去均值）",
                            line=dict(color=AMBER, width=2, dash="dash"),
                            marker=dict(color=AMBER, size=8, symbol="square"),
                            legendgroup="行业内（去均值）", showlegend=(row == 2 and i == 0),
                            row=row, col=i + 1, hovertemplate="%{x} 行业内 %{y:.2f}<extra></extra>")
            if row == 2:   # 仅均值行加端点直接标注
                for s, c in [(r_, BLUE), (d_, AMBER)]:
                    for k in (0, 9):
                        fig.add_annotation(x=xd[k], y=s.iloc[k], text=f"{s.iloc[k]:+.1f}",
                                           showarrow=False, yshift=14 if k == 0 else -16,
                                           xshift=-6 if k == 0 else 6,
                                           font=dict(size=10.5, color=c), row=row, col=i + 1)
            if row == 3:   # 失败率行加基线参考线
                m = re.search(r"失败率%\(ret≤0\)\s+([\d.]+)", base)
                if m:
                    fig.add_hline(y=float(m.group(1)), line=dict(color=GRAY, width=1, dash="dot"),
                                  row=row, col=i + 1)

    for i in range(3):
        fig.update_yaxes(title_text="%", row=2, col=i + 1)
        fig.update_yaxes(title_text="%", row=3, col=i + 1)
        fig.update_xaxes(title_text="热度十档（D1 最低 → D10 最高）", row=3, col=i + 1)

    fig.update_layout(
        height=1180, template="plotly_white", barmode="group", bargap=0.42, bargroupgap=0.12,
        hovermode="closest",
        title=dict(text="analysis_015 · industry — 二级行业热门度对 v4 阻力带突破的区分力"
                        "（9018 笔已判定，2017-2026，纯 v4 无闸门）",
                   x=0.5, font=dict(size=16)),
        legend=dict(orientation="h", y=1.075, x=0.5, xanchor="center", font=dict(size=12)),
        margin=dict(t=210, b=60))

    comp = pd.read_csv(HERE / "d10_composition_raw.csv")
    comp_html = "".join(
        f"<li><b>{r['指标']}</b> {r['档']}：{r['行业'].replace(' | ', ' / ')}"
        f"（{r['占比%'].replace(' | ', '% / ')}%）</li>" for _, r in comp.iterrows())

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset='utf-8'>
<title>analysis_015 · industry</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.75;padding:4px 8px 40px'>
<p><b>基线</b>（全体 11100 笔）：失败率 65.9% / 成功率 33.4% / 肥尾率 7.2% / 均值 +1.57% / 中位 −5.12%。
样本 = v4 活带突破（analysis_012 <code>detail_v4.parquet</code>，deg≥2，静态 4ATR 止损 + 前日 ATR 吊灯，无任何 regime/形态过滤）。
热度定义：sw2021 二级行业（117 个）的日频横截面排名 → 20 日均值，信号日 t 取值。</p>

<p><b>要点：</b></p>
<ol>
<li><b>原始口径会给出错误结论。</b>换手率排名 原始 档↔均值 <b>+0.77</b>（"高换手行业突破更好"），
剥离行业固定效应后翻转为 <b>−0.83</b>（"行业相对自己放量 → 突破更差"）。典型辛普森悖论。</li>
<li><b>为什么翻。</b>原始 D10 被行业身份证塞满——</li>
<ul style='margin:6px 0'>{comp_html}</ul>
<li><b>剥离后两个活跃度指标都是强负向且单调</b>：成交量 −0.94（D1 +5.56% 失败 58.8 / D10 −2.53% 失败 70.0）、
换手率 −0.83（D1 +2.47% / D10 −3.48% 失败 75.5）。</li>
<li><b>收益率热度基本无效</b>（原始 +0.02、行业内 −0.25），建议砍掉。</li>
<li>与 analysis_014 <b>个股层面</b>「巨量禁区」（RV D10 失败率 72.9%）方向一致——<b>两个层级同向，证据强度升级</b>。</li>
</ol>
<p style='color:#718096'>⚠ 行业内去均值用全样本行业均值，有轻微前视，本图仅作机理诊断；结论须待因果版
（rolling/expanding 基线）确认。三指标原始相关极低（0.02~0.17）。
数据表见同目录 CSV（<code>HEAT_*_decile.csv</code> / <code>_decile_dm.csv</code> / <code>sign_flip.csv</code>）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
