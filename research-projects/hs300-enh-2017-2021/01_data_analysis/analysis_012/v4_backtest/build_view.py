"""v4 回测统计可视化：v4 vs v3 对照 —— 总体瓦片 + ret 5%桶 + degree/decile 分布 + 离场构成。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]

v4 = pd.read_parquet(HERE / "detail_v4.parquet")
v4["date"] = pd.to_datetime(v4["date"])
v4["ret_pct"] = v4["ret"] * 100
v3 = pd.read_parquet(PROJ / "01_data_analysis/analysis_007/atr4_static/detail_atr4static.parquet")
v3["date"] = pd.to_datetime(v3["date"])
v3["ret_pct"] = v3["ret"] * 100
for d in (v4, v3):
    d["ok"] = d["ret_pct"] > 0


def panel(det, tag, color):
    dec = det[det["result"].isin(["success", "fail"])].copy()
    n_s = int((dec.ok).sum()); n_f = int((~dec.ok).sum())
    w, l = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
    payoff = w.mean() / abs(l.mean())
    # ret 5% 桶
    edges = list(range(-50, 56, 5))
    labels = [f"<{edges[0]}"] + [f"[{edges[i]},{edges[i+1]})" for i in range(len(edges)-1)] + [f">={edges[-1]}"]
    dec2 = dec.copy()
    dec2["bucket"] = pd.cut(dec2["ret_pct"], bins=[-np.inf]+edges+[np.inf], labels=labels, right=False)
    bucket = dec2.groupby("bucket", observed=False)["ret_pct"].agg(n="count").reset_index()
    # degree 箱线（分桶 2..11 + 12+）
    dec2["gdeg"] = dec2["degree"].apply(lambda x: x if x <= 11 else 99)
    dec2["gdeg_lab"] = dec2["gdeg"].map({**{i: str(i) for i in range(2, 12)}, 99: "12+"})
    tiles = (f"<div class='item'><span>样本</span><b>{len(dec)}</b></div>"
             f"<div class='item'><span>胜率</span><b>{n_s/len(dec)*100:.1f}%</b></div>"
             f"<div class='item'><span>期望</span><b>{dec['ret_pct'].mean():+.2f}%</b></div>"
             f"<div class='item'><span>盈亏比</span><b>{payoff:.2f}</b></div>"
             f"<div class='item'><span>中位</span><b>{dec['ret_pct'].median():+.2f}%</b></div>")
    fig = make_subplots(rows=1, cols=3, subplot_titles=(
        f"{tag} ret 5% bucket", f"{tag} by degree box+mean", f"{tag} exit reason"))
    fig.add_trace(go.Bar(x=bucket["bucket"].astype(str), y=bucket["n"], marker_color=color), 1, 1)
    for lab in ["2","3","4","5","6","7","8","9","10","11","12+"]:
        y = dec2[dec2["gdeg_lab"]==lab]["ret_pct"]
        if len(y):
            fig.add_trace(go.Box(y=y, name=lab, boxpoints=False, line=dict(width=1),
                                 marker_color="#7f8c8d"), 1, 2)
    reason = dec["reason"].value_counts()
    fig.add_trace(go.Bar(x=reason.index, y=reason.values, marker_color=color, opacity=0.8), 1, 3)
    fig.update_layout(template="plotly_white", height=420, boxmode="overlay",
                      margin=dict(l=40, r=20, t=55, b=30),
                      legend=dict(orientation="h", y=1.1), showlegend=False)
    return tiles, fig.to_html(full_html=False, include_plotlyjs=False)


t4, f4 = panel(v4, "v4 (live bands)", "#c0392b")
t3, f3 = panel(v3, "v3 (all bands)", "#2980b9")

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v4 backtest stats</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:8px 4px;}}
.metrics .item b{{display:block;font-size:17px;margin-top:4px;color:#2980b9;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
h3{{border-top:2px solid #eee;padding-top:14px;}}
</style></head><body>
<h2>analysis_012 更新三 — v4 活带信号回测统计（同更新八规则）</h2>
<div style="color:#6b7480;font-size:13px">v3=全带突破(12,847笔) vs v4=仅活阻力带突破(11,026笔)。
生命周期滤掉 1,877 死带信号(14%)，期望 1.61→1.57、胜率 34.1→33.6、盈亏比 2.46→2.49——基本中性。</div>
<h3>① v4（活带信号）</h3><div class="metrics">{t4}</div>{f4}
<h3>② v3（全带信号，更新八原）</h3><div class="metrics">{t3}</div>{f3}
</body></html>"""
(HERE / "v4_stats_view.html").write_text(html, encoding="utf-8")
print("v4_stats_view.html 已生成")
