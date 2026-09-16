"""decile_split 可视化：success/fail × 5 特征 × 10 档 mean/median 曲线 + 汇总表。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
spl = pd.read_csv(HERE / "decile_split.csv", encoding="utf-8-sig")
FEAT_LABEL = {"degree": "degree", "price_decile": "price decile (past 1y)",
              "ma_turn20": "ma_turn20", "div_yield": "dividend yield",
              "ma_vol10": "ma_vol10"}

TITLES = ["degree", "price decile (1y)", "ma_turn20", "dividend yield", "ma_vol10", ""]
fig = make_subplots(rows=3, cols=2, row_heights=[0.4, 0.4, 0.2], subplot_titles=TITLES)
cell_r, cell_c = 1, 1
for f in ["degree", "price_decile", "ma_turn20", "div_yield", "ma_vol10"]:
    for g, nm, col in [("success", "success", "#c0392b"), ("fail", "fail", "#2980b9")]:
        s = spl[(spl["feature"] == f) & (spl["group"] == g)].sort_values("decile")
        fig.add_trace(go.Scatter(x=s["decile"], y=s["mean"], name=f"{nm} mean",
                                 mode="lines+markers", line=dict(color=col, width=1.8),
                                 showlegend=(cell_r == 1 and cell_c == 1)),
                      row=cell_r, col=cell_c)
    cell_c += 1
    if cell_c > 2:
        cell_c = 1
        cell_r += 1

# 表格
def rows_html(f):
    s = spl[spl["feature"] == f]
    tr = ""
    for g in ["success", "fail"]:
        for r in s[s["group"] == g].sort_values("decile").itertuples():
            tr += (f"<tr><td>{g}</td><td>{r.decile}</td><td>{int(r.n)}</td>"
                   f"<td>{r.mean:.2f}</td><td>{r.median:.2f}</td>"
                   f"<td>{r.max:.2f}</td><td>{r.min:.2f}</td></tr>")
    return (f"<h4>{FEAT_LABEL[f]}</h4><table><tr><th>组</th><th>十分位</th><th>n</th>"
            f"<th>均值%</th><th>中位%</th><th>max%</th><th>min%</th></tr>{tr}</table>")

tables = "".join(rows_html(f) for f in ["degree", "price_decile", "ma_turn20", "div_yield", "ma_vol10"])
fig.update_layout(template="plotly_white", height=880, hovermode="closest",
                  margin=dict(l=50, r=20, t=80, b=30), legend=dict(orientation="h", y=1.04))

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v4 decile split</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
table{{border-collapse:collapse;font-size:12px;margin:6px 0 16px;}}
th,td{{border:1px solid #d6dae1;padding:3px 8px;text-align:center;}}
th{{background:#f3f5f8;}}
h3{{margin-top:22px;}}
</style></head><body>
<h2>analysis_012 — v4 交易 成功/失败 × 特征十分位分桶统计</h2>
<div style="color:#6b7480;font-size:13px">成功=ret&gt;0、失败=ret≤0。特征十分位=各组内等频 rank
（price_decile 用原始 1-10 档）。指标：均值/中位/max/min。</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
<h3>明细表</h3>{tables}
</body></html>"""
(HERE / "split_view.html").write_text(html, encoding="utf-8")
print("split_view.html 已生成")
