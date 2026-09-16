"""analysis_007 — v3 水平带突破信号成功率评估（全市场沪深300成分，2017 至今）。

【更新四 2026-08-28（当前版）】在更新三扫描结论上固化两项（用户指定，其他规则全部不变）：
  1. **止盈规则**：吊灯倍数固定 **m=4**（收盘 < 突破后最高价 − 4×ATR(14)）——更新三甜点
  2. **突破规则**：**突破程度 degree ≥ 2** 才算突破（单转折点带 degree=1 的突破剔除，
     不入场不判定）

  其余不变：入场=突破次日开盘；止损=收盘<阻力线（优先）；离场价=触发日收盘；
  成功=止盈且收益>0；失败=止损 或 止盈但收益≤0；无界持有，数据尽未触发→未决。
  degree 分桶相应改为 2 / 3-5 / 6+（1 档被过滤）。

【历史版本】（详见 records.md）
  更新二：事件级止损+2×ATR吊灯模拟（胜率34.4%/盈亏比2.26/+0.61%/持仓6bar）
  更新三：吊灯倍数扫描{2,3,4,5}——胜率单调降/盈亏比单调升/期望m=4走平(+1.76%)

结构：事件缓存 v3_events_cache.parquet（一次采集，含全部 degree）；ATR14 预计算缓存
shared/atr14_panel.parquet；本版模拟/过滤纯查表。
输出：breakout_detail_v3.parquet/csv、summary_by_degree / by_year / by_symbol.csv、result_view.html
铁律：信号生成无未来数据；成败判定为事后评估，自然用后续行情。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent.parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo_v3 import run_band_breakout      # noqa: E402
from atr14_precompute import load_atr14            # noqa: E402

ATR_MULT = 4.0      # 更新四：吊灯倍数固定 4
MIN_DEGREE = 2      # 更新四：突破程度 ≥2 才算突破（degree=1 剔除）
START = "2017-01-01"
EVENT_CACHE = HERE / "v3_events_cache.parquet"


# ── 事件采集（一次，落盘缓存，含全部 degree）─────────────────
def scan_events() -> pd.DataFrame:
    if EVENT_CACHE.exists():
        df = pd.read_parquet(EVENT_CACHE)
        df["date"] = pd.to_datetime(df["date"])
        return df
    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])
    rows = []
    symbols = market["symbol"].unique()
    for k, sym in enumerate(symbols, 1):
        g = market[market["symbol"] == sym].sort_values("date").reset_index(drop=True)
        if len(g) < 60:
            continue
        try:
            events, _bands, _tb = run_band_breakout(g)
        except Exception as ex:
            print(f"  WARN {sym}: {ex}")
            continue
        for e in events:
            if e["type"] != "break_up":
                continue
            d = pd.Timestamp(e["date"])
            if d < pd.Timestamp(START):
                continue
            hits = g.index[g["date"] == e["date"]]
            if len(hits) == 0:
                continue
            rows.append({"symbol": sym, "name": g["name"].iloc[0], "date": d,
                         "close_sig": float(e["close"]), "line": float(e["line"]),
                         "lo": float(e["lo"]), "hi": float(e["hi"]),
                         "degree": int(e["degree"]), "sig_i": int(hits[0])})
        if k % 100 == 0:
            print(f"  ... {k}/{len(symbols)}, events {len(rows)}", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(EVENT_CACHE, index=False)
    return df


# ── 事件级模拟（止损优先 / m×ATR 吊灯）──────────────────────
def simulate_event(g: pd.DataFrame, atr: np.ndarray, sig_i: int, line: float) -> dict | None:
    """从 t+1 开盘入场，逐日收盘判定：先止损（close<line），后吊灯（close<max_high−4×ATR14）。

    atr: 与 g 行对齐的 ATR14 数组（NaN 当日跳过吊灯）。返回事件结果 dict；无前向数据返回 None。
    """
    n = len(g)
    if sig_i + 1 >= n:
        return None
    opens, highs, closes = g["open"].values, g["high"].values, g["close"].values
    dates = g["date"].values
    base = float(opens[sig_i + 1])
    max_hi = float(np.nanmax(highs[sig_i:sig_i + 1]))      # 突破后最高价：自信号日起（含）
    for k in range(sig_i + 1, n):
        hk, ck = highs[k], closes[k]
        max_hi = max(max_hi, float(hk)) if not np.isnan(hk) else max_hi
        if np.isnan(ck):
            continue                                        # 停牌：仓位冻结
        if ck < line:                                       # ① 止损（优先）
            ret = ck / base - 1.0
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ret, "exit_reason": "stop_loss",
                    "hold_bars": k - sig_i, "max_high": max_hi}
        a = atr[k]
        if a is not None and not np.isnan(a) and ck < max_hi - ATR_MULT * a:   # ② 吊灯 m=4
            ret = ck / base - 1.0
            return {"base": base, "exit_date": dates[k], "exit_price": float(ck),
                    "ret": ret, "exit_reason": "chandelier",
                    "hold_bars": k - sig_i, "max_high": max_hi}
    return {"base": base, "exit_date": None, "exit_price": np.nan,
            "ret": np.nan, "exit_reason": "pending",
            "hold_bars": n - 1 - sig_i, "max_high": max_hi}


def classify(row: dict) -> tuple:
    """失败=止损 或 止盈但收益≤0；成功=止盈且收益>0；pending=数据尽未触发。"""
    if row["exit_reason"] == "pending":
        return "pending", "pending_nofwd"
    if row["exit_reason"] == "stop_loss":
        return "fail", "stop_loss"
    return ("success", "chan_pos") if row["ret"] > 0 else ("fail", "chan_nonpos")


def deg_bucket(d: int) -> str:
    return "2" if d == 2 else "3-5" if d <= 5 else "6+"


def agg_stats(dec: pd.DataFrame, keys):
    keys = [keys] if isinstance(keys, str) else keys
    out = (dec.groupby(keys)["result"]
           .agg(total="count",
                成功=lambda s: int((s == "success").sum()),
                失败=lambda s: int((s == "fail").sum())).reset_index())
    out["胜率%"] = (out["成功"] / out["total"] * 100).round(1)
    stats = (dec.groupby(keys)
             .apply(lambda x: pd.Series({
                 "平均收益%": round(x["ret"].mean() * 100, 2),
                 "盈亏比": (round(x.loc[x.ret > 0, "ret"].mean()
                                / abs(x.loc[x.ret <= 0, "ret"].mean()), 2)
                           if (x.ret > 0).any() and (x.ret <= 0).any() else np.nan),
                 "持仓中位(bar)": round(x["hold_bars"].median()),
             }), include_groups=False).reset_index())
    return out.merge(stats, on=keys, how="left")


def main():
    events_all = scan_events()
    events = events_all[events_all["degree"] >= MIN_DEGREE].copy()
    print(f"事件缓存 {len(events_all)} 个；degree>={MIN_DEGREE} 过滤后 {len(events)} 个（剔除 "
          f"{len(events_all) - len(events)} 个 degree=1）")

    market = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
    market["date"] = pd.to_datetime(market["date"])
    groups = {s: g.sort_values("date").reset_index(drop=True)
              for s, g in market.groupby("symbol")}

    atr_df = load_atr14(PROJ / "_market_hs300_panel.parquet", SHARED)
    atr_by_sym = {s: x.set_index("date")["atr14"] for s, x in atr_df.groupby("symbol")}

    all_rows = []
    for sym, evs in events.groupby("symbol"):
        g = groups.get(sym)
        if g is None:
            continue
        a_ser = atr_by_sym.get(sym)
        atr = (g["date"].map(a_ser).to_numpy(dtype=float) if a_ser is not None
               else np.full(len(g), np.nan))
        for r in evs.itertuples():
            sim = simulate_event(g, atr, int(r.sig_i), float(r.line))
            if sim is None:
                continue
            result, reason = classify(sim)
            all_rows.append({"symbol": r.symbol, "name": r.name, "date": r.date,
                             "close_sig": r.close_sig, "line": r.line, "lo": r.lo, "hi": r.hi,
                             "degree": r.degree, "deg_bucket": deg_bucket(r.degree),
                             "year": r.date.year, "atr_mult": ATR_MULT,
                             **sim, "result": result, "reason": reason})
    det = pd.DataFrame(all_rows)
    det.to_parquet(HERE / "breakout_detail_v3.parquet", index=False)
    det.to_csv(HERE / "breakout_detail_v3.csv", index=False, encoding="utf-8-sig")
    print(f"明细落盘：{len(det)} 行")

    dec = det[det["result"].isin(["success", "fail"])].copy()
    n_s = int((dec["result"] == "success").sum())
    n_f = int((dec["result"] == "fail").sum())
    rate = n_s / len(dec) * 100
    wins, losses = dec.loc[dec["ret"] > 0, "ret"], dec.loc[dec["ret"] <= 0, "ret"]
    payoff = wins.mean() / abs(losses.mean())
    by_deg = agg_stats(dec, "deg_bucket")
    by_deg["o"] = by_deg["deg_bucket"].map({"2": 0, "3-5": 1, "6+": 2})
    by_deg = by_deg.sort_values("o").drop(columns="o")
    by_year = agg_stats(dec, "year").sort_values("year")
    by_sym = agg_stats(dec, ["symbol", "name"]).sort_values("total", ascending=False)

    print("\n=== 更新四：m=4 吊灯 + degree>=2 过滤（其余同更新二）===")
    print(f"事件 {len(det)} | 已判定 {len(dec)}（成功 {n_s} / 失败 {n_f}）| "
          f"未决 {int((det['result'] == 'pending').sum())}")
    print(f"胜率 {rate:.1f}% | 盈亏比 {payoff:.2f} | 平均收益 {dec['ret'].mean()*100:+.2f}% | "
          f"持仓中位 {dec['hold_bars'].median():.0f} bar")
    print("离场原因构成:", dec["reason"].value_counts().to_dict())
    print("\n=== 分 degree ===")
    print(by_deg.to_string(index=False))
    print("\n=== 年度 ===")
    print(by_year.to_string(index=False))
    by_deg.to_csv(HERE / "summary_by_degree.csv", index=False, encoding="utf-8-sig")
    by_year.to_csv(HERE / "summary_by_year.csv", index=False, encoding="utf-8-sig")
    by_sym.to_csv(HERE / "summary_by_symbol.csv", index=False, encoding="utf-8-sig")
    _viz(det, dec, n_s, n_f, rate, payoff, by_deg, by_year)


def _viz(det, dec, n_s, n_f, rate, payoff, by_deg, by_year):
    sys.path.insert(0, str(PROJ.parents[2] / ".claude" / "skills" / "skill-research-assistant" / "scripts"))
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    figs = {}
    f1 = make_subplots(specs=[[{"secondary_y": True}]])
    f1.add_trace(go.Bar(x=by_deg["deg_bucket"], y=by_deg["成功"], name="成功",
                        marker_color="#27ae60"), 1, 1)
    f1.add_trace(go.Bar(x=by_deg["deg_bucket"], y=by_deg["失败"], name="失败",
                        marker_color="#e74c3c"), 1, 1)
    f1.add_trace(go.Scatter(x=by_deg["deg_bucket"], y=by_deg["胜率%"], name="胜率%",
                            mode="lines+markers+text", text=by_deg["胜率%"],
                            textposition="top center", line=dict(color="#2c3e50", width=2.5)),
                 secondary_y=True)
    f1.update_layout(barmode="stack", title="分 degree：胜率（m=4 吊灯 + degree>=2）", height=420)
    f1.update_yaxes(title_text="次数", secondary_y=False)
    f1.update_yaxes(title_text="胜率%", secondary_y=True, range=[0, 100])
    figs["deg_rate"] = f1

    f2 = make_subplots(specs=[[{"secondary_y": True}]])
    f2.add_trace(go.Bar(x=by_deg["deg_bucket"], y=by_deg["盈亏比"], name="盈亏比",
                        marker_color="#8e44ad"), 1, 1)
    f2.add_trace(go.Scatter(x=by_deg["deg_bucket"], y=by_deg["平均收益%"], name="平均收益%",
                            mode="lines+markers", line=dict(color="#e67e22", width=2.5)),
                 secondary_y=True)
    f2.update_layout(title="分 degree：盈亏比 / 平均收益%", height=420)
    figs["deg_payoff"] = f2

    f3 = make_subplots(specs=[[{"secondary_y": True}]])
    f3.add_trace(go.Bar(x=by_year["year"], y=by_year["成功"], name="成功",
                        marker_color="#27ae60"), 1, 1)
    f3.add_trace(go.Bar(x=by_year["year"], y=by_year["失败"], name="失败",
                        marker_color="#e74c3c"), 1, 1)
    f3.add_trace(go.Scatter(x=by_year["year"], y=by_year["胜率%"], name="胜率%",
                            mode="lines+markers", line=dict(color="#2c3e50", width=2.5)),
                 secondary_y=True)
    f3.update_layout(barmode="stack", title="年度：胜率 / 次数", height=420)
    f3.update_yaxes(title_text="次数", secondary_y=False)
    f3.update_yaxes(title_text="胜率%", secondary_y=True, range=[0, 100])
    figs["year"] = f3

    f4 = go.Figure()
    f4.add_trace(go.Histogram(x=dec["hold_bars"], nbinsx=80, marker_color="#2980b9"))
    f4.update_layout(title="持仓 bar 数分布（中位 %.0f）" % dec["hold_bars"].median(),
                     xaxis_title="持仓交易日", height=380)
    figs["hold"] = f4

    rc = dec["reason"].value_counts()
    colors = {"stop_loss": "#c0392b", "chan_pos": "#27ae60", "chan_nonpos": "#e67e22"}
    f5 = go.Figure()
    f5.add_trace(go.Bar(x=rc.index, y=rc.values,
                        marker_color=[colors.get(c, "#95a5a6") for c in rc.index]))
    f5.update_layout(title="离场原因构成", height=380)
    figs["reason"] = f5

    parts = [f.to_html(full_html=False, include_plotlyjs=(i == 0), div_id=f"fig_{k}")
             for i, (k, f) in enumerate(figs.items())]
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>analysis_007 更新四 — m=4 吊灯 + degree≥2 过滤</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;background:#fff;}}
.stats{{color:#333;font-size:14px;}} table{{border-collapse:collapse;margin:10px 0;}}
th,td{{border:1px solid #d6dae1;padding:5px 10px;font-size:13px;}}</style>
</head><body>
<h1>analysis_007 更新四 — 吊灯固定 4×ATR(14) + 突破程度 degree ≥ 2</h1>
<p class="stats"><b>规则</b>：入场=突破次日开盘；止损=收盘&lt;阻力线（优先）；
吊灯=收盘&lt;突破后最高价−4×ATR(14)；离场价=触发日收盘；degree&lt;2 的突破不计。</p>
<h2>总体</h2>
<p class="stats">事件 {len(det)} | 成功 {n_s} / 失败 {n_f} |
<b>胜率 {rate:.1f}%</b> | <b>盈亏比 {payoff:.2f}</b> |
平均收益 {dec['ret'].mean()*100:+.2f}% | 持仓中位 {dec['hold_bars'].median():.0f} bar</p>
<h2>分 degree（2 / 3-5 / 6+）</h2>
{by_deg.to_html(index=False)}
{''.join(parts)}
</body></html>"""
    out = HERE / "result_view.html"
    out.write_text(body, encoding="utf-8")
    print("Saved:", out)


if __name__ == "__main__":
    main()
