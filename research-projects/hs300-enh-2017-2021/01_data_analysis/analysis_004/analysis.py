"""analysis_004 — v2.7 突破信号成功率评估（全市场沪深300成分，2017 至今）。

更新一（新成败规则 + 20 天窗口字段落盘）：

  · 基准价格：突破后第二天开盘价（突破日 t，t+1 开盘）
  · 观察窗口：t+1 ~ t+20 共 20 个交易日
  · 失败规则：① 窗口内最低价 跌破 基准×0.95（dip5），或 ② 第 20 日收盘收益率 < 0（ret20_neg）
  · 成功规则：窗口内未破基准×0.95，且（第 20 日收盘收益率 > 0（ret20_pos），
             或 窗口内最高价 > 基准×1.10（high10））
  · 前向数据不足 20 根：能判 dip5 则判，否则 pending_nofwd；未破且收益恰为 0 → pending_flat

落盘字段（breakout_detail.parquet/csv，一次采集、支持任意重判不再重跑 v2.7）：
  date/symbol/name/break_price/line_val/dist       信号与线信息
  base（次日开盘）/ min_low_20 / max_high_20 / close_20 / ret_20
  min_low_inf / max_high_inf / first_dip_date / first_high_date   （旧规则与首触发顺序重判用）
  result / reason / hit_date / hit_price            新规则判定结果

数据：`_market_hs300_panel.parquet`（668 只历史成分，2015~2026-08-21）。
铁律：信号生成无未来数据；成功/失败判定为事后评估，自然使用后续行情。

输出：
  breakout_detail.parquet / breakout_detail.csv   明细
  summary_by_year.csv / summary_by_symbol.csv     汇总
  result_view.html                                可视化（年度/按标的/分布）
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo_v2 import run_trendline_breakout   # noqa: E402

FAIL_PCT = 0.05     # 窗口内最低 < 基准×0.95 → 失败
WIN_PCT = 0.10      # 窗口内最高 > 基准×1.10 → 成功（条件之一）
WINDOW = 20         # 观察窗口（交易日）
START = "2017-01-01"


def window_stats(g: pd.DataFrame, sig_i: int) -> dict | None:
    """采集一次 break_up 的 20 天窗口统计（相对次日开盘 base）。

    返回 None 表示无前向数据（信号日即最后一根）。
    前向不足 20 根时 min/max 按可用天数算，close_20 为 NaN。
    """
    if sig_i + 1 >= len(g):
        return None
    fut = g.iloc[sig_i + 1:]
    base = float(g["open"].iloc[sig_i + 1])
    lows, highs = fut["low"].values, fut["high"].values
    dates = fut["date"].values
    n = len(fut)
    w = min(n, WINDOW)
    min_low_20 = float(lows[:w].min())
    max_high_20 = float(highs[:w].max())
    close_20 = float(g["close"].iloc[sig_i + w]) if n >= WINDOW else np.nan
    ret_20 = close_20 / base - 1 if n >= WINDOW else np.nan
    fail_th, win_th = base * (1 - FAIL_PCT), base * (1 + WIN_PCT)
    dip_mask, high_mask = lows < fail_th, highs > win_th
    first_dip = dates[int(np.argmax(dip_mask))] if dip_mask.any() else None
    first_high = dates[int(np.argmax(high_mask))] if high_mask.any() else None
    return {"base": base, "n_fwd": n,
            "min_low_20": min_low_20, "max_high_20": max_high_20,
            "close_20": close_20, "ret_20": ret_20,
            "min_low_inf": float(lows.min()), "max_high_inf": float(highs.max()),
            "first_dip_date": first_dip, "first_high_date": first_high}


def apply_rule(st: dict):
    """新成败规则（见模块 docstring）。返回 (result, reason, hit_date, hit_price)。"""
    fail_th, win_th = st["base"] * (1 - FAIL_PCT), st["base"] * (1 + WIN_PCT)
    if st["min_low_20"] < fail_th:                      # 失败①：窗口内破 -5%
        return "fail", "dip5", st["first_dip_date"], st["min_low_20"]
    if np.isnan(st["ret_20"]):                          # 前向不足：dip5 未触发 → 未决
        return "pending", "pending_nofwd", None, np.nan
    if st["ret_20"] < 0:                                # 失败②：20 日收益为负
        return "fail", "ret20_neg", None, st["close_20"]
    if st["max_high_20"] > win_th:                      # 成功①：窗口内冲过 +10%
        return "success", "high10", st["first_high_date"], st["max_high_20"]
    if st["ret_20"] > 0:                                # 成功②：20 日收益为正
        return "success", "ret20_pos", None, st["close_20"]
    return "pending", "pending_flat", None, np.nan      # 收益恰为 0 且未冲 +10%


def scan_symbol(g: pd.DataFrame) -> list[dict]:
    """单股票：跑 v2.7 → 所有 break_up → 采集窗口统计 + 新规则判定。"""
    events, lines, _ = run_trendline_breakout(g)
    rows = []
    for e in events:
        if e["type"] != "break_up":
            continue
        d = pd.Timestamp(e["date"])
        if d < pd.Timestamp(START):
            continue
        hits = g.index[g["date"] == e["date"]]
        if len(hits) == 0:
            continue
        sig_i = int(hits[0])
        st = window_stats(g, sig_i)
        if st is None:
            continue
        result, reason, hit_date, hit_price = apply_rule(st)
        rows.append({"symbol": g["symbol"].iloc[0], "name": g["name"].iloc[0],
                     "date": d, "break_price": float(e["price"]),
                     "line_val": float(e["line_val"]), "dist": float(e["dist"]),
                     **st, "result": result, "reason": reason,
                     "hit_date": hit_date, "hit_price": hit_price})
    return rows


def summarize(det: pd.DataFrame):
    decided = det[det["result"].isin(["success", "fail"])]
    n_s = int((decided["result"] == "success").sum())
    n_f = int((decided["result"] == "fail").sum())
    rate = n_s / len(decided) * 100 if len(decided) else np.nan
    yr = (decided.groupby("year")["result"]
          .agg(total="count",
               成功=lambda s: int((s == "success").sum()),
               失败=lambda s: int((s == "fail").sum())).reset_index())
    yr["成功率%"] = (yr["成功"] / yr["total"] * 100).round(1)
    by_sym = (decided.groupby(["symbol", "name"])["result"]
              .agg(total="count",
                   成功=lambda s: int((s == "success").sum()),
                   失败=lambda s: int((s == "fail").sum())).reset_index())
    by_sym["成功率%"] = (by_sym["成功"] / by_sym["total"] * 100).round(1)
    by_sym = by_sym.sort_values("total", ascending=False)
    return decided, n_s, n_f, rate, yr, by_sym


def main():
    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])

    all_rows = []
    symbols = market["symbol"].unique()
    for k, sym in enumerate(symbols, 1):
        g = market[market["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if len(g) < 60:
            continue
        try:
            all_rows.extend(scan_symbol(g))
        except Exception as ex:
            print(f"  ⚠️ {sym}: {ex}")
        if k % 100 == 0:
            print(f"  … {k}/{len(symbols)} 只，累计 {len(all_rows)} 次突破")
    det = pd.DataFrame(all_rows)
    det["year"] = det["date"].dt.year
    det.to_parquet(HERE / "breakout_detail.parquet", index=False)
    det.to_csv(HERE / "breakout_detail.csv", index=False, encoding="utf-8-sig")
    print(f"\n明细落盘：{HERE / 'breakout_detail.parquet'}  ({len(det)} 行)")

    decided, n_s, n_f, rate, yr, by_sym = summarize(det)
    print(f"\n=== 总体（2017 起 | 基准=次日开盘 | 失败=破-5%或20日收益<0 | 成功=未破且(收益>0或冲+10%)）===")
    print(f"突破总数 {len(det)} | 已判定 {len(decided)} | 成功 {n_s} | 失败 {n_f} | 成功率 {rate:.1f}%")
    print("\n失败原因构成:", decided[decided['result'] == 'fail']['reason'].value_counts().to_dict())
    print("成功原因构成:", decided[decided['result'] == 'success']['reason'].value_counts().to_dict())
    print("\n=== 年度 ===")
    print(yr.to_string(index=False))
    print(f"\n=== 按标的（前 15 按次数，共 {len(by_sym)} 只）===")
    print(by_sym.head(15).to_string(index=False))

    yr.to_csv(HERE / "summary_by_year.csv", index=False, encoding="utf-8-sig")
    by_sym.to_csv(HERE / "summary_by_symbol.csv", index=False, encoding="utf-8-sig")
    _viz(det, decided, n_s, n_f, rate, yr, by_sym)


def _viz(det, decided, n_s, n_f, rate, yr, by_sym):
    sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    figs = {}
    f1 = make_subplots(specs=[[{"secondary_y": True}]])
    f1.add_trace(go.Bar(x=yr["year"], y=yr["成功"], name="成功", marker_color="#27ae60"), 1, 1)
    f1.add_trace(go.Bar(x=yr["year"], y=yr["失败"], name="失败", marker_color="#e74c3c"), 1, 1)
    f1.add_trace(go.Scatter(x=yr["year"], y=yr["成功率%"], name="成功率%", mode="lines+markers",
                            line=dict(color="#2c3e50", width=2.5)), secondary_y=True)
    f1.update_layout(barmode="stack",
                     title="v2.7 突破信号年度成功率（失败=破-5%或20日收益<0；成功=未破且(收益>0或冲+10%)）",
                     height=460)
    f1.update_yaxes(title_text="次数", secondary_y=False)
    f1.update_yaxes(title_text="成功率%", secondary_y=True, range=[0, 100])
    figs["year"] = f1

    # 失败/成功原因构成（年度堆叠）
    pv = decided.pivot_table(index="year", columns="reason", values="symbol", aggfunc="count").fillna(0)
    f2 = go.Figure()
    colors = {"dip5": "#c0392b", "ret20_neg": "#e67e22", "high10": "#27ae60", "ret20_pos": "#2980b9"}
    for c in pv.columns:
        f2.add_trace(go.Bar(x=pv.index, y=pv[c], name=c, marker_color=colors.get(c, "#95a5a6")))
    f2.update_layout(barmode="stack", title="成败原因构成（dip5=窗口内破-5% | ret20_neg=20日收益<0 | high10=冲+10% | ret20_pos=20日收益>0）",
                     height=460)
    figs["reason"] = f2

    top = by_sym.head(30).iloc[::-1]
    f3 = go.Figure()
    f3.add_trace(go.Bar(y=top["name"] + " " + top["symbol"], x=top["成功"], name="成功",
                        orientation="h", marker_color="#27ae60"))
    f3.add_trace(go.Bar(y=top["name"] + " " + top["symbol"], x=-top["失败"], name="失败",
                        orientation="h", marker_color="#e74c3c"))
    f3.update_layout(barmode="relative", title=f"按标的信号量 Top30（绿=成功，红=失败；共 {len(by_sym)} 只）",
                     height=700)
    figs["sym"] = f3

    f4 = go.Figure()
    f4.add_trace(go.Histogram(x=by_sym["成功率%"], nbinsx=20, marker_color="#2980b9"))
    f4.update_layout(title="各标的成功率分布", xaxis_title="成功率%", yaxis_title="标的数", height=380)
    figs["dist"] = f4

    parts = [f.to_html(full_html=False, include_plotlyjs=(i == 0), div_id=f"fig_{k}")
             for i, (k, f) in enumerate(figs.items())]
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>v2.7 突破成功率评估（更新一）</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;background:#fff;}}
.stats{{color:#333;font-size:14px;}}</style>
</head><body>
<h1>v2.7 突破信号成功率评估（更新一）— 沪深300 全成分 2017~今</h1>
<p class="stats"><b>总体</b>：突破 {len(det)} 次 | 已判定 {len(decided)} | <b>成功 {n_s} / 失败 {n_f} |
成功率 <b>{rate:.1f}%</b></p>
<p class="stats"><b>规则（更新一）</b>：基准=突破次日开盘；窗口=20 交易日；
失败=窗口内最低 &lt; 基准×0.95 <b>或</b> 第 20 日收益 &lt; 0；
成功=窗口内未破 −5% 且（第 20 日收益 &gt; 0 <b>或</b> 窗口内最高 &gt; 基准×1.10）。</p>
{''.join(parts)}
</body></html>"""
    out = HERE / "result_view.html"
    out.write_text(body, encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
