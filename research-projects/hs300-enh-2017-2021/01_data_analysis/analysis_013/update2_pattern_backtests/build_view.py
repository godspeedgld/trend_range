"""更新二汇总视图 — summary_view.html：统一统计表（含沪深300 基准行）+ 统一净值曲线图。

曲线图：12 个回测 + 沪深300 买入持有（黑色粗线，非超额，用户指定）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
PALETTE = ["#2b6cb0", "#e53e3e", "#2f855a", "#d69e2e", "#805ad5", "#dd6b20",
           "#319795", "#b83280", "#4a5568", "#38b2ac", "#c53030", "#718096"]


def bench_stats(idx: pd.DataFrame):
    r = idx["close"].pct_change().fillna(0)
    nav = (1 + r).cumprod()
    total = nav.iloc[-1] - 1
    ann = nav.iloc[-1] ** (252 / len(r)) - 1
    sharpe = r.mean() / r.std() * np.sqrt(252)
    dd = (nav / nav.cummax() - 1).min()
    return {"总收益%": round(total * 100, 1), "年化%": round(ann * 100, 2),
            "Sharpe": round(sharpe, 2), "maxDD%": round(dd * 100, 1)}, nav


def main():
    tb = pd.read_csv(HERE / "summary_table.csv")
    tb = tb.rename(columns={"total_return_pct": "总收益%", "annual_pct": "年化%",
                            "maxDD_pct": "maxDD%", "win_rate_pct": "胜率%",
                            "n_trades": "笔数", "payoff": "盈亏比",
                            "sharpe": "Sharpe",
                            "avg_ret_pct": "单笔均%", "avg_hold_days": "均持仓日"})
    idx = pd.read_parquet(HERE / "hs300_index.parquet").set_index("date")
    bs, bnav = bench_stats(idx)
    bench_row = {"run_id": "benchmark", "形态": "沪深300买入持有", "笔数": 1,
                 "胜率%": np.nan, "盈亏比": np.nan, "单笔均%": np.nan,
                 "均持仓日": np.nan, **bs}

    show_cols = ["形态", "笔数", "总收益%", "年化%", "Sharpe", "maxDD%",
                 "胜率%", "盈亏比", "单笔均%", "均持仓日"]
    html_tb = pd.concat([tb[show_cols], pd.DataFrame([bench_row])[show_cols]], ignore_index=True)\
        .to_html(index=False, border=0, classes="tbl", na_rep="—",
                 float_format=lambda x: f"{x:g}")

    fig = go.Figure()
    for i, row in tb.iterrows():
        nav = pd.read_csv(HERE / "runs" / row["run_id"] / "nav.csv", parse_dates=["date"])
        fig.add_trace(go.Scatter(x=nav["date"], y=nav["nav"], name=f"{row['形态']}({row['笔数']}笔)",
                                 line=dict(color=PALETTE[i % len(PALETTE)], width=1.3)))
    fig.add_trace(go.Scatter(x=bnav.index, y=bnav, name="沪深300 买入持有",
                             line=dict(color="#1a202c", width=3)))
    fig.update_layout(height=640, template="plotly_white",
                      title="analysis_013 更新二 · 11 形态/通道独立回测净值（沪深300 因果口径，2015 至今）",
                      hovermode="x unified", legend=dict(orientation="h", y=-0.15),
                      yaxis_title="净值（起点=1）")
    g = fig.to_html(full_html=False, include_plotlyjs="cdn")

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>analysis_013 更新二</title>
<style>body{{font-family:system-ui;max-width:1280px;margin:auto;background:#fff}}
.tbl{{border-collapse:collapse;font-size:13px;margin:16px 0}}
.tbl th,.tbl td{{padding:5px 14px;text-align:right;border-bottom:1px solid #e2e8f0}}
.tbl th:first-child,.tbl td:first-child{{text-align:left}}
h2{{text-align:center}}p.note{{color:#555;font-size:13px}}</style></head><body>
<h2>analysis_013 更新二 · 形态/通道独立回测汇总</h2>
<p class="note">画法=quantreg_sr 因果口径（变体B 同款，一致性已验证）；开仓=空仓且收盘&gt;当日压力线（形态过滤）→次日开盘；
止损=entry−3×ATR14(信号日)；止盈=入场后最高−3×ATR14(当日)（盘中 low 触发，跳空按开盘）；满仓，单边 10bps。</p>
{html_tb}
{g}
</body></html>"""
    (HERE / "summary_view.html").write_text(html, encoding="utf-8")
    print("summary_view.html 写出:", HERE / "summary_view.html")
    print("\n基准（沪深300 买入持有）:", bs)


if __name__ == "__main__":
    main()
