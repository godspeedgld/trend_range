"""decile_scan 可视化：8 特征 10 档 失败率+肥尾率 双线 + 档期望。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
scan = pd.read_csv(HERE / "decile_scan.csv", encoding="utf-8-sig")
FEATS = ["macd", "roc", "llt", "float_market_cap", "dividend_yield_ratio",
         "pe_ttm", "ma_turn20", "ma_vol20"]

fig = make_subplots(rows=8, cols=1, vertical_spacing=0.02,
                    subplot_titles=[f for f in FEATS])
for i, f in enumerate(FEATS):
    s = scan[scan["feature"] == f].sort_values("decile")
    fig.add_trace(go.Scatter(x=s["decile"], y=s["fail_rate"]*100, name="fail rate %",
                             mode="lines+markers", line=dict(color="#2980b9", width=2)),
                  i + 1, 1)
    fig.add_trace(go.Scatter(x=s["decile"], y=s["tail_rate"]*100, name="tail rate %(≥30%)",
                             mode="lines+markers", line=dict(color="#c0392b", width=2)),
                  i + 1, 1)
    fig.add_trace(go.Scatter(x=s["decile"], y=s["exp_ret"], name="expect ret %",
                             mode="lines+markers", line=dict(color="#27ae60", width=1.6, dash="dot")),
                  i + 1, 1)
    # 基线标注
    fig.add_hline(y=66.4, line=dict(color="#2980b9", width=0.8, dash="dot"), row=i+1, col=1)

fig.update_layout(template="plotly_white", height=360 * 8, hovermode="x unified",
                  margin=dict(l=60, r=60, t=60, b=30),
                  legend=dict(orientation="h", y=1.0))
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>decile scan</title><script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.note{{color:#6b7480;font-size:13px;margin:8px 0 16px;}}</style></head><body>
<h2>analysis_012 — 8 特征 × 10 档：失败率 vs 肥尾率扫描</h2>
<div class="note">蓝=fail rate(基线66.4%点线) 红=tail rate(≥30%,基线7.2%) 绿虚线=档期望%。
<b>读法</b>：找"蓝线低(失败少)+红线不低(肥尾保留)"的档。最佳：
ma_vol20 档1(低量: 58%/10%/+6.5%)、float_mcap 档1(小市值: 62%/11%/+6.7%)、llt 档9-10(高动量: 肥尾12%)。</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
</body></html>"""
(HERE / "decile_scan_view.html").write_text(html, encoding="utf-8")
print("decile_scan_view.html 已生成")
