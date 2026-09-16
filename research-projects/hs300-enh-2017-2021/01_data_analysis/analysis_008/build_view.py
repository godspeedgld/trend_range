"""analysis_008 — result_view.html 生成（4 版本净值对比 + 各闸门剔除交易年度分布）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analysis import A_V2_TRADES, build_gates, HERE as _H   # noqa: E402

VERSIONS = [("A_v2 无闸门", A_V2_TRADES.parent / "nav_from_trades.csv"),
            ("闸门 MA200", _H / "gates_ma200/nav_from_trades.csv"),
            ("闸门 LLT60", _H / "gates_llt60/nav_from_trades.csv"),
            ("闸门 ROC市值加权", _H / "gates_roc/nav_from_trades.csv"),
            ("闸门 RSI市值加权", _H / "gates_rsi/nav_from_trades.csv")]
COLORS = {"A_v2 无闸门": "#95a5a6", "闸门 MA200": "#2980b9",
          "闸门 LLT60": "#f39c12", "闸门 ROC市值加权": "#27ae60",
          "闸门 RSI市值加权": "#c0392b"}


def dropped_yearly(trades, gate):
    cal = pd.DatetimeIndex(gate.index)
    pos = {d: i for i, d in enumerate(cal)}
    keep = []
    for e in pd.to_datetime(trades["entry_date"]):
        i = pos.get(e)
        sd = cal[i - 1] if i and i > 0 else pd.NaT
        keep.append(bool(gate.get(sd)) if pd.notna(sd) else False)
    dropped = trades[~pd.Series(keep, index=trades.index).values].copy()
    dropped["y"] = pd.to_datetime(dropped["entry_date"]).dt.year
    return dropped.groupby("y")["return_pct"].sum()


def main():
    fig = make_subplots(rows=2, cols=1, row_heights=[0.62, 0.38], shared_xaxes=False,
                        vertical_spacing=0.08,
                        subplot_titles=("NAV (trades 口径, 固定名义 10 万/仓, 15bps 双边)",
                                        "各闸门【剔除】交易的年度收益合计 pp（负=砍对了, 正=误杀）"))
    for name, p in VERSIONS:
        nav = pd.read_csv(p)
        nav["date"] = pd.to_datetime(nav["date"])
        fig.add_trace(go.Scatter(x=nav["date"], y=nav["nav"], name=name,
                                 line=dict(color=COLORS[name], width=1.6 if "MA200" in name else 1.2)), row=1, col=1)

    trades = pd.read_csv(A_V2_TRADES, encoding="utf-8-sig")
    gates = build_gates()
    yearly = pd.DataFrame({
        "MA200": dropped_yearly(trades, gates["MA200"]),
        "LLT60": dropped_yearly(trades, gates["LLT60"]),
        "ROC市值加权": dropped_yearly(trades, gates["ROC_市值加权"]),
        "RSI市值加权": dropped_yearly(trades, gates["RSI上下限_市值加权"]),
    }).fillna(0)
    for col, color in (("MA200", "#2980b9"), ("LLT60", "#f39c12"),
                       ("ROC市值加权", "#27ae60"), ("RSI市值加权", "#c0392b")):
        fig.add_trace(go.Bar(x=yearly.index, y=yearly[col], name=f"剔除-{col}",
                             marker_color=color, opacity=0.75), row=2, col=1)

    cmp = pd.read_csv(HERE / "gate_comparison.csv", encoding="utf-8-sig", index_col=0)
    tiles = "".join(
        f"<div class='item'><span>{i}</span><b>{r.total_return*100:+.1f}%</b>"
        f"<small>Sharpe {r.sharpe:.2f} / maxDD {r.max_drawdown*100:.1f}% / {int(r.n_trades)} 笔"
        f" / 胜率 {r.win_rate_pct:.1f}%</small></div>"
        for i, r in cmp.iterrows())

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_008 — 牛熊闸门对照 (MA200 / LLT60 / 扩散指标)</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 220px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:10px 6px;}}
.metrics .item b{{display:block;font-size:20px;margin:4px 0;color:#2980b9;}}
.metrics .item span{{font-weight:bold;}}
.metrics .item small{{color:#6b7480;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
</style></head><body>
<h2>analysis_008 — 扩散指标牛熊闸门 vs MA200 闸门（简化回测）</h2>
<div class="note">简化口径：A_v2（无闸门基线）交易中，信号日闸门为空头则剔除（不开仓），存量仓不变；
指标全部由 trades 经 metrics_from_trades.py 同尺子推算（指标铁律）。
局限：静态筛选不重排坑位；闸门按信号日单点判定。</div>
<div class="metrics">{tiles}</div>
{fig.to_html(full_html=False, include_plotlyjs=False, div_id='fig')}
</body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("result_view.html 已生成")
    print(yearly.round(1).to_string())


if __name__ == "__main__":
    main()
