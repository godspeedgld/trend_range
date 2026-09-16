"""成功/失败各自独立的全套分布图（与全案例 build_view 同构）。

每块含：总体瓦片 + ret 5%桶分布 + degree 箱线(均值点) + decile 箱线(均值点)。
成功组 ret>0，失败组 ret<=0。输出 sf_view.html（上下两块，各自完整）。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
inp = pd.read_csv(HERE / "stats_input.csv")
inp = inp.dropna(subset=["decile"]).copy()
inp["ok"] = inp["ret_pct"] > 0
inp["g_deg"] = inp["degree"].apply(lambda d: d if d <= 11 else 99)
inp["g_deg_lab"] = inp["g_deg"].map({**{i: str(i) for i in range(2, 12)}, 99: "12+"})


def group_panel(sub, name, color, ret_lo, ret_hi):
    """组内全套：瓦片 + 桶 + degree + decile。返回 (fig_html, tiles_html)。"""
    wins = sub[sub["ret_pct"] > 0]
    overall = {
        "n": len(sub), "win_rate": len(wins) / len(sub),
        "mean": sub["ret_pct"].mean(), "median": sub["ret_pct"].median(),
        "payoff": (wins["ret_pct"].mean() / abs(sub.loc[sub["ret_pct"] <= 0, "ret_pct"].mean()))
        if len(wins) and (sub["ret_pct"] <= 0).any() else np.nan,
    }
    # 5% 桶（组内适配范围）
    edges = list(range(int(ret_lo), int(ret_hi) + 1, 5))
    labels = [f"<{edges[0]}"] + [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges) - 1)] \
             + [f">={edges[-1]}"]
    sub2 = sub.copy()
    sub2["bucket"] = pd.cut(sub2["ret_pct"], bins=[-np.inf] + edges + [np.inf],
                            labels=labels, right=False)
    bucket = (sub2.groupby("bucket", observed=False)["ret_pct"]
              .agg(n="count", mean="mean").reset_index())

    fig = make_subplots(rows=2, cols=2, subplot_titles=(
        f"{name} ret 5% bucket (n)", f"{name} by degree: box(IQR)+mean dot",
        f"{name} by decile: box(IQR)+mean dot", f"{name} mean ret% (degree vs decile)"))
    fig.add_trace(go.Bar(x=bucket["bucket"].astype(str), y=bucket["n"], name="n",
                         marker_color=color), row=1, col=1)
    # degree 箱线（2..11 + 12+ 尾）
    dg_ord = [str(i) for i in range(2, 12)] + ["12+"]
    for lab in dg_ord:
        y = sub[sub["g_deg_lab"] == lab]["ret_pct"]
        if len(y):
            fig.add_trace(go.Box(y=y, name=lab, boxpoints=False, line=dict(width=1),
                                 marker_color="#7f8c8d"), row=1, col=2)
    md = sub.groupby("g_deg_lab")["ret_pct"].mean()
    fig.add_trace(go.Scatter(x=[l for l in dg_ord if l in md.index],
                             y=[md[l] for l in dg_ord if l in md.index],
                             name="mean", mode="markers", marker=dict(color=color, size=9)),
                  row=1, col=2)
    # decile 箱线
    for d in range(1, 11):
        y = sub[sub["decile"] == d]["ret_pct"]
        if len(y):
            fig.add_trace(go.Box(y=y, name=f"d{d}", boxpoints=False,
                                 line=dict(width=1), marker_color="#8e44ad"), row=2, col=1)
    mdc = sub.groupby("decile")["ret_pct"].mean()
    fig.add_trace(go.Scatter(x=list(range(1, 11)), y=mdc.reindex(range(1, 11)),
                             name="mean", mode="markers+lines",
                             marker=dict(color="#f39c12", size=7)), row=2, col=1)
    # 期望：decile 线 + degree 线
    fig.add_trace(go.Scatter(x=list(range(1, 11)), y=mdc.reindex(range(1, 11)),
                             name="decile mean%", mode="lines+markers",
                             line=dict(color="#8e44ad")), row=2, col=2)
    fig.add_trace(go.Scatter(x=list(range(2, 12)), y=md.reindex([str(i) for i in range(2, 12)]),
                             name="degree mean%", mode="lines+markers",
                             line=dict(color=color)), row=2, col=2)
    fig.update_layout(template="plotly_white", height=720, boxmode="overlay",
                      margin=dict(l=50, r=20, t=60, b=30),
                      legend=dict(orientation="h", y=1.04))
    tiles = (f"<div class='item'><span>样本</span><b>{int(overall['n'])}</b></div>"
             f"<div class='item'><span>组内成功率</span><b>{overall['win_rate']*100:.1f}%</b></div>"
             f"<div class='item'><span>组内均值</span><b>{overall['mean']:+.2f}%</b></div>"
             f"<div class='item'><span>组内中位</span><b>{overall['median']:+.2f}%</b></div>")
    return fig.to_html(full_html=False, include_plotlyjs=False), tiles


ok = inp[inp["ok"]]
bad = inp[~inp["ok"]]
fig_ok, tiles_ok = group_panel(ok, "成功组 (ret>0)", "#c0392b", 0, 60)
fig_bad, tiles_bad = group_panel(bad, "失败组 (ret≤0)", "#27ae60", -35, 0)

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_007 sf 独立分布</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:10px 4px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
h3{{border-top:2px solid #eee;padding-top:18px;}}
</style></head><body>
<h2>analysis_007 更新七 — 成功/失败各自独立分布（与全案例同构）</h2>
<div class="note">成功组 = ret&gt;0（3834 笔）；失败组 = ret≤0（9108 笔）。各块瓦片+ret桶+degree箱线+
decile箱线+期望线，同全案例 build_view 版式，可分别与"全案例"页对照。</div>

<h3>① 成功组（3834 笔，右尾量级分布）</h3>
<div class="metrics">{tiles_ok}</div>
{fig_ok}

<h3>② 失败组（9108 笔，止损成本分布）</h3>
<div class="metrics">{tiles_bad}</div>
{fig_bad}
</body></html>"""
(HERE / "sf_view.html").write_text(html, encoding="utf-8")
print("sf_view.html 已生成（成功+失败两独立块）")
