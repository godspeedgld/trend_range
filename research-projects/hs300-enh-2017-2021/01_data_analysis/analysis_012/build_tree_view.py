"""更新一可视化：决策树四分类结果（混淆矩阵热图 + 指标条 + 按真实类的预测分布 + 树规则）。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sklearn.metrics import confusion_matrix

HERE = Path(__file__).resolve().parent
pred = pd.read_parquet(HERE / "tree_test_pred.parquet")
res = pd.read_csv(HERE / "tree_results.csv", index_col=0)

LBL = {1: "c1 <0%", 2: "c2 0-5%", 3: "c3 5-20%", 4: "c4 >20%"}
yte, yp = pred["label"].values, pred["pred_label"].values
cm = confusion_matrix(yte, yp)

fig = make_subplots(rows=2, cols=2, row_heights=[0.55, 0.45],
                    subplot_titles=("Confusion matrix (rows=actual, cols=predicted)",
                                    "Binary(>0%): precision / recall / F1 by model spec",
                                    "Predicted-class distribution by actual class",
                                    "P(label>=2) score distribution by actual binary"))
# 1) 混淆矩阵
fig.add_trace(go.Heatmap(z=cm, x=[LBL[i] for i in range(1, 5)],
                         y=[LBL[i] for i in range(1, 5)],
                         text=cm, texttemplate="%{text}",
                         colorscale="Blues", showscale=False), 1, 1)
# 2) 模型指标条
metrics = ["bin_acc", "precision", "recall", "f1", "auc"]
for i, mt in enumerate(metrics):
    fig.add_trace(go.Bar(x=res.index, y=res[mt], name=mt,
                         marker_color=["#2980b9", "#27ae60", "#f39c12", "#c0392b", "#8e44ad"][i],
                         opacity=0.85)), 1, 2
# 3) 每个真实类里预测分布
for a in range(1, 5):
    sub = pred[pred["label"] == a]
    counts = sub["pred_label"].value_counts().reindex(range(1, 5), fill_value=0)
    fig.add_trace(go.Bar(x=[LBL[i] for i in range(1, 5)], y=counts.values,
                         name=f"actual {LBL[a]}"), 2, 1)
# 4) 预测概率分布（按真实二值）
for b, nm, col in ((1, "actual <0%", "#c0392b"), (0, "actual >=0%", "#27ae60")):
    s = pred[pred["label"] >= 2] if b == 0 else pred[pred["label"] < 2]
    fig.add_trace(go.Histogram(x=s["pred_prob_ge0"], name=nm, opacity=0.6,
                               marker_color=col, nbinsx=30), 2, 2)

fig.update_layout(template="plotly_white", height=860, barmode="group",
                  margin=dict(l=50, r=20, t=60, b=40),
                  legend=dict(orientation="h", y=1.04))

tiles = "".join(
    f"<div class='item'><span>{i}</span><b>{r.bin_acc:.3f}</b>"
    f"<small>P {r.precision:.3f} / R {r.recall:.3f} / F1 {r.f1:.3f} / AUC {r.auc:.3f}</small></div>"
    for i, r in res.iterrows())

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_012 u1 — 决策树四分类</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0;}}
.metrics .item{{flex:1 1 180px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:8px 4px;}}
.metrics .item b{{display:block;font-size:16px;color:#2980b9;}}
.metrics .item span{{font-weight:bold;font-size:12px;}}
.metrics .item small{{color:#6b7480;font-size:11px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
</style></head><body>
<h2>analysis_012 更新一 — 决策树（ma_turn20 / ma_vol20 / dividend_yield）四分类</h2>
<div class="note">训练 2017-2020（4768 笔）→ 测试 2021-至今（8079 笔）。类：c1&lt;0% / c2 0-5% /
c3 5-20% / c4 ≥20%。<b>核心结论（诚实）</b>：不加权树全押 c1（四类正确率 0.686 = 基线，
c2-c4 预测全为 0）；balanced 版查全 0.785 但查准 0.315&lt;基准率；AUC≈0.49-0.50。
三个特征无逐笔分类能力（与更新八 AUC≈0.54 一致）。</div>
<div class="metrics">{tiles}</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "update1_view.html").write_text(html, encoding="utf-8")
print("update1_view.html 已生成")
