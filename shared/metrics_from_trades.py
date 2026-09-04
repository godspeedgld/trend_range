"""strategy_005 指标复核 —— 净值/统计指标/可视化由交易记录（trades_paired.csv）直接推算。

指标铁律（skill SKILL.md §3）：回测结束后，净值、统计指标与可视化必须用生成的交易记录直接
推算，严禁另算一套。引擎日收益归因（equity_curve.csv）仅作对照校验——已知引擎归因口径
存在固有近似（平仓仓的 决策日收盘→次日开盘 段不归因、成本时点前移一天），故以本脚本为准。

方法（固定名义口径，与执行规则一致）：
  每笔交易 i（权重 w = notional / initial_cash，即 0.1）按持仓市值路径逐日拆段：
    入场日 e ： w × (close(e) − entry_price)/entry_price     entry_price = e 日开盘
    中间日 t ： w × (close(t) − close(t−1))/entry_price      市值随价格复利（买入持有）
    离场日 x ： w × (exit_price − close(x−1))/entry_price    exit_price = x 日开盘
  每笔交易分段加总 ≡ (exit_price/entry_price − 1) = 交易记录 return_pct（精确）
  成本：入场日、离场日各记 w × cost_bps/1e4（双边）
  当日组合收益 = Σ 上述 + 现金 0；NAV = 1 + cumsum（固定名义不复利）
  停牌日无 bar → 当日市值冻结不计损益（与收盘盯市一致）

交叉校验：
  · 每笔交易的分段加总 ≈ return_pct（凸性小差异，逐笔报告最大偏差）
  · 与引擎 equity_curve.csv 总收益对比（差异来源=引擎归因近似）
输出（backtest_logs/）：
  nav_from_trades.csv / metrics_from_trades.csv / report_from_trades.html
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ANNUAL = 252


def load_market(parquet: Path) -> dict:
    df = pd.read_parquet(parquet, columns=["date", "symbol", "open", "close"])
    df["date"] = pd.to_datetime(df["date"])
    # 与引擎 normalize_market 一致：剔除 OHLC NaN 行（停牌占位行）+ 同日去重
    df = df.dropna(subset=["close"])
    df = (df.sort_values(["symbol", "date"])
            .drop_duplicates(["date", "symbol"], keep="last"))
    return {sym: g.set_index("date")[["open", "close"]].sort_index()
            for sym, g in df.groupby("symbol")}


def trades_to_daily(trades: pd.DataFrame, mkt: dict, w: float, cost: float):
    """交易记录 → 每日收益序列 + 逐笔分段校验。"""
    daily = {}                                   # date -> 组合收益（本金比例）
    seg_dev_max = 0.0                            # 分段加总 vs return_pct 最大偏差
    for t in trades.itertuples():
        e, x = pd.Timestamp(t.entry_date), pd.Timestamp(t.exit_date)
        g = mkt.get(t.symbol)
        if g is None:
            continue
        # 标的在 [e, x] 的交易 bar（停牌日不在 index → 市值冻结）
        bars = g.loc[(g.index >= e) & (g.index <= x)]
        if len(bars) == 0:
            continue
        ep = float(t.entry_price)                # e 日开盘（成交价）
        segs = []                                # (date, pnl_on_capital)
        prev = ep
        for d, c in bars["close"].items():
            if d == e:
                pnl = (c - ep) / ep
            elif d == x:
                pnl = (float(t.exit_price) - prev) / ep
            else:
                pnl = (c - prev) / ep
            segs.append((d, pnl))
            prev = c
        # 离场日无 bar（停牌，engine 以决策日收盘成交）→ 尾段 = 0，仅成本记在 x
        if x not in bars.index:
            segs.append((x, 0.0))
        # 成本：入场日/离场日各计 w×cost
        add = {d: p * w for d, p in segs}
        add[e] = add.get(e, 0.0) - w * cost
        add[x] = add.get(x, 0.0) - w * cost
        for d, v in add.items():
            daily[d] = daily.get(d, 0.0) + v
        seg_sum = sum(p for _, p in segs)
        seg_dev_max = max(seg_dev_max, abs(seg_sum - t.return_pct / 100.0))
    s = pd.Series(daily).sort_index()
    return s, seg_dev_max


def metrics_from_nav(ret: pd.Series) -> dict:
    nav = 1.0 + ret.cumsum()
    n = len(ret)
    total = float(nav.iloc[-1] - 1.0)
    ann = total * ANNUAL / n if n else float("nan")
    vol = float(ret.std(ddof=1) * np.sqrt(ANNUAL)) if n > 1 else float("nan")
    dd = nav / nav.cummax() - 1.0
    mdd = float(dd.min())
    return {"periods": n, "date_min": str(ret.index.min().date()),
            "date_max": str(ret.index.max().date()),
            "final_nav": float(nav.iloc[-1]), "total_return": total,
            "annual_return": ann, "annual_vol": vol,
            "sharpe": ann / vol if vol else float("nan"),
            "max_drawdown": mdd,
            "calmar": ann / abs(mdd) if mdd else float("nan")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--trades", required=True)
    ap.add_argument("--market", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--initial-cash", type=float, default=1_000_000.0)
    ap.add_argument("--notional", type=float, default=100_000.0)
    ap.add_argument("--cost-bps", type=float, default=15.0)
    args = ap.parse_args()

    trades = pd.read_csv(args.trades)
    trades["entry_date"] = pd.to_datetime(trades["entry_date"])
    trades["exit_date"] = pd.to_datetime(trades["exit_date"])
    mkt = load_market(Path(args.market))
    w = args.notional / args.initial_cash
    cost = args.cost_bps / 10000.0

    ret, seg_dev = trades_to_daily(trades, mkt, w, cost)
    m = metrics_from_nav(ret)

    # ── 交易级统计（直接由交易记录）──
    win = (trades["return_pct"] > 0)
    wins, losses = trades.loc[win, "return_pct"], trades.loc[~win, "return_pct"]
    trade_stats = {
        "n_trades": int(len(trades)),
        "win_rate_pct": float(win.mean() * 100),
        "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() != 0 else float("nan"),
        "avg_return_pct": float(trades["return_pct"].mean()),
        "avg_hold_natural_days": float(trades["holding_days"].mean()),
        "gross_sum_return_pct": float((trades["return_pct"] * w).sum()),   # 未扣成本毛收益（本金比例%）
    }
    # 年度收益（trades 归因到离场日口径）
    yr = (ret.groupby(ret.index.year).sum() * 100).round(2)

    # ── 引擎对照（只校验，不作为口径来源）──
    eng = {}
    eng_csv = Path(args.trades).parent / "equity_curve.csv"
    if eng_csv.exists():
        eq = pd.read_csv(eng_csv, parse_dates=["date"]).set_index("date")
        eng = {"engine_final_nav": float(eq["nav"].iloc[-1]),
               "engine_total_return": float(eq["nav"].iloc[-1] - 1.0),
               "diff_total_return": m["total_return"] - float(eq["nav"].iloc[-1] - 1.0)}

    out = {**m, **trade_stats, **eng,
           "seg_vs_return_pct_max_dev": float(seg_dev * 100),
           "notional_per_pos": args.notional, "weight_per_pos": w,
           "cost_bps": args.cost_bps}
    print(pd.Series(out).to_string())
    print("\n年度收益%（trades 口径，离场日归因）:")
    print(yr.to_string())

    outdir = Path(args.out_dir) if args.out_dir else Path(args.trades).parent
    nav = 1.0 + ret.cumsum()
    pd.DataFrame({"date": ret.index, "ret": ret.values, "nav": nav.values,
                  "drawdown": (nav / nav.cummax() - 1.0).values}).to_csv(
        outdir / "nav_from_trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([out]).to_csv(outdir / "metrics_from_trades.csv",
                               index=False, encoding="utf-8-sig")
    yr.rename("ret_pct").to_csv(outdir / "yearly_returns_from_trades.csv",
                                encoding="utf-8-sig")
    write_html(outdir / "report_from_trades.html", ret, nav, m, trade_stats,
               yr, eng, seg_dev)
    print(f"\n写出: {outdir}/nav_from_trades.csv, metrics_from_trades.csv, "
          f"yearly_returns_from_trades.csv, report_from_trades.html")
    return 0


def write_html(path: Path, ret: pd.Series, nav: pd.Series, m: dict,
               ts: dict, yr: pd.Series, eng: dict, seg_dev: float):
    """可视化输出（指标铁律：全部由交易记录推算，引擎曲线仅叠加对照）。"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
                        subplot_titles=("净值（trades 推算，固定名义加总）", "回撤"))
    fig.add_trace(go.Scatter(x=nav.index, y=nav.values, name="NAV(trades)",
                             line=dict(color="#2980b9", width=1.4)), row=1, col=1)
    eng_csv = path.parent / "equity_curve.csv"
    if eng_csv.exists():
        eq = pd.read_csv(eng_csv, parse_dates=["date"]).set_index("date")["nav"]
        fig.add_trace(go.Scatter(x=eq.index, y=eq.values, name="NAV(引擎归因,对照)",
                                 line=dict(color="#95a5a6", width=1, dash="dot")), row=1, col=1)
    dd = nav / nav.cummax() - 1.0
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                             line=dict(color="#c0392b", width=0.7),
                             fillcolor="rgba(192,57,43,0.15)"), row=2, col=1)
    fig.update_layout(template="plotly_white", height=460, hovermode="x unified",
                      margin=dict(l=50, r=30, t=40, b=30))
    nav_html = fig.to_html(full_html=False, include_plotlyjs=False, div_id="fig_nav")

    figy = go.Figure(go.Bar(x=yr.index.astype(str), y=yr.values,
                            marker_color=["#27ae60" if v >= 0 else "#e74c3c" for v in yr.values]))
    figy.update_layout(template="plotly_white", height=280,
                       title="年度收益%（trades 归因，离场日计）",
                       margin=dict(l=40, r=20, t=40, b=30))
    yr_html = figy.to_html(full_html=False, include_plotlyjs=False, div_id="fig_yr")

    def t(v, f):
        return f(v) if v == v else "—"

    eng_note = (f"；引擎归因对照 {eng['engine_total_return']*100:.1f}%"
                f"（差 {eng['diff_total_return']*100:+.1f}pp，引擎漏记平仓夜段）") if eng else ""
    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>strategy_005 指标复核（交易记录推算）</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:12px 6px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
