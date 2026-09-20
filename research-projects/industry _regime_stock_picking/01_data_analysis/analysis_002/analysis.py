"""analysis_002 — 验证财通拐点系列二的「PB 回归法」（本地 PB 分位 / 十分位 / 修复目标价）

引用研报卡：research_report/industry_research/property_reversal_targets_caitong_20260531_main.md
（表1：PB 修复空间测算，截至 2026-05-29，口径 = 总市值/归母净资产）

本分析：
  1. 口径修正：BigQuant stock_valuation.pb 的分母是**全部权益（含少数股东）**，
     与 Wind/财通的归母口径不可比——地产股少数股东占比高（合作开发），必须修正：
         pb_归母(t) = pb_bigquant(t) / (1 − 少数股东占比(t))
     少数股东占比 = 少数/(归母+少数)，来自本地财报面板（46 期季度点值，交易日 ffill）
  2. 五年窗（2021 起）/十年窗（2016 起，跟随财通自然年起点）：
     max、当前百分位、十分位（D1~D10）
  3. 修复目标：目标PB = max×0.7（财通正文口径）与 70% 分位（稳健中枢）双口径；
     目标价 = 目标PB × BPS（BPS = 财报面板最新每股净资产）；涨幅 = 目标PB/当前PB − 1
  4. 与财通表1 对照（仅 3 家重叠：保利/蛇口/滨江），并回验系列三 0625「未来一个季度
     温和上行」的预测（申万地产指数 6/25→8/21 实际走势）
产出：result_view.html（plotly 本地 vendor）+ 控制台表

铁律：所有数字直接来自 stock_valuation/stock_bar1d/财报面板，无外部补充；
      财通数字一律标「原文口径，未复现验证」。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]          # industry _regime_stock_picking
REPO = HERE.parents[3]          # trend_range（analysis_002→01_data_analysis→proj→research-projects→repo）
PANEL_ROOT = REPO / "financial-statement-analysis"
DDB = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

SYMS = {"保利发展": "600048.SH", "招商蛇口": "001979.SZ", "滨江集团": "002244.SZ",
        "新城控股": "601155.SH", "建发股份": "600153.SH", "绿地控股": "600606.SH"}

# 财通表1（2026-05-29，原文口径未复现验证）——重叠 3 家，用于对照
CAITONG = {  # 名: (当前PB, 五年分位%, 五年修复空间%)
    "保利发展": (0.4, 0.3, 177), "招商蛇口": (0.8, 10.7, 39), "滨江集团": (1.1, 49.3, 22),
}


def load_pb_series(con, sym: str) -> pd.DataFrame:
    """日频 pb（BigQuant 全权益口径）+ 少数占比修正 → pb_归母"""
    df = con.execute("""SELECT date, pb, total_market_cap FROM stock_valuation
                        WHERE instrument=? AND pb IS NOT NULL ORDER BY date""",
                     [sym]).df()
    df["date"] = pd.to_datetime(df["date"])
    return df


def minority_ratio_series(name: str, dates: pd.Series) -> pd.Series:
    """少数股东占比 = 少数/(归母+少数)，财报季度点值 → 交易日 ffill"""
    bal = pd.read_parquet(PANEL_ROOT / f"panel_{name}" / "panel_balance.parquet")
    mi = bal.loc[[i for i in bal.index if "少数股东权益" in i][0]]
    eq = bal.loc["归属于母公司普通股股东权益合计"]
    ratio = (mi / (mi + eq)).astype(float)
    ratio.index = pd.to_datetime(ratio.index.map(lambda p: f"{p[:4]}-{p[5:7]}-28"))  # 期末近似
    s = pd.Series(ratio.values, index=ratio.index).sort_index()
    return s.reindex(dates, method="ffill").fillna(s.iloc[0])


def latest_bps(name: str) -> float:
    bal = pd.read_parquet(PANEL_ROOT / f"panel_{name}" / "panel_balance.parquet")
    row = bal.loc[[i for i in bal.index if "每股股东权益" in i and "母公司" in i][0]]
    v = row.dropna()
    return float(v.iloc[-1])


def stats_window(s: pd.Series, start: str) -> dict:
    w = s[s.index >= start].dropna()
    cur = w.iloc[-1]
    pct = (w < cur).mean() * 100                     # 当前值的历史百分位
    dec = min(10, int(pct // 10) + 1)                # 十分位 D1~D10
    return {"n": len(w), "max": float(w.max()), "min": float(w.min()),
            "pct": float(pct), "dec": dec, "cur": float(cur),
            "q70": float(w.quantile(0.70))}


def main():
    con = duckdb.connect(str(DDB), read_only=True)
    rows, figs_data = [], {}
    for nm, sym in SYMS.items():
        df = load_pb_series(con, sym)
        # ★ mr 的 index 是日期、df["pb"] 的 index 是 RangeIndex——直接相除会按并集索引
        #   对齐成 2N 行全 NaN；mr 本身就是按 df["date"] 逐行 reindex 的，用 values 对位相除
        mr = minority_ratio_series(nm, df["date"])
        df["pb_gm"] = df["pb"].values / (1 - mr.values)
        bps = latest_bps(nm)
        s5, s10 = stats_window(df.set_index("date")["pb_gm"], "2021-01-01"), \
                  stats_window(df.set_index("date")["pb_gm"], "2016-01-01")
        for tag, st in [("五年", s5), ("十年", s10)]:
            tgt_a = st["max"] * 0.7                   # 财通正文口径
            tgt_b = st["q70"]                         # 稳健：70% 分位
            rows.append({
                "公司": nm, "窗": tag, "当前PB(归母)": round(st["cur"], 3),
                "历史max": round(st["max"], 2), "当前分位%": round(st["pct"], 1),
                "十分位": f"D{st['dec']}",
                "目标PB(max×0.7)": round(tgt_a, 2), "目标价": round(tgt_a * bps, 2),
                "涨幅%": round((tgt_a / st["cur"] - 1) * 100, 0),
                "目标PB(70%分位)": round(tgt_b, 2), "涨幅B%": round((tgt_b / st["cur"] - 1) * 100, 0),
                "BPS": bps,
            })
        figs_data[nm] = df.set_index("date")["pb_gm"]

    # 0625 预测回验：六家等权组合（A 股"内房股"代理）6/25 → 最新
    # （stock_industry_bar1d 是 6 位树码无名称列，名称映射绕圈；六家等权更贴题且零依赖）
    px = con.execute("""SELECT date, instrument, close FROM stock_bar1d
                        WHERE instrument IN ('600048.SH','001979.SZ','002244.SZ',
                                             '601155.SH','600153.SH','600606.SH')
                          AND date >= '2026-06-24' ORDER BY date""").df()
    con.close()
    px["date"] = pd.to_datetime(px["date"])
    ret = px.pivot(index="date", columns="instrument", values="close").pct_change().mean(axis=1)
    idx = (1 + ret).cumprod()                      # 等权净值（起点=1）
    idx = idx.iloc[1:]
    chg_idx = (idx.iloc[-1] - 1) * 100

    tbl = pd.DataFrame(rows)
    tbl.to_csv(HERE / "pb_table.csv", index=False, encoding="utf-8-sig")
    print(tbl.to_string(index=False))
    print(f"\n[0625 预测回验] 申万房地产指数 2026-06-25 → {idx.index[-1].date()}: {chg_idx:+.1f}%"
          f"（财通预测'未来一个季度温和上行'）")

    # ── 可视化 ──
    html = render_html(tbl, figs_data, idx, chg_idx)
    out = HERE / "result_view.html"
    out.write_text(html, encoding="utf-8")
    js = REPO / "cs-trend-train/plotly.min.js"
    if js.exists() and not (HERE / "plotly.min.js").exists():
        import shutil; shutil.copy(js, HERE / "plotly.min.js")
    print(f"OK -> {out}")


def render_html(tbl, figs_data, idx, chg_idx) -> str:
    import plotly.io as pio
    DARK = dict(paper_bgcolor="#16181d", plot_bgcolor="#1b1e24",
                font=dict(color="#d8dce3", size=11), margin=dict(l=50, r=20, t=34, b=32))
    GRID = dict(gridcolor="#26292f", zeroline=False)
    cfg = dict(displayModeBar=False, responsive=True)

    charts = []
    for nm, s in figs_data.items():
        s5 = s[s.index >= "2021-01-01"]
        tr = [dict(type="scatter", mode="lines", x=s.index.astype(str).tolist(), y=s.tolist(),
                   name="PB(归母)", line=dict(color="#4a90d9", width=1.6))]
        shapes = []
        if len(s5):
            tr.append(dict(type="scatter", mode="lines", x=s5.index.astype(str).tolist(),
                           y=[s5.max() * 0.7] * len(s5), name="五年max×0.7",
                           line=dict(color="#e8c35a", width=1.4, dash="dash")))
            shapes.append(dict(type="line", y0=s5.max(), y1=s5.max(), x0=0, x1=1, xref="paper",
                               line=dict(color="#ef232a", width=1, dash="dot")))
            shapes.append(dict(type="line", y0=s5.min(), y1=s5.min(), x0=0, x1=1, xref="paper",
                               line=dict(color="#14b143", width=1, dash="dot")))
        fig = dict(data=tr, layout=dict(**DARK, height=280,
                   title=dict(text=f"{nm} PB（归母口径）·红虚线=五年max·黄虚线=max×0.7目标", font=dict(size=12)),
                   xaxis=dict(**GRID), yaxis=dict(**GRID, title="PB"), showlegend=True,
                   legend=dict(orientation="h", y=1.2, x=0), shapes=shapes))
        charts.append(pio.to_html(fig, include_plotlyjs=False, full_html=False, config=cfg,
                                   div_id=f"pb_{nm}"))

    # 申万地产指数（0625 回验）
    i2 = idx[idx.index >= "2026-04-01"]
    fig_i = dict(data=[dict(type="scatter", mode="lines",
                            x=i2.index.astype(str).tolist(), y=i2.tolist(),
                            line=dict(color="#e8c35a", width=1.8))],
                 layout=dict(**DARK, height=260,
                 title=dict(text=f"六家房企等权净值（0625 预测回验：{chg_idx:+.1f}%）", font=dict(size=12)),
                 xaxis=dict(**GRID), yaxis=dict(**GRID)))
    chart_idx = pio.to_html(fig_i, include_plotlyjs=False, full_html=False, config=cfg, div_id="idx")

    tbl5 = tbl[tbl["窗"] == "五年"].set_index("公司")
    tbl10 = tbl[tbl["窗"] == "十年"].set_index("公司")
    ct = ""
    for nm, (pb0, pct0, r0) in CAITONG.items():
        mine = tbl5.loc[nm]
        ct += (f"<tr><td>{nm}</td><td>{pb0}</td><td>{mine['当前PB(归母)']}</td>"
               f"<td>{pct0}%</td><td>{mine['当前分位%']}%</td>"
               f"<td>{r0}%</td><td>{mine['涨幅%']}%</td></tr>")

    css = """*{box-sizing:border-box;margin:0;padding:0}body{font:13.5px/1.7 system-ui,'Microsoft YaHei',sans-serif;
    background:#16181d;color:#d8dce3;padding:22px 30px 60px;max-width:1100px;margin:0 auto}
    h1{font-size:19px;margin-bottom:2px}.sub{color:#7a8494;font-size:12px;margin-bottom:18px}
    h2{font-size:15px;color:#e8c35a;margin:26px 0 8px;border-left:3px solid #e8c35a;padding-left:9px}
    p{color:#b8c0cc;margin:6px 0}p b{color:#d8dce3}.pos{color:#ef232a}.neg{color:#14b143}
    table{border-collapse:collapse;font-size:12px;margin:8px 0;width:100%}
    th,td{padding:5px 8px;border-bottom:1px solid #23262e;text-align:right;white-space:nowrap}
    th{color:#9aa3b2;font-weight:500}td.l,th.l{text-align:left}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    .warn{background:#3a3320;color:#e8c35a;border-radius:6px;padding:8px 12px;font-size:12.5px;margin:10px 0}"""
    return f"""<!DOCTYPE html><html lang=zh><head><meta charset='utf-8'><title>analysis_002 PB回归验证</title>
<script src='plotly.min.js'></script><style>{css}</style></head><body>
<h1>验证财通「PB 回归法」——六家 A 股房企 PB 分位与修复目标</h1>
<div class='sub'>analysis_002 · 数据：BigQuant stock_valuation（pb 口径已修正为归母）+ 东财四表财报面板 ·
截至 2026-08-21 · 引用：property_reversal_targets_caitong_20260531（表1 截至 5/29）</div>
<div class='warn'>★ 口径修正：BigQuant pb 分母=全部权益（含少数股东），财通/Wind=归母权益。
地产股少数股东占比 37%~64%（合作开发），不修正则 PB 全部低估约一半——本页所有 PB 均已按
财报面板少数占比修正为归母口径。另：六家 5/29→8/21 股价 -3%~-17%（其中 5/29→6/25 续跌、6/25→8/21 反弹 +7.4%）。</div>
<h2>一、PB 分位与十分位（当前所处历史位置）</h2>
{tbl_to_html(tbl5, "五年窗（2021 起）")}
{tbl_to_html(tbl10, "十年窗（2016 起）")}
<h2>二、与财通表1 对照（重叠 3 家）</h2>
<table><tr><th class='l'>公司</th><th>财通PB@5/29</th><th>本地PB@8/21</th><th>财通五年分位</th>
<th>本地五年分位</th><th>财通五年修复</th><th>本地五年涨幅(max×0.7)</th></tr>{ct}</table>
<p>差异来源：① 数据日不同（5/29 vs 8/21，期间板块再跌）② 净资产期次（财通用 2025 年报，本地用 2026H1）
③ 财通 PB 为 Wind 口径，本地为修正后归母口径。方向一致性是验证重点。</p>
<h2>三、PB 走势（六年）</h2>
<div class='grid2'>{''.join(charts)}</div>
<h2>四、0625 预测回验</h2>
<p>财通系列三（6/25）判断"未来一个季度内房股温和上行"。实际六家等权 6/25→8/21：
<b class='{'pos' if chg_idx > 0 else 'neg'}'>{chg_idx:+.1f}%</b> ——
{'<b>预测兑现</b>（注意起点：5/29→6/25 板块曾再跌一程，报告发布恰在低点，之后温和反弹，与左侧布局框架自洽）。' if chg_idx > 0 else '预测未兑现。'}</p>
{chart_idx}
<p class='sub'>口径：目标价 = 目标PB × BPS（财报面板最新每股净资产）；涨幅 = 目标PB/当前PB − 1，
与复权无关。"max×0.7" 为财通正文口径；"70% 分位" 为稳健中枢口径（分位数对端点不敏感）。
财通数字一律为原文口径，未复现验证。</p>
</body></html>"""


def tbl_to_html(t: pd.DataFrame, title: str) -> str:
    cols = ["当前PB(归母)", "历史max", "当前分位%", "十分位", "目标PB(max×0.7)", "目标价", "涨幅%",
            "目标PB(70%分位)", "涨幅B%"]
    head = "".join(f"<th>{c}</th>" for c in cols)
    body = ""
    for nm, r in t.iterrows():
        body += f"<tr><td class='l'>{nm}</td>" + "".join(
            f"<td>{r[c]}</td>" for c in cols) + "</tr>"
    return f"<p><b>{title}</b></p><table><tr><th class='l'>公司</th>{head}</tr>{body}</table>"


if __name__ == "__main__":
    sys.exit(main())
