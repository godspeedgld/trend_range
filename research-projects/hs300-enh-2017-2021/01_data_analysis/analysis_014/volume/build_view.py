"""analysis_014/volume 可视化 — RV/UDVR 十档 + 3×3 交互热力 + 分时段稳定性。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
RED, BLUE, GRAY, GOLD = "#e53e3e", "#2b6cb0", "#a0aec0", "#d69e2e"


def main():
    rv = pd.read_csv(HERE / "RV_decile.csv", index_col=0)
    ud = pd.read_csv(HERE / "UDVR_decile.csv", index_col=0)
    inter = pd.read_csv(HERE / "interaction.csv")
    per = pd.read_csv(HERE / "period_split.csv")

    fig = make_subplots(rows=2, cols=2,
                        subplot_titles=("放量比 RV=vol/ma_vol20 十档：失败率/肥尾率/均值",
                                        "涨量占比 UDVR 十档：失败率/肥尾率/均值",
                                        "交互 3×3：单笔均值%（行=UDVR 列=RV）",
                                        "分时段失败率%（RV 左半 / UDVR 右半）"),
                        horizontal_spacing=0.1, vertical_spacing=0.16)
    for j, (t, tag) in enumerate([(rv, "RV"), (ud, "UDVR")]):
        x = t.index.astype(str)
        fig.add_bar(x=x, y=t["失败率%(ret≤0)"], marker_color=[RED if v >= 68 else GRAY for v in t["失败率%(ret≤0)"]],
                    name=f"{tag} 失败率", showlegend=(j == 0), row=1, col=j + 1)
        fig.add_scatter(x=x, y=t["肥尾率%(ret≥30)"], mode="markers+lines", name=f"{tag} 肥尾率",
                        marker=dict(color=GOLD, size=8), line=dict(color=GOLD, width=1.5),
                        showlegend=(j == 0), row=1, col=j + 1, yaxis=f"y{j+1}")
        fig.add_scatter(x=x, y=t["均值%"], mode="markers+lines", name=f"{tag} 均值%",
                        marker=dict(color=BLUE, size=8), line=dict(color=BLUE, width=1.5, dash="dot"),
                        showlegend=(j == 0), row=1, col=j + 1)
    # 交互热力（均值）
    piv = inter.pivot(index="ud3", columns="rv3", values="均值%").reindex(
        index=["低UDVR", "中UDVR", "高UDVR"], columns=["低RV", "中RV", "高RV"])
    fig.add_heatmap(z=piv.values, x=piv.columns.astype(str).tolist(), y=piv.index.tolist(),
                    colorscale="RdYlGn", text=[[f"{v:+.2f}" for v in row] for row in piv.values],
                    texttemplate="%{text}", showscale=False, row=2, col=1)
    piv2 = inter.pivot(index="ud3", columns="rv3", values="失败率%(ret≤0)").reindex(
        index=["低UDVR", "中UDVR", "高UDVR"], columns=["低RV", "中RV", "高RV"])
    fig.add_heatmap(z=piv2.values, x=piv2.columns.astype(str).tolist(), y=piv2.index.tolist(),
                    colorscale="RdYlGn_r", text=[[f"{v:.1f}" for v in row] for row in piv2.values],
                    texttemplate="%{text}", showscale=False, row=2, col=1,
                    visible="legendonly", name="失败率%")
    # 分时段
    for _, r in per.iterrows():
        ys = [r[f"D{k}失败率%"] for k in range(1, 11)]
        fig.add_scatter(x=[f"D{k}" for k in range(1, 11)], y=ys, mode="lines+markers",
                        name=f"{r['时段']}·{r['特征']}", row=2, col=2)

    fig.update_layout(height=860, template="plotly_white", hovermode="x unified",
                      title=dict(text="analysis_014 · volume — 量能特征对 v4 阻力带突破的区分力（11100 笔，纯算法无闸门）",
                                 x=0.5, font=dict(size=15)),
                      legend=dict(orientation="h", y=-0.1, font=dict(size=11)))
    html = f"""<!DOCTYPE html><html><head><meta charset='utf-8'></head>
<body style='font-family:system-ui;max-width:1280px;margin:auto;background:#fff'>
{fig.to_html(full_html=False, include_plotlyjs='cdn')}
<p style='color:#555;font-size:13px'>基线：失败率 65.9% / 成功率 33.4% / 肥尾率 7.2% / 均值 +1.57% / 中位 −5.12%。
样本 = v4 活带突破（analysis_012 detail_v4，deg≥2，2017-2026，静态4ATR止损+吊灯出场，无任何 regime/形态过滤）。
<b>要点：① RV D10（突破日>3.77×均量巨量）失败率 72.9%、均值 −0.49%，跨时段稳定的最差档——"巨量突破"是反向信号；
② UDVR 极高档（>0.776）失败率 70.4%——前期涨量已主导+再突破=追高衰竭；③ 最优组合 高UDVR×低RV：均值 +4.15%、
肥尾 9.1%；最差 高UDVR×高RV（n=1750）：失败率 72.3%、均值 +0.25%——组合区分力 ~9pp 失败率 / ~4pp 均值。</b></p>
</body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 写出")


if __name__ == "__main__":
    main()
