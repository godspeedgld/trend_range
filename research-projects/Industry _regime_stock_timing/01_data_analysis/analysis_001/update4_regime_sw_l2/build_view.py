"""analysis_001 更新四 可视化 —— 变盘指数：申万一级(31) vs 申万二级(117)。

净值口径（skill 指标铁律）：trades 直接推算（nav_from_trades，固定名义不复利）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
A = HERE.parent
BLUE, AMBER, GRAY, RED = "#2b6cb0", "#b7791f", "#718096", "#c53030"

RUNS = [
    ("① W2 基准", A / "runs/w2pure/backtest_logs", BLUE),
    ("更新一（变盘指数 = 一级 31）", A / "update4_regime_sw_l2/runs/l1ctrl/backtest_logs", GRAY),
    ("★ 更新四（变盘指数 = 二级 117）", HERE / "runs/l2/backtest_logs", AMBER),
    ("④ analysis_001（无 MA200，一级）", A / "runs/new/backtest_logs", RED),
]


def main():
    fig = make_subplots(rows=2, cols=1,
                        subplot_titles=("净值（trades 口径 · 固定名义不复利）", "回撤 %"),
                        vertical_spacing=0.13, row_heights=[0.62, 0.38])
    rows = []
    for lab, d, c in RUNS:
        n = pd.read_csv(d / "nav_from_trades.csv")
        n["date"] = pd.to_datetime(n["date"])
        n["dd"] = (n["nav"] / n["nav"].cummax() - 1) * 100
        m = pd.read_csv(d / "metrics_from_trades.csv").iloc[0]
        t = pd.read_csv(d / "trades_paired.csv")["return_pct"]
        fig.add_scatter(x=n["date"], y=n["nav"], mode="lines", name=lab,
                        line=dict(color=c, width=2.4 if "★" in lab else 2.0), row=1, col=1)
        fig.add_scatter(x=n["date"], y=n["dd"], mode="lines", name=lab,
                        line=dict(color=c, width=1.5), showlegend=False, row=2, col=1)
        rows.append({"配置": lab, "笔数": int(m.n_trades), "总收益%": m.total_return * 100,
                     "年化%": m.annual_return * 100, "Sharpe": m.sharpe, "maxDD%": m.max_drawdown * 100,
                     "Calmar": m.calmar, "交易胜率%": m.win_rate_pct, "单笔均值%": t.mean(),
                     "肥尾率%": (t >= 30).mean() * 100, "失败率%": (t <= 0).mean() * 100})
    fig.add_hline(y=1.0, line=dict(color="#4a5568", width=1, dash="dot"), row=1, col=1)
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_layout(height=820, template="plotly_white", hovermode="x unified",
                      title=dict(text="analysis_001 更新四 — 变盘指数：申万一级(31) vs 申万二级(117)<br>"
                                      "<span style='font-size:12px;color:#718096'>"
                                      "两版判定一致率仅 66.8%，但回测结果几乎一样 · 其余规则与更新一完全相同</span>",
                                 x=0.5, font=dict(size=16)),
                      legend=dict(orientation="h", y=1.10, x=0.5, xanchor="center", font=dict(size=12)),
                      margin=dict(t=185, b=50))

    df = pd.DataFrame(rows)
    tbl = "".join(
        "<tr" + (" style=background:#f7fafc" if i % 2 else "") + ">"
        + f"<td style='padding:4px 12px'>{r['配置']}</td><td>{r['笔数']}</td>"
        + f"<td><b>{r['总收益%']:+.1f}</b></td><td>{r['年化%']:+.1f}</td><td>{r['Sharpe']:.3f}</td>"
        + f"<td>{r['maxDD%']:.1f}</td><td>{r['Calmar']:.2f}</td><td>{r['交易胜率%']:.1f}</td>"
        + f"<td>{r['单笔均值%']:+.2f}</td><td>{r['肥尾率%']:.1f}</td><td>{r['失败率%']:.1f}</td></tr>"
        for i, (_, r) in enumerate(df.iterrows()))

    l1 = df.iloc[1]
    l2 = df.iloc[2]

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_001 · 更新四</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：把更新一的变盘指数从<b>申万一级 31 个行业</b>换成<b>申万二级 117 个行业</b>，
算法完全相同。其余规则不变，优先级仍用一级行业收益率排名。</p>

<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:4px 12px;text-align:left'>配置</th><th>笔数</th>
<th>总收益%</th><th>年化%</th><th>Sharpe</th><th>maxDD%</th><th>Calmar</th><th>交易胜率%</th>
<th>单笔均值%</th><th>肥尾率%</th><th>失败率%</th></tr>
{tbl}</table>

<p style='margin-top:12px'><b>结论：二级 vs 一级——基本打平，二级略偏"进攻"。</b></p>
<ol>
<li><b>收益 +6.1pp、Sharpe +0.020</b>（{l1['总收益%']:+.1f}% → {l2['总收益%']:+.1f}%），
    略好但在噪音范围内；<b>但回撤深 3.3pp</b>（{l1['maxDD%']:.1f}% → {l2['maxDD%']:.1f}%），
    Calmar 反而低 {l1['Calmar']-l2['Calmar']:.2f}。<b>风险调整后两者不可区分。</b></li>
<li><b>💡 这本身是有价值的信息</b>：两版变盘指数的<b>判定一致率只有 66.8%</b>（近 1/3 的日子结论相反），
    但<b>最终回测结果几乎一样</b> → 说明
    <b>信号不来自某个特定的行业分层方式，而来自"行业排序扰动的方向"这个共性概念</b>。
    指标对横截面口径不敏感，是<b>稳健性的正面证据</b>。</li>
<li><b>❌ 但仍远不如 W2</b>（{l2['总收益%']:+.1f}% vs +186.7%）。连续第四个变体不如 W2 ——
    根因始终相同：<b>变盘指数当开仓闸门会大幅压缩开仓机会</b>
    （开门 863 天 vs MA200 的 2,755 天）。</li>
</ol>
<p style='color:#c53030'><b>⚠ 研报原意仍未测试（第四次记录）</b>：四轮都在把变盘指数当<b>开仓闸门</b>用，
而研报说的是 <b>T′ 符号决定用「动量」还是「反转」因子</b>。强烈建议下一轮直接做风格切换。</p>
<p style='color:#718096'>净值口径 = trades 直接推算（nav_from_trades，固定名义不复利）。
L1 对照档逐位复现更新一（total_return = 1.2257860746514515 / 352 笔），证明只改了变盘指数一个变量。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