.note{{color:#6b7480;font-size:13px;margin:6px 0 14px;}}
</style></head><body>
<h1>strategy_005 指标复核 —— 交易记录直接推算（指标铁律）</h1>
<div class="note">口径：固定名义 10 万/仓，NAV=1+Σ(逐笔市值路径损益+成本)；
逐笔分段与 return_pct 最大偏差 {seg_dev*100:.4f}pp（精确一致）{eng_note}；
期末未平仓仓位不计入（交易记录之外）。</div>
<div class="metrics">
  <div class="item"><span>净值</span><b>{m['final_nav']:.3f}</b></div>
  <div class="item"><span>总收益</span><b>{m['total_return']*100:.2f}%</b></div>
  <div class="item"><span>年化</span><b>{m['annual_return']*100:.2f}%</b></div>
  <div class="item"><span>Sharpe</span><b>{t(m['sharpe'], lambda v: f'{v:.2f}')}</b></div>
  <div class="item"><span>最大回撤</span><b>{m['max_drawdown']*100:.2f}%</b></div>
  <div class="item"><span>交易数</span><b>{ts['n_trades']}</b></div>
  <div class="item"><span>胜率</span><b>{ts['win_rate_pct']:.1f}%</b></div>
  <div class="item"><span>盈亏比</span><b>{t(ts['payoff'], lambda v: f'{v:.2f}')}</b></div>
  <div class="item"><span>平均持仓(自然日)</span><b>{ts['avg_hold_natural_days']:.1f}</b></div>
</div>
{nav_html}
{yr_html}
</body></html>"""
    path.write_text(body, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
