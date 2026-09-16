"""MA200 偏离度 10 档 可视化：失败率/肥尾率/期望 双轴。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
res = pd.read_csv(HERE / "ma200_dev_decile.csv", encoding="utf-8-sig")
res["mid"] = (res["dev_min"] + res["dev_max"]) / 2

fig = go.Figure()
fig.add_trace(go.Bar(x=res["decile"], y=res["fail_rate"]*100, name="fail rate %",
                     marker_color="rgba(41,128,185,0.75)", yaxis="y"))
fig.add_trace(go.Scatter(x=res["decile"], y=res["tail_rate"]*100, name="tail rate %(≥30%)",
                         mode="lines+markers", line=dict(color="#c0392b", width=2.5),
                         marker=dict(size=9), yaxis="y2"))
fig.add_trace(go.Scatter(x=res["decile"], y=res["exp_ret"], name="expect ret %",
                         mode="lines+markers", line=dict(color="#27ae60", width=2, dash="dot"),
                         yaxis="y2"))
# 基线
fig.add_hline(y=66.3, line=dict(color="#2980b9", width=0.8, dash="dot"))
fig.add_hline(y=7.2, line=dict(color="#c0392b", width=0.8, dash="dot"), yref="y2")
# 甜点区标注 D4-D5
fig.add_vrect(x0=3.5, x1=5.5, fillcolor="rgba(243,156,18,0.15)", line_width=0)

fig.update_layout(template="plotly_white", height=520,
                  title="(close-MA200)/MA200 decile → fail/tail rate（甜点 D4-D5：指数刚站上年线 +1~+5%）",
                  xaxis_title="偏离度 decile（D1 深线下 → D10 高位追）",
                  yaxis=dict(title="fail rate %", range=[40, 90]),
                  yaxis2=dict(title="tail rate % / expect %", overlaying="y", side="right"),
                  hovermode="x unified", margin=dict(l=50, r=60, t=70, b=50),
                  legend=dict(orientation="h", y=1.08))

html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>ma200 dev decile</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 12px;}}</style></head><body>
<h2>analysis_012 — 指数偏离 (close-MA200)/MA200 十分位 × 失败率/肥尾率</h2>
<div class="note">蓝柱=失败率(基线66.3%点线) 红线=肥尾率(基线7.2%) 绿点线=期望%。
橙色底=D4-D5 甜点区(偏离+0.7~+5.1%)：失败率 54-59%↓、肥尾率 11-12%↑、期望+6.7~+8.0%。
两时段甜点略移：2017-20 在 D4(+1~3%, 失败37.4%)、2021-26 在 D5(+3~5%)——核心都是"指数刚破年线小幅偏离"。
D1-D2 深线下、D10 高位(>+17%) 失败率最高(70-81%)。</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "ma200_dev_view.html").write_text(html, encoding="utf-8")
print("ma200_dev_view.html 已生成")
