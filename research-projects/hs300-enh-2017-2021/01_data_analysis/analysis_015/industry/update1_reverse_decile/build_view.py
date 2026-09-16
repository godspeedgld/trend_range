"""analysis_015/industry 更新一 可视化 — 按收益分档反查行业热度（反向十分位）。

要点是**浅 U 型而非单调**，故：
  · 行1 给十档中位数 + P25–P75 带（让读者看清效应幅度 vs 档内离散度）+ 全局均值参考线
  · 行2 给分时段五分位，验证 U 型跨时段是否稳定
配色沿用已过 validate_palette.js 的 #2b6cb0(10日) / #b7791f(20日)；
行2 用线型（实线 2017-2020 / 虚线 2021-2026）做时段次级编码。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
BLUE, AMBER, GRAY = "#2b6cb0", "#b7791f", "#718096"


def main():
    dec = {v: pd.read_csv(HERE / f"ret_decile_{v}.csv", index_col=0)
           for v in ["H10_RAW", "H10_DM", "H20_RAW", "H20_DM"]}
    per = pd.read_csv(HERE / "period_split.csv")
    summ = pd.read_csv(HERE / "summary.csv")
    base = (HERE / "baseline.txt").read_text(encoding="utf-8")
    m_fail = re.search(r"失败率%\(ret≤0\)=([\d.]+)", base)
    m_fat = re.search(r"肥尾率%\(ret≥30\)=([\d.]+)", base)

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=("原始横截面排名 · 十档　<span style='font-size:11px;color:#718096'>"
                        "灰虚线=十档中位数的中位数 · 蓝带=10日档内 P25–P75</span>",
                        "行业内中性化 · 十档　<span style='font-size:11px;color:#718096'>"
                        "灰虚线=十档中位数的中位数 · 蓝带=10日档内 P25–P75</span>",
                        "原始 · 分时段五分位（实线 2017-2020 / 虚线 2021-2026）",
                        "行业内 · 分时段五分位（实线 2017-2020 / 虚线 2021-2026）"),
        vertical_spacing=0.19, horizontal_spacing=0.09)

    # ── 行1：十档中位数 + IQR 带 + 全局均值参考线 ──
    for j, (raw, dm) in enumerate([("H10_RAW", "H20_RAW"), ("H10_DM", "H20_DM")]):
        t10, t20 = dec[raw], dec[dm]
        x = [f"D{int(i)}" for i in t10.index]
        # IQR 带（仅 10 日，浅色）
        fig.add_scatter(x=x, y=t10["热度P25"], mode="lines", line=dict(width=0),
                        showlegend=False, hoverinfo="skip", row=1, col=j + 1)
        fig.add_scatter(x=x, y=t10["热度P75"], mode="lines", line=dict(width=0),
                        fill="tonexty", fillcolor="rgba(43,108,176,0.13)",
                        showlegend=False, hoverinfo="skip", row=1, col=j + 1)
        fig.add_scatter(x=x, y=t10["热度中位数"], mode="lines+markers",
                        name="10 日窗口", line=dict(color=BLUE, width=2),
                        marker=dict(color=BLUE, size=9), legendgroup="w10",
                        showlegend=(j == 0), row=1, col=j + 1,
                        hovertemplate="%{x} 10日 %{y:.3f}<extra></extra>")
        fig.add_scatter(x=x, y=t20["热度中位数"], mode="lines+markers",
                        name="20 日窗口", line=dict(color=AMBER, width=2, dash="dot"),
                        marker=dict(color=AMBER, size=9, symbol="square"), legendgroup="w20",
                        showlegend=(j == 0), row=1, col=j + 1,
                        hovertemplate="%{x} 20日 %{y:.3f}<extra></extra>")
        # 全局均值参考线（全部样本的热度中位数）
        allmed = t10["热度中位数"].median()
        fig.add_hline(y=allmed, line=dict(color=GRAY, width=1.2, dash="dash"), row=1, col=j + 1)
        for k in (0, len(x) - 1):
            fig.add_annotation(x=x[k], y=t10["热度中位数"].iloc[k],
                               text=f"{t10['热度中位数'].iloc[k]:.3f}", showarrow=False,
                               yshift=16, xshift=-4 if k == 0 else 4,
                               font=dict(size=10.5, color=BLUE), row=1, col=j + 1)

    # ── 行2：分时段五分位（色=窗口10日, 线型=时段）──
    for j, var in enumerate(["10日·原始", "10日·行业内"]):
        sub = per[per["变体"] == var]
        for seg, dash in [("2017-2020", "solid"), ("2021-2026", "dash")]:
            row = sub[sub["时段"] == seg]
            if row.empty:
                continue
            r = row.iloc[0]
            ys = [r[f"Q{k}热度中位"] for k in range(1, 6)]
            fig.add_scatter(x=[f"Q{k}" for k in range(1, 6)], y=ys, mode="lines+markers",
                            name=seg, line=dict(color=BLUE, width=2, dash=dash),
                            marker=dict(color=BLUE, size=8, symbol="circle" if dash == "solid" else "square"),
                            showlegend=False, row=2, col=j + 1,
                            hovertemplate=f"{seg} %{{x}} %{{y:.3f}}<extra></extra>")

    fig.update_yaxes(title_text="行业热度中位数（分位数）", row=1, col=1)
    fig.update_yaxes(title_text="行业内中性化 · 热度中位数", row=1, col=2)
    fig.update_yaxes(title_text="热度中位数", row=2, col=1)
    fig.update_yaxes(title_text="行业内 · 热度中位数", row=2, col=2)
    for c in (1, 2):
        fig.update_xaxes(title_text="突破收益十分位（D1 最差 → D10 最好）", row=1, col=c)
        fig.update_xaxes(title_text="突破收益五分位（Q1 最差 → Q5 最好）", row=2, col=c)

    fig.update_layout(height=900, template="plotly_white", hovermode="x unified",
                      title=dict(text="analysis_015 · industry 更新一 — 反向十分位：按突破收益分档，反查行业热度"
                                      "（9018 笔，10 日/20 日 × 原始/行业内）",
                                 x=0.5, font=dict(size=16)),
                      legend=dict(orientation="h", y=1.10, x=0.5, xanchor="center", font=dict(size=12)),
                      margin=dict(t=190, b=60))

    rows_html = "".join(
        f"<tr><td>{r['变体']}</td><td>{r['档↔热度中位数']:+.2f}</td>"
        f"<td>{r['D1热度中位']:.3f}</td><td>{r['D10热度中位']:.3f}</td>"
        f"<td>{r['D10−D1']:+.3f}</td></tr>" for _, r in summ.iterrows())

    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset='utf-8'>
<title>analysis_015 · industry · 更新一</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>设计</b>：按每笔突破的 <code>ret</code>（突破后已实现收益）分十档等频（每档 854 笔，共 {int(dec['H10_RAW']['n'].sum())} 笔），
再看每档的行业热度中位数。热度 = sw2021 二级行业（117 个）的「近 10 日收益率横截面排名均值」，信号日 t 取值。</p>

<p><b>读出来的形状是浅 U 型，不是单调线：</b>D1（最差，收益中位 −17.4%）热度最高 <b>0.581</b>，
一路降到 D6（−4.0%）的 <b>0.559</b>，再回升到 D10（肥尾档 +35.2%）的 <b>0.571</b>。
两个极端档都比中段更热。</p>

<p><b>四变体对照（Spearman 单调性检验）：</b></p>
<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#f7fafc'><th style='padding:4px 12px;text-align:left'>变体</th>
<th style='padding:4px 12px'>档↔热度中位数</th><th style='padding:4px 12px'>D1</th>
<th style='padding:4px 12px'>D10</th><th style='padding:4px 12px'>D10−D1</th></tr>
{rows_html}</table>

<p style='margin-top:12px'><b>结论：</b></p>
<ol>
<li><b>你的人工理解方向反了</b>——若看单调性，是"收益越高、行业越冷"（Spearman −0.18 ~ −0.45）。</li>
<li><b>但单调性这个检验在这儿是错的工具</b>：真实形状是 U 型，Spearman 只抓住了下半段。
按 U 型读，<b>你的直觉部分成立</b>：肥尾档（D10）确实来自偏热的行业，而亏损最惨的档（D1）来自<b>最</b>热的行业
——热门行业的突破<b>结果更极端</b>（尾部更厚），这与策略"高失败 + 右尾彩票"的本质一致。</li>
<li><b>⚠ 幅度很小</b>：D1↔D6 差 0.022、D1↔D10 差 0.010，而档内 P25–P75 带宽约 0.14
（图中蓝色带）——效应只有档内离散度的 ~1/6。D1↔D6 的 0.022 在 n=854/档下约 5 个标准误，
统计上可辨，但经济意义有限。</li>
<li><b>U 型跨时段稳定</b>：2017-2020 与 2021-2026 两段的五分位都是两端高中间低（下图）。</li>
<li>附带发现：<code>ret</code> 分布双峰——D1–D6 <b>全是失败单</b>（100% ret≤0，只是亏多亏少），
D8–D9 零失败，D10 肥尾率 62.2%。所以"收益十分位"实际是在分「亏多少」和「赚多少」，
<b>失败率本身是分档的函数</b>，不宜再当被解释变量（这点与父目录"按热度分档"的口径不同）。</li>
</ol>
<p style='color:#718096'>基线：失败率 {m_fail.group(1) if m_fail else '65.9'}% / 肥尾率 {m_fat.group(1) if m_fat else '7.2'}%。
行业内中性化用 causal expanding 基线（仅 t 之前历史，min_periods=250），无父目录诊断版的前视问题。
数据表见同目录 CSV（<code>ret_decile_*.csv</code> / <code>summary.csv</code> / <code>period_split.csv</code>）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
