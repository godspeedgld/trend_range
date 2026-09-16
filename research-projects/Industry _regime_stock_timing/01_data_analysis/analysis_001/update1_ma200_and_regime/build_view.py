"""analysis_001 更新一 可视化 —— 双过滤 vs 各对照档。

净值口径（skill 指标铁律）：**trades 直接推算**（nav_from_trades，固定名义不复利），
不用引擎 equity_curve（复利路径 + 归因近似）。

配色：#2b6cb0 W2基准(蓝) · #b7791f 更新一(琥珀) · #c53030 analysis_001(红) · #718096 更新一·对照(灰)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
P = HERE.parent                                  # analysis_001
BLUE, AMBER, RED, GRAY = "#2b6cb0", "#b7791f", "#c53030", "#718096"

RUNS = [
    ("① W2 基准（MA200 + COMBO优先）", P / "runs/w2pure/backtest_logs", BLUE),
    ("★ 更新一（双过滤 + 行业优先）", HERE / "runs/u1/backtest_logs", AMBER),
    ("更新一·对照（双过滤 + COMBO优先）", HERE / "runs/u1_combo/backtest_logs", GRAY),
    ("④ analysis_001（变盘下行 + 行业优先）", P / "runs/new/backtest_logs", RED),
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
        fig.add_scatter(x=n["date"], y=n["nav"], mode="lines", name=lab,
                        line=dict(color=c, width=2.2), row=1, col=1)
        fig.add_scatter(x=n["date"], y=n["dd"], mode="lines", name=lab,
                        line=dict(color=c, width=1.5), showlegend=False, row=2, col=1)
        rows.append({"配置": lab, "笔数": int(m.n_trades), "总收益%": m.total_return * 100,
                     "年化%": m.annual_return * 100, "Sharpe": m.sharpe,
                     "maxDD%": m.max_drawdown * 100, "Calmar": m.calmar,
                     "交易胜率%": m.win_rate_pct, "单笔均值%": t.mean(),
                     "肥尾率%": (t >= 30).mean() * 100, "失败率%": (t <= 0).mean() * 100})
    fig.add_hline(y=1.0, line=dict(color="#4a5568", width=1, dash="dot"), row=1, col=1)
    fig.update_yaxes(title_text="净值", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    fig.update_layout(height=820, template="plotly_white", hovermode="x unified",
                      title=dict(text="analysis_001 更新一 — 双过滤（MA200 ∩ 变盘指数下行）<br>"
                                      "<span style='font-size:12px;color:#718096'>开门日 676 天"
                                      "（占 MA200 的 25%）· 其余规则与 analysis_001 完全相同</span>",
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

    u1 = df[df['配置'].str.startswith('★')].iloc[0]
    a1 = df[df['配置'].str.startswith('④')].iloc[0]
    w2 = df[df['配置'].str.startswith('①')].iloc[0]

    html = f"""<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>
<title>analysis_001 · 更新一</title></head>
<body style='font-family:system-ui;max-width:1320px;margin:auto;background:#fff;color:#1a202c'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<div style='color:#4a5568;font-size:13.5px;line-height:1.8;padding:4px 8px 40px'>
<p><b>做法</b>：在 analysis_001（④ 变盘下行 + 行业优先）基础上，把 <b>MA200 加回作为第二个过滤条件</b>
（AND）。其余规则完全相同，<b>预计算零重算</b>（直接用 ../_precomputed/）。</p>

<table style='border-collapse:collapse;font-size:13px'>
<tr style='background:#edf2f7'><th style='padding:4px 12px;text-align:left'>配置</th><th>笔数</th>
<th>总收益%</th><th>年化%</th><th>Sharpe</th><th>maxDD%</th><th>Calmar</th><th>交易胜率%</th>
<th>单笔均值%</th><th>肥尾率%</th><th>失败率%</th></tr>
{tbl}</table>

<p style='margin-top:12px'><b>结论：变盘指数的正确用法是「叠加」而非「替代」——但仍不如纯 W2。</b></p>
<ol>
<li><b>对 analysis_001 大幅改善 ✓</b>：{u1['总收益%']:+.1f}% vs {a1['总收益%']:+.1f}%（<b>+{u1['总收益%']-a1['总收益%']:.1f}pp</b>），
    Sharpe {a1['Sharpe']:.3f} → <b>{u1['Sharpe']:.3f}</b>，maxDD {a1['maxDD%']:.1f}% → <b>{u1['maxDD%']:.1f}%</b>，
    Calmar {a1['Calmar']:.2f} → {u1['Calmar']:.2f}。<b>把 MA200 加回来效果提升非常显著</b>，
    印证"<b>不能替代、但可以叠加</b>"。</li>
<li><b>对 W2 基准仍差</b>：{u1['总收益%']:+.1f}% vs {w2['总收益%']:+.1f}%（<b>{u1['总收益%']-w2['总收益%']:+.1f}pp</b>），
     Sharpe {u1['Sharpe']:.3f} vs {w2['Sharpe']:.3f}。双过滤把开门日压到 <b>676 天（MA200 的 25%）</b>，
    交易数 468 → 352，<b>牺牲的开仓机会太多</b>，收益损失大于回撤改善。</li>
<li><b>定位：防守型变体</b>。maxDD <b>{u1['maxDD%']:.1f}%</b> 是各档里最浅之一（比 W2 的 {w2['maxDD%']:.1f}% 还浅），
    但收益不足 —— 与 strategy_009 的定位类似。</li>
<li><b>优先级效应随闸门收紧而反转</b>：MA200 下行业优先 −27.6pp、变盘下行下 +16.1pp、双过滤下 +3.3pp
    —— <b>「特征-脚手架耦合定律」第三次兑现</b>。</li>
</ol>
<p style='color:#c53030'><b>⚠ 研报的原意仍未测试</b>：研报说 T′ 符号决定用<b>动量还是反转因子</b>，
本更新仍是把它当<b>开仓闸门</b>用。下一步应做「风格切换」方向的验证。</p>
<p style='color:#718096'>净值口径 = trades 直接推算（nav_from_trades，固定名义不复利）。</p>
</div></body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
