"""8 特征在肥尾(ret≥30%) vs 失败(ret≤0) 的分布对比（独立目录）。

特征：macd / roc / llt / float_market_cap / dividend_yield_ratio / pe_ttm / ma_turn20 / ma_vol20
口径：信号日 t 取值（≤t 无未来）；float_market_cap/pe_ttm 已 log；macd/roc/llt 已归一。
输出：
  fat_tail_dist.csv（两组各特征统计：n/mean/median/q25/q75/分位）
  fat_tail_view.html（每特征 overlaid 直方 + 箱线 + 组均值标注）
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
D = pd.read_parquet(HERE.parent / "detail_v4.parquet")
D["date"] = pd.to_datetime(D["date"])
FX = pd.read_parquet(HERE.parent / "stats_v4/features_v4.parquet")
FX["date"] = pd.to_datetime(FX["date"])
m = D.merge(FX[["symbol", "date", "macd", "roc", "llt", "float_market_cap",
                "dividend_yield_ratio", "pe_ttm", "ma_turn20", "ma_vol20"]],
            on=["symbol", "date"], how="left", suffixes=("", "_f"))

FEATS = ["macd", "roc", "llt", "float_market_cap", "dividend_yield_ratio",
         "pe_ttm", "ma_turn20", "ma_vol20"]
LABEL = {"macd": "MACD (DIF-DEA)/C", "roc": "ROC 20d", "llt": "LLT(60) slope/C",
         "float_market_cap": "float mcap (log)", "dividend_yield_ratio": "dividend yield",
         "pe_ttm": "PE_ttm (log)", "ma_turn20": "ma_turn20", "ma_vol20": "ma_vol20"}
COL = {"macd": "#2980b9", "roc": "#27ae60", "llt": "#e74c3c", "float_market_cap": "#8e44ad",
       "dividend_yield_ratio": "#f39c12", "pe_ttm": "#16a085", "ma_turn20": "#c0392b",
       "ma_vol20": "#7f8c8d"}

tail = m[m["ret"] >= 0.3]      # 肥尾
fail = m[m["ret"] <= 0]        # 失败
print(f"肥尾(ret≥30%) {len(tail)} | 失败(ret≤0) {len(fail)}")

rows = []
# 每特征两张独立图：肥尾一张、失败一张（不叠加）→ 16 子图按 feature 分组上下排
fig = make_subplots(rows=len(FEATS), cols=2,
                    subplot_titles=sum(([f"{LABEL[f]} — 肥尾(ret≥30%)", f"{LABEL[f]} — 失败(ret≤0)"]
                                        for f in FEATS), []),
                    vertical_spacing=0.012, horizontal_spacing=0.06)
for i, f in enumerate(FEATS):
    r = i + 1
    t, fl = tail[f].dropna(), fail[f].dropna()
    rows.append({"feature": f, "n_tail": len(t), "n_fail": len(fl),
                 "tail_mean": t.mean(), "fail_mean": fl.mean(),
                 "tail_median": t.median(), "fail_median": fl.median(),
                 "tail_q25": t.quantile(.25), "tail_q75": t.quantile(.75),
                 "fail_q25": fl.quantile(.25), "fail_q75": fl.quantile(.75)})
    fig.add_trace(go.Histogram(x=t, histnorm="probability density",
                               marker_color="rgba(231,76,60,0.6)", nbinsx=45,
                               showlegend=False), r, 1)
    fig.add_trace(go.Histogram(x=fl, histnorm="probability density",
                               marker_color="rgba(41,128,185,0.5)", nbinsx=45,
                               showlegend=False), r, 2)

stats = pd.DataFrame(rows)
stats.to_csv(HERE / "fat_tail_dist.csv", index=False, encoding="utf-8-sig")
print(stats.round(4).to_string(index=False))

fig.update_layout(template="plotly_white", height=340 * len(FEATS),
                  margin=dict(l=50, r=20, t=50, b=30), showlegend=False)
html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>fat tail vs fail dist</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
table{{border-collapse:collapse;font-size:12px;margin-top:14px;}}
th,td{{border:1px solid #d6dae1;padding:3px 8px;text-align:center;}}
th{{background:#f3f5f8;}}</style></head><body>
<h2>analysis_012 — 8 特征各自：肥尾(ret≥30%) 与 失败(ret≤0) 分布（每特征 2 独立图）</h2>
<div class="note">每特征 2 张独立图：左=肥尾({len(tail)}笔, ret≥30%)，右=失败({len(fail)}笔, ret≤0)。
特征为信号日 t 值（≤t 无未来）；float_mcap/pe 已 log。看各自形态（偏度/集中带），再对照左右两张
是否同分布。</div>
{fig.to_html(full_html=False, include_plotlyjs=False)}
<h3>统计表</h3>
<table><tr><th>feature</th><th>肥尾n</th><th>失败n</th><th>肥尾均值</th><th>失败均值</th>
<th>肥尾中位</th><th>失败中位</th><th>肥尾IQR</th><th>失败IQR</th></tr>{''.join(
 f"<tr><td>{r.feature}</td><td>{int(r.n_tail)}</td><td>{int(r.n_fail)}</td>"
 f"<td>{r.tail_mean:.3f}</td><td>{r.fail_mean:.3f}</td>"
 f"<td>{r.tail_median:.3f}</td><td>{r.fail_median:.3f}</td>"
 f"<td>{r.tail_q75-r.tail_q25:.3f}</td><td>{r.fail_q75-r.fail_q25:.3f}</td></tr>"
 for r in stats.itertuples())}</table>
</body></html>"""
(HERE / "fat_tail_view.html").write_text(html, encoding="utf-8")
print("fat_tail_view.html 已生成")
