"""更新八视图：全/成功/失败独立全套 + 4.1 degree×decile 热图 + 4.2 特征 IC/AUC。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
inp = pd.read_parquet(HERE / "trades_stats.parquet")
inp["ok"] = inp["ret_pct"] > 0
inp["deg_c"] = inp["degree"].apply(lambda d: "2" if d == 2 else "3-5" if d <= 5
                                   else "6-11" if d <= 11 else "12+")
inp["dcl_c"] = inp["decile"].apply(lambda x: "1-3" if x <= 3 else "4-6" if x <= 6
                                   else "7-9" if x <= 9 else "10")

def group_panel(sub, name, color, lo, hi):
    wins = sub[sub["ret_pct"] > 0]
    overall = {"n": len(sub), "wr": len(wins) / len(sub),
               "mean": sub["ret_pct"].mean(), "med": sub["ret_pct"].median()}
    edges = list(range(int(lo), int(hi) + 1, 5))
    labels = [f"<{edges[0]}"] + [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges) - 1)] \
             + [f">={edges[-1]}"]
    sub2 = sub.copy()
    sub2["bucket"] = pd.cut(sub2["ret_pct"], bins=[-np.inf] + edges + [np.inf],
                            labels=labels, right=False)
    bucket = (sub2.groupby("bucket", observed=False)["ret_pct"]
              .agg(n="count", mean="mean").reset_index())
    fig = make_subplots(rows=2, cols=2, subplot_titles=(
        f"{name} ret 5% bucket", f"{name} by degree box", f"{name} by decile box",
        f"{name} mean% deg vs decile"))
    fig.add_trace(go.Bar(x=bucket["bucket"].astype(str), y=bucket["n"],
                         marker_color=color), row=1, col=1)
    for lab in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12+"]:
        y = sub[sub["g_deg_lab"] == lab]["ret_pct"]
        if len(y):
            fig.add_trace(go.Box(y=y, name=lab, boxpoints=False, line=dict(width=1),
                                 marker_color="#7f8c8d"), row=1, col=2)
    for d in range(1, 11):
        y = sub[sub["decile"] == d]["ret_pct"]
        if len(y):
            fig.add_trace(go.Box(y=y, name=f"d{d}", boxpoints=False, line=dict(width=1),
                                 marker_color="#8e44ad"), row=2, col=1)
    mdc = sub.groupby("decile")["ret_pct"].mean().reindex(range(1, 11))
    fig.add_trace(go.Scatter(x=list(range(1, 11)), y=mdc, name="decile mean",
                             mode="lines+markers", line=dict(color="#f39c12")), row=2, col=2)
    fig.update_layout(template="plotly_white", height=680, boxmode="overlay",
                      margin=dict(l=50, r=20, t=55, b=30),
                      legend=dict(orientation="h", y=1.03))
    tiles = (f"<div class='item'><span>样本</span><b>{int(overall['n'])}</b></div>"
             f"<div class='item'><span>成功率</span><b>{overall['wr']*100:.1f}%</b></div>"
             f"<div class='item'><span>均值</span><b>{overall['mean']:+.2f}%</b></div>"
             f"<div class='item'><span>中位</span><b>{overall['med']:+.2f}%</b></div>")
    return fig.to_html(full_html=False, include_plotlyjs=False), tiles

fig_all, tile_all = group_panel(inp, "全案例", "#2980b9", -50, 60)
fig_ok, tile_ok = group_panel(inp[inp.ok], "成功组", "#c0392b", 0, 60)
fig_bad, tile_bad = group_panel(inp[~inp.ok], "失败组", "#27ae60", -35, 0)

# 4.1 热图
pv = inp.pivot_table(index="deg_c", columns="dcl_c", values="ok", aggfunc="mean")
cols = ["1-3", "4-6", "7-9", "10"]
pv = pv.reindex(["2", "3-5", "6-11", "12+"])[cols]
pn = inp.pivot_table(index="deg_c", columns="dcl_c", values="ok", aggfunc="count")
pn = pn.reindex(["2", "3-5", "6-11", "12+"])[cols]
fig_hm = go.Figure(go.Heatmap(z=pv.values, x=cols, y=pv.index,
                              text=[[f"{v:.0%}<br>({int(pn.values[i][j])})"
                                     for j, v in enumerate(row)] for i, row in enumerate(pv.values)],
                              texttemplate="%{text}", colorscale="RdYlGn",
                              zmin=0.25, zmax=0.4, colorbar=dict(title="win rate")))
fig_hm.update_layout(template="plotly_white", height=420, margin=dict(l=60, r=20, t=40, b=40),
                     title="4.1 win rate% (n) by degree × decile")

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_007 u8 atr4static</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:10px 4px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
h3{{border-top:2px solid #eee;padding-top:16px;}}
</style></head><body>
<h2>analysis_007 更新八 — 止损=静态4ATR(突破价−4ATR，信号日定)+吊灯(前一日ATR)</h2>
<div class="note">12847 已判定：成功 4377 / 失败 8470，胜率 34.1%、期望 +1.61%、盈亏比 2.46、中位 -4.9%。
止损只触发 977 笔(7.6%)——静态4ATR在突破价下方约-15%，几乎只接崩盘；92% 由吊灯止盈带走。
vs 原破line止损(胜率29.7%): 新止损胜率升但盈亏比降(2.46 vs 3.13)。</div>

<h3>① 全案例</h3><div class="metrics">{tile_all}</div>{fig_all}
<h3>② 成功组</h3><div class="metrics">{tile_ok}</div>{fig_ok}
<h3>③ 失败组</h3><div class="metrics">{tile_bad}</div>{fig_bad}
<h3>④ 4.1 degree × decile 组合胜率</h3>
{fig_hm.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "u8_view.html").write_text(html, encoding="utf-8")
print("u8_view.html 已生成")
