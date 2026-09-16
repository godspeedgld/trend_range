"""成功/失败分拆对比图（并入 ret_stats_view.html 底部比较）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
deg = pd.read_csv(HERE / "sf_by_degree.csv", encoding="utf-8-sig")
dci = pd.read_csv(HERE / "sf_by_decile.csv", encoding="utf-8-sig")

fig = make_subplots(rows=2, cols=2, subplot_titles=(
    "Win/Loss by degree: n (stacked) + win rate%",
    "Win/Loss by degree: mean ret% (success vs loss)",
    "Win/Loss by decile: n (stacked) + win rate%",
    "Win/Loss by decile: mean ret% (success vs loss)"))

for i, (df, xname, xlab) in enumerate([(deg, "label", "degree"),
                                       (dci, "label", "decile")], 1):
    r = 1 if i == 1 else 2
    x = df[xname].astype(str)
    fig.add_trace(go.Bar(x=x, y=df["n_ok"], name=f"{xlab} 成功数",
                         marker_color="#e74c3c", opacity=0.85), row=r, col=1)
    fig.add_trace(go.Bar(x=x, y=df["n_bad"], name=f"{xlab} 失败数",
                         marker_color="#95a5a6", opacity=0.6), row=r, col=1)
    fig.add_trace(go.Scatter(x=x, y=df["ok_share_of_grp"] * 100, name=f"{xlab} 胜率%",
                             mode="lines+markers", yaxis="y2"), row=r, col=1)
    fig.add_trace(go.Bar(x=x, y=df["ok_mean"], name=f"{xlab} 成功均收%",
                         marker_color="#c0392b"), row=r, col=2)
    fig.add_trace(go.Bar(x=x, y=df["bad_mean"], name=f"{xlab} 失败均收%",
                         marker_color="#27ae60"), row=r, col=2)
    fig.add_trace(go.Scatter(x=x, y=df["grp_mean"], name=f"{xlab} 整档期望%",
                             mode="lines+markers", line=dict(color="#f39c12", width=2)),
                  row=r, col=2)
    # 次级轴（胜率%）
    fig.update_yaxes(overlaying="y", side="right", showgrid=False, title="win rate%",
                     row=r, col=1)

fig.update_layout(template="plotly_white", height=760, barmode="stack",
                  margin=dict(l=50, r=55, t=60, b=30),
                  legend=dict(orientation="h", y=1.04))
fig.write_html(str(HERE / "sf_view.html"))
print("sf_view.html 已生成")

# 并入主页面 ret_stats_view.html（在 </body> 前插 sf 面板）
main = (HERE / "ret_stats_view.html").read_text(encoding="utf-8")
sf_fig = fig.to_html(full_html=False, include_plotlyjs=False, div_id="fig_sf")
note = ("<h3 style='margin-top:26px'>成功/失败分拆（成功=ret&gt;0；失败=ret≤0）——"
        "数量+胜率 / 成功均收 vs 失败均收 vs 整档期望</h3>"
        "<div class='note'>失败均收 ≈ -6~-7.6%（止损带）；成功均收随 degree/decile 变化是"
        "右尾量级的关键；整档期望=成败加权，才是该档策略价值。</div>")
main = main.replace("</body></html>", sf_fig + "</body></html>")
main = main.replace("<h2>analysis_007 更新六", "<h2>analysis_007 更新六+七")
main = main.replace("</div>\n</body>", "</div>" + note + "</body>") if "</div>\n</body>" in main else main
(HERE / "ret_stats_view.html").write_text(main, encoding="utf-8")
print("已并入 ret_stats_view.html")
