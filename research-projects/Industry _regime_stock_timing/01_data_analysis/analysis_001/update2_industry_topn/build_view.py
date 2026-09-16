"""analysis_001 更新二 可视化 —— 行业「过滤」vs「排序」。

净值口径（skill 指标铁律）：trades 直接推算（nav_from_trades，固定名义不复利）。
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
A = HERE.parent                                  # analysis_001
BLUE, AMBER, RED, GRAY = "#2b6cb0", "#b7791f", "#c53030", "#718096"

RUNS = [
    ("① W2 基准", A / "runs/w2pure/backtest_logs", BLUE),
    ("★ 更新一（行业排序，无过滤）", A / "update1_ma200_and_regime/runs/u1/backtest_logs", AMBER),
    ("更新二·前10行业（对照）", HERE / "runs/top10/backtest_logs", GRAY),
    ("更新二·前5行业（主档）", HERE / "runs/top5/backtest_logs", RED),
]


def main():
    fig = make_subplots(rows=2, cols=1, subplot_titles=("净值（trades 口径 · 固定名义不复利）", "回撤 %"),
                        vertical_spacing=0.13, row_heights=[0.62, 0.38])
    rows = []
    for lab, d, c in RUNS:
        n = pd.read_csv(d / "nav_from_trades.csv")
        n["date"] = pd.to_datetime(n["date"])
        n["dd"] = (n["nav"] / n["nav"].cummax() - 1) * 100
        m = pd.read_csv(d / "metrics_from_trades.csv").iloc[0]
        t = pd.read_csv(d / "trades_paired.csv")["return_pct"]
        fig.add_scatter(x=n["date"], y=n["nav"], mode="lines", name=lab, line=dict(color=c, width=2.2),
                        row=1, col=1)
        fig.add_scatter(x=n["date"], y=n["dd"], mode="lines", name=lab, line=dict(color=c, width=1.5),
                        showlegend=False, row=2, col=1)
        rows.append({"配置": lab, "笔数": int(m.n_trades), "总收益%": m.total_return * 100,
                     "年化%": m.annual_return * 100, "Sharpe": m.sharpe, "maxDD%": m.max_drawdown * 100,
                     "Calmar": m.calmar, "交易胜率%": m.win_rate_pct, "单笔均值%": t.mean(),
                     "肥尾率%": (t >= 30).mean() * 100, "失败率%": (t <= 0).mean() * 100})
    fig.add_hline(y=1.0, line=dict(color="#4a5568", width=1, dash="dot"), row=1, col=1)
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_layout(height=820, template="plotly_white", hovermode="x unified",
                      title=dict(text="analysis_001 更新二 — 行业「过滤」vs「排序」<br>"
                                      "<span style='font-size:12px;color:#718096'>"
                                      "只允许行业收益率排名前 N 名开仓 · 其余规则与更新一完全相同</span>",
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

    u1 = df.iloc[1]
    t5 = df.iloc[3]
    t10 = df.iloc[2]

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_001 · 更新二</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：把更新一的"行业排名<b>排序</b>"改成"行业排名<b>过滤</b>"——只允许前 N 名行业开仓，
组内按 COMBO 排序。其余完全相同，<b>预计算零重算</b>。</p>

<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:4px 12px;text-align:left'>配置</th><th>笔数</th>
<th>总收益%</th><th>年化%</th><th>Sharpe</th><th>maxDD%</th><th>Calmar</th><th>交易胜率%</th>
<th>单笔均值%</th><th>肥尾率%</th><th>失败率%</th></tr>
{tbl}</table>

<p style='margin-top:12px'><b>结论：更新二失败 ——「过滤」比不过「排序」。</b></p>
<ol>
<li><b>过滤越严，收益越低</b>：无过滤 {u1['总收益%']:+.1f}% → 前10 {t10['总收益%']:+.1f}%（{t10['总收益%']-u1['总收益%']:+.1f}pp）
    → 前5 <b>{t5['总收益%']:+.1f}%</b>（<b>{t5['总收益%']-u1['总收益%']:+.1f}pp</b>）。
    Sharpe 同向：{u1['Sharpe']:.3f} → {t10['Sharpe']:.3f} → <b>{t5['Sharpe']:.3f}</b>。</li>
<li><b>被滤掉的交易是正贡献的</b>：前5 过滤掉 {int(u1['笔数']-t5['笔数'])} 笔，这
    {int(u1['笔数']-t5['笔数'])} 笔合计贡献约 <b>{t5['总收益%']-u1['总收益%']:+.1f}pp</b>
    —— 行业排名 6~31 的行业开出的仓<b>整体是赚钱的</b>。</li>
<li><b>踩了项目的设计定律：排序 ≫ 开关</b>（analysis_014 三杠杆归因）。
    排序是"软"的（次优行业仍有机会），过滤是"硬"的（直接放弃，无论坑位空不空）。
    本更新把行业排名从<b>排序键</b>降级成<b>硬阈值</b>，正好踩了这条定律。</li>
<li><b>但行业排名确实携带质量信息</b>：前5 过滤同时<b>提升胜率</b>（{u1['交易胜率%']:.1f}% → {t5['交易胜率%']:.1f}%）
    与<b>肥尾率</b>（{u1['肥尾率%']:.1f}% → {t5['肥尾率%']:.1f}%），并<b>压低回撤</b>（{u1['maxDD%']:.1f}% → {t5['maxDD%']:.1f}%）。
    只是用"过滤"表达会损失太多机会 —— 应保持在排序里，或做<b>加分项</b>而非门槛。</li>
</ol>
<p style='color:#c53030'><b>⚠ 研报原意仍未测试</b>（连续第三次记录）：研报说 T′ 符号决定用
<b>动量还是反转因子</b>，本更新仍是把它当<b>开仓闸门</b>用。建议下一轮直接做风格切换。</p>
<p style='color:#718096'>净值口径 = trades 直接推算（nav_from_trades，固定名义不复利）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
