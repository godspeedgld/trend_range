"""中际旭创/宁德时代/贵州茅台/中国平安 v4 生命周期测试 + 可视化（规则同中芯/蛇口）。"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.graph_objects as go

HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[2] / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo_v3 import run_band_breakout
from plateau_algo_v4 import run_band_breakout_v4

WAREHOUSE = Path(r"C:\Quant\trend_range\data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")
STOCKS = {"300308.SZ": "zjjc", "300750.SZ": "ndsd", "600519.SH": "gzmt", "601318.SH": "zgpa"}
NAMES = {"300308.SZ": "中际旭创", "300750.SZ": "宁德时代", "600519.SH": "贵州茅台",
         "601318.SH": "中国平安"}


def load_daily(inst: str) -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute("SELECT date, open, high, low, close FROM stock_bar1d "
                     f"WHERE instrument='{inst}' ORDER BY date").fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna().reset_index(drop=True)


def main():
    all_html = []
    for inst, tag in STOCKS.items():
        g = load_daily(inst)
        ev4, bands4, _ = run_band_breakout_v4(g)
        ev3, bands3, _ = run_band_breakout(g)
        b4 = pd.DataFrame([{**{k: v for k, v in b.items() if k != "dead_i"},
                            "dead": b["dead"], "dead_date": b["d_dead"],
                            "d_last": b["d_last"]} for b in bands4])
        b4.to_csv(HERE / f"{tag}_v4_bands.csv", index=False, encoding="utf-8-sig")
        e4 = pd.DataFrame(ev4)
        if len(e4):
            e4["date"] = pd.to_datetime(e4["date"])
            e4.to_csv(HERE / f"{tag}_v4_events.csv", index=False, encoding="utf-8-sig")
        g.to_csv(HERE / f"{tag}_daily.csv", index=False)

        nR_alive = int(((b4["kind"] == "R") & (~b4["dead"])).sum())
        n_deadR = int(((b4["kind"] == "R") & b4["dead"]).sum())
        print(f"{NAMES[inst]} {inst}: bars={len(g)} v3事件={len(ev3)} v4事件={len(ev4)} | "
              f"活阻力带 {nR_alive} 死阻力 {n_deadR}")

        # 可视化：只显示阻力带；活=红实线到末日、死=灰点线到死亡日
        last_date = g["date"].iloc[-1]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=g["date"], y=g["close"], name="close",
                                 line=dict(color="#2c3e50", width=1.0)))
        for _, b in b4.iterrows():
            if b["kind"] != "R":
                continue
            x0 = pd.Timestamp(b["d0"])
            if b["dead"]:
                x1, col, dash = pd.Timestamp(b["dead_date"]), "#95a5a6", "dot"
            else:
                x1, col, dash = last_date, "#c0392b", "solid"
            fig.add_trace(go.Scatter(
                x=[x0, x1], y=[b["line"], b["line"]], mode="lines",
                line=dict(color=col, width=2.5, dash=dash),
                hovertemplate=(f"line={b['line']:.2f} pts={b['count']}<br>"
                               f"{x0.date()} → {x1.date()}"),
                showlegend=False))
        fig.update_layout(template="plotly_white", height=540,
                          title=f"{NAMES[inst]} {inst} — v4 resistance bands "
                                "(red alive→today, grey dead→death date)",
                          margin=dict(l=50, r=20, t=55, b=30))
        all_html.append(fig.to_html(full_html=False, include_plotlyjs=False,
                                    div_id=f"fig_{tag}"))

    html = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<title>v4 more stocks</title>'
            '<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script></head><body>'
            '<h2>analysis_012 — v4 阻力带生命周期（旭创/宁德/茅台/平安）</h2>'
            '<div style="color:#6b7480;font-size:13px">规则：阻力带死 = 累计90日 close&gt;line×1.10 '
            '或 单日 close&gt;line×1.30。红实线=活阻力（画到数据末日）；灰点线=死阻力（截止死亡日）；'
            '黑线=收盘价。</div>' + "".join(all_html) + '</body></html>')
    (HERE / "v4_more_view.html").write_text(html, encoding="utf-8")
    print("v4_more_view.html 已生成")


if __name__ == "__main__":
    main()
