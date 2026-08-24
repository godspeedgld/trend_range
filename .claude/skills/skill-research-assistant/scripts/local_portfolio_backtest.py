#!/usr/bin/env python
"""组合回测引擎（skill-report-replication-cta-ts）——开仓池/平仓池框架。

固定框架（引擎写死）：
  每日收盘（t 日决策）：
    1. 持仓股检查平仓条件 → 平仓池
    2. 开仓池股票检查剔除条件
    3. 非持仓非开仓池股票扫入场信号 → 开仓池
  次日开盘（t+1 执行）：
    0. 平仓池全部平仓（开盘价）
    1. 持仓 ≥ n → 不操作
    2. 持仓 < n → 从开仓池按优先顺序选股开仓（开盘价，权重 1/n）
  每日收益 = Σ(weight × 标的收益) - 调仓成本；现金收益 0

可变部分（策略脚本 strategy.py 实现 5 个函数，见 templates/portfolio_strategy.py）：
    entry_signal(hist_df) -> bool                # 入选逻辑
    exit_check(entry_info, hist_df) -> bool     # 剔出/平仓逻辑
    pool_invalidate(hist_df) -> bool            # 开仓池剔除
    select_order(open_pool) -> list[sym]        # 开仓优先选择
    position_weight(sym, n, hist_df) -> float   # 单股权重（默认 1/n）

输出与 local_backtest.py 一致：equity/metrics/trades_paired/weights + html 报告。
"""
from __future__ import annotations

import argparse
import html as _html
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from local_backtest import normalize_market, read_table, compute_metrics, BacktestConfig

DEFAULT_PARAMS = {
    "max_positions": 10,     # n：最大持仓数（权重 1/n）
    "cost_bps": 15.0,        # 双边成本
    "warmup": 60,            # 数据暖期（上市<60日剔除）
}


# ═══════════════════════════════════════════════════════════
# 策略装载（5 接口）
# ═══════════════════════════════════════════════════════════

def load_portfolio_strategy(path: Path):
    spec_file = importlib.util.spec_from_file_location("portfolio_mod", str(path))
    if spec_file is None or spec_file.loader is None:
        raise RuntimeError(f"无法装载策略: {path}")
    mod = importlib.util.module_from_spec(spec_file)
    spec_file.loader.exec_module(mod)
    for fn in ("entry_signal", "exit_check", "select_order"):
        if not hasattr(mod, fn):
            raise RuntimeError(f"strategy.py 缺少必需函数: {fn}")
    # 可选：pool_invalidate / position_weight（引擎给默认）
    return mod


# ═══════════════════════════════════════════════════════════
# 引擎主循环（固定框架）
# ═══════════════════════════════════════════════════════════

def run_portfolio(market: pd.DataFrame, strat, params: dict):
    """开仓池/平仓池组合回测主循环。

    market: date,symbol,open,high,low,close[,volume,amount] 多标的
    strat: 策略模块（5 接口）
    Returns: (daily_ret, holdings_df, trades_df)
    """
    max_n = params["max_positions"]
    cost = params["cost_bps"] / 10000.0
    warmup = params["warmup"]

    dates = sorted(market["date"].unique())
    symbols = sorted(market["symbol"].unique())

    # 透视表（date × symbol）供快速取数
    open_px = market.pivot_table(index="date", columns="symbol", values="open").sort_index()
    close_px = market.pivot_table(index="date", columns="symbol", values="close").sort_index()

    # 每标的分组（供策略函数用历史 df）
    sym_groups = {sym: g.sort_values("date").reset_index(drop=True)
                  for sym, g in market.groupby("symbol")}
    # 日期→行号映射（每标的）
    sym_date_idx = {sym: {d: i for i, d in enumerate(g["date"])} for sym, g in sym_groups.items()}

    holdings = {}      # sym -> {"entry_date", "entry_price", "peak", "weight", "info"}
    open_pool = {}     # sym -> {"signal_date", ...info}
    daily_rets = []
    holdings_rows = []
    trades = []

    def hist_df(sym, t_date):
        """取 sym 到 t_date（含）的历史 df。"""
        g = sym_groups[sym]
        idx = sym_date_idx[sym].get(t_date)
        if idx is None:
            return g.iloc[0:0]
        return g.iloc[:idx + 1]

    for t in range(warmup, len(dates)):
        d = dates[t]
        d_next = dates[t + 1] if t + 1 < len(dates) else None

        # ── 收盘阶段：决策 ──
        close_pool = []
        for sym in list(holdings):
            h = holdings[sym]
            hd = hist_df(sym, d)
            if len(hd) == 0:
                continue
            if strat.exit_check(h, hd):
                close_pool.append(sym)

        # 开仓池剔除（传信号日，非当前日）
        for sym in list(open_pool):
            hd = hist_df(sym, d)
            if len(hd) == 0:
                del open_pool[sym]
                continue
            invalidate = getattr(strat, "pool_invalidate", None)
            if invalidate and invalidate(hd, open_pool[sym].get("signal_date", d)):
                del open_pool[sym]

        # 扫描入场信号（非持仓非开仓池）
        for sym in symbols:
            if sym in holdings or sym in open_pool:
                continue
            hd = hist_df(sym, d)
            if len(hd) < warmup:
                continue
            if strat.entry_signal(hd):
                open_pool[sym] = {"signal_date": d}

        # ── 开盘阶段：次日执行 ──
        if d_next is None:
            break
        turnover = 0.0
        # 平仓（开盘价卖出）
        for sym in close_pool:
            h = holdings.pop(sym)
            exit_price = open_px.loc[d_next, sym] if sym in open_px.columns and d_next in open_px.index else np.nan
            if pd.isna(exit_price):
                exit_price = close_px.loc[d, sym]
            ret = exit_price / h["entry_price"] - 1.0
            trades.append({
                "symbol": sym, "entry_date": h["entry_date"],
                "entry_price": round(h["entry_price"], 4),
                "exit_date": d_next, "exit_price": round(exit_price, 4),
                "holding_days": int((pd.Timestamp(d_next) - pd.Timestamp(h["entry_date"])).days),
                "weight": h["weight"], "return_pct": round(ret * 100, 4),
            })
            turnover += h["weight"]
        # 开仓（持仓 < n 时）
        if len(holdings) < max_n and open_pool:
            ordered = strat.select_order(dict(open_pool))
            picks = [s for s in ordered if s not in holdings][:max_n - len(holdings)]
            for sym in picks:
                if sym in open_px.columns and d_next in open_px.index:
                    epx = open_px.loc[d_next, sym]
                else:
                    continue
                if pd.isna(epx):
                    continue
                w_fn = getattr(strat, "position_weight", None)
                w = w_fn(sym, max_n, hist_df(sym, d)) if w_fn else 1.0 / max_n
                holdings[sym] = {"entry_date": d_next, "entry_price": epx,
                                 "peak": epx, "weight": w}
                del open_pool[sym]
                turnover += w

        # ── 当日收益（close-to-close，基于昨日收盘持仓）──
        d_prev = dates[t - 1]
        r = 0.0
        for sym, h in holdings.items():
            c_now = close_px.loc[d, sym] if sym in close_px.columns else np.nan
            c_prev = close_px.loc[d_prev, sym] if sym in close_px.columns else np.nan
            if pd.notna(c_now) and pd.notna(c_prev) and c_prev > 0:
                r += h["weight"] * (c_now / c_prev - 1.0)
            h["peak"] = max(h["peak"], c_now if pd.notna(c_now) else h["peak"])
        r -= turnover * cost  # 调仓成本
        daily_rets.append({"date": d, "ret": r,
                           "n_holdings": len(holdings),
                           "cash_weight": max(0.0, 1.0 - sum(h["weight"] for h in holdings.values()))})
        for sym, h in holdings.items():
            holdings_rows.append({"date": d, "symbol": sym, "weight": h["weight"]})

    daily_df = pd.DataFrame(daily_rets).set_index("date")
    trades_df = pd.DataFrame(trades)
    holdings_df = pd.DataFrame(holdings_rows)
    return daily_df, holdings_df, trades_df


# ═══════════════════════════════════════════════════════════
# 输出
# ═══════════════════════════════════════════════════════════

def write_outputs(cfg: BacktestConfig, daily: pd.Series, holdings_df, trades_df,
                  metrics: dict, params: dict, out_dir: Path = None):
    sdir = out_dir if out_dir is not None else cfg.project_dir / "03_backtest_strategy"
    sdir = Path(sdir)
    logs = sdir / "backtest_logs"
    logs.mkdir(parents=True, exist_ok=True)
    nav = (1 + daily).cumprod()
    pd.DataFrame({"date": daily.index, "net_return": daily.values, "nav": nav.values,
                  "drawdown": (nav / nav.cummax() - 1.0).values}).to_csv(
        logs / "equity_curve.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(logs / "performance_metrics.csv",
                                   index=False, encoding="utf-8-sig")
    if trades_df is not None and len(trades_df):
        trades_df.to_csv(logs / "trades_paired.csv", index=False, encoding="utf-8-sig")
    if holdings_df is not None and len(holdings_df):
        holdings_df.to_csv(logs / "position_return_detail.csv", index=False, encoding="utf-8-sig")
    (sdir / "config.json").write_text(json.dumps({
        "engine": "portfolio pool-based", "params": params,
        "cost_bps": cfg.cost_bps, "n_trades": int(len(trades_df))},
        ensure_ascii=False, indent=2), encoding="utf-8")

    # html 报告（净值+回撤+交易表，与 local_backtest 风格一致）
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3],
                        subplot_titles=("Strategy NAV", "Drawdown"))
    fig.add_trace(go.Scatter(x=nav.index, y=nav.values, name="NAV",
                             line=dict(color="#2980b9", width=1.4)), row=1, col=1)
    dd = nav / nav.cummax() - 1.0
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                             line=dict(color="#c0392b", width=0.7),
                             fillcolor="rgba(192,57,43,0.15)"), row=2, col=1)
    fig.update_layout(template="plotly_white", height=460, hovermode="x unified",
                      margin=dict(l=50, r=30, t=40, b=30), showlegend=False)
    nav_html = fig.to_html(full_html=False, include_plotlyjs=False, div_id="fig_nav")

    # 交易级统计：胜率 / 盈亏比（平均盈利 ÷ 平均亏损）
    n = int(len(trades_df)) if trades_df is not None else 0
    trade_wr, payoff = float("nan"), float("nan")
    if trades_df is not None and len(trades_df):
        t = trades_df
        trade_wr = (t["return_pct"] > 0).mean() * 100
        wins = t[t["return_pct"] > 0]["return_pct"]
        losses = t[t["return_pct"] < 0]["return_pct"]
        if len(wins) and len(losses) and losses.mean() != 0:
            payoff = wins.mean() / abs(losses.mean())

    def _cell(v, fmt):
        return fmt(v) if v == v else "—"          # NaN → 占位

    trades_html = "<p>无交易记录。</p>"
    if n:
        rows = "".join(
            f"<tr><td>{i+1}</td><td>{r.symbol}</td><td>{r.entry_date}</td>"
            f"<td>{r.entry_price:.2f}</td><td>{r.exit_date}</td><td>{r.exit_price:.2f}</td>"
            f"<td style='color:{'#27ae60' if r.return_pct>0 else '#e74c3c'}'>{r.return_pct:+.2f}%</td>"
            f"<td>{r.holding_days}</td></tr>"
            for i, r in enumerate(trades_df.itertuples()))
        trades_html = (
            f"<p>共 {n} 笔，胜率 {trade_wr:.1f}%，盈亏比 {_cell(payoff, lambda v: f'{v:.2f}')}</p>"
            f"<div style='max-height:480px;overflow:auto'>"
            f"<table><tr><th>#</th><th>symbol</th><th>开仓日</th><th>开仓价</th><th>平仓日</th>"
            f"<th>平仓价</th><th>收益</th><th>持仓天数</th></tr>{rows}</table></div>")

    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>组合回测报告</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;}}
table{{border-collapse:collapse;width:100%;}}th,td{{border:1px solid #d6dae1;padding:6px 10px;}}
th{{background:#f3f5f8;}}
/* 页签（CSS radio，无 JS） */
.tab-radio{{display:none;}}
.tab-label{{display:inline-block;padding:9px 22px;cursor:pointer;border:1px solid #d6dae1;
  border-bottom:none;background:#f3f5f8;margin-right:4px;border-radius:6px 6px 0 0;}}
.tab-radio:checked + .tab-label{{background:#fff;font-weight:bold;border-top:2px solid #2980b9;}}
.tab-panel{{display:none;border:1px solid #d6dae1;padding:18px;border-radius:0 6px 6px 6px;}}
#tab_perf:checked ~ #panel_perf{{display:block;}}
#tab_trades:checked ~ #panel_trades{{display:block;}}
.metrics{{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0;}}
.metrics .item{{flex:1 1 120px;text-align:center;border:1px solid #e4e8ee;border-radius:8px;padding:12px 6px;}}
.metrics .item b{{display:block;font-size:18px;margin-top:4px;}}
.metrics .item span{{color:#6b7480;font-size:12px;}}
</style></head><body>
<h1>组合回测报告（开仓池/平仓池引擎）</h1>
<div class="note">收盘决策（平仓池/开仓池/入场扫描）→ 次日开盘执行（平仓+开仓，权重 1/n）。
收益 close-to-close，调仓成本 {params['cost_bps']}bps 双边。</div>

<div class="tabs">
<input type="radio" id="tab_perf" name="tabs" class="tab-radio" checked>
<label for="tab_perf" class="tab-label">净值与绩效</label>
<input type="radio" id="tab_trades" name="tabs" class="tab-radio">
<label for="tab_trades" class="tab-label">交易记录（{n}）</label>

<div class="tab-panel" id="panel_perf">
<div class="metrics">
  <div class="item"><span>净值</span><b>{metrics.get('final_nav', 0):.3f}</b></div>
  <div class="item"><span>年化收益</span><b>{metrics.get('annual_return', 0)*100:.2f}%</b></div>
  <div class="item"><span>Sharpe</span><b>{metrics.get('sharpe', 0):.2f}</b></div>
  <div class="item"><span>最大回撤</span><b>{metrics.get('max_drawdown', 0)*100:.2f}%</b></div>
  <div class="item"><span>交易数</span><b>{n}</b></div>
  <div class="item"><span>交易胜率</span><b>{_cell(trade_wr, lambda v: f'{v:.1f}%')}</b></div>
  <div class="item"><span>盈亏比</span><b>{_cell(payoff, lambda v: f'{v:.2f}')}</b></div>
</div>
{nav_html}
</div>

<div class="tab-panel" id="panel_trades">
<h3 style="margin-top:0">交易明细</h3>
{trades_html}
</div>
</div>
</body></html>"""
    (sdir / "backtest_report.html").write_text(body, encoding="utf-8")


# ═══════════════════════════════════════════════════════════

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--market-data", required=True,
                   help="多标的 OHLCV CSV/Parquet（date,symbol,open,high,low,close）")
    p.add_argument("--strategy", help="strategy.py 路径，默认 03_backtest_strategy/strategy.py")
    p.add_argument("--max-positions", type=int, default=DEFAULT_PARAMS["max_positions"])
    p.add_argument("--cost-bps", type=float, default=DEFAULT_PARAMS["cost_bps"])
    p.add_argument("--warmup", type=int, default=DEFAULT_PARAMS["warmup"])
    p.add_argument("--output-dir", help="输出目录（默认 {project_dir}/03_backtest_strategy）")
    p.add_argument("--initial-cash", type=float, default=1_000_000.0)
    p.add_argument("--annualization", type=float, default=252.0)
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    cfg = BacktestConfig(
        project_dir=proj, market_data=Path(args.market_data).resolve(),
        strategy_py=Path(args.strategy).resolve() if args.strategy else proj / "03_backtest_strategy" / "strategy.py",
        cost_bps=args.cost_bps, slippage_bps=0.0,
        initial_cash=args.initial_cash, annualization=args.annualization, allow_short=False)
    if not cfg.market_data.exists():
        raise FileNotFoundError(f"market data 不存在: {cfg.market_data}")

    market = normalize_market(read_table(cfg.market_data), cfg)
    market["date"] = pd.to_datetime(market["date"])
    print(f"数据: {len(market)} rows, {market['symbol'].nunique()} 标的, "
          f"{market['date'].min().date()} ~ {market['date'].max().date()}")

    strat = load_portfolio_strategy(cfg.strategy_py)
    params = {"max_positions": args.max_positions, "cost_bps": args.cost_bps,
              "warmup": args.warmup}

    daily_df, holdings_df, trades_df = run_portfolio(market, strat, params)
    daily = daily_df["ret"]
    daily.index = pd.to_datetime(daily.index)
    metrics = compute_metrics(daily, cfg)
    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    write_outputs(cfg, daily, holdings_df, trades_df, metrics, params, out_dir)

    out = {"ok": True, "metrics": metrics,
           "n_trades": int(len(trades_df)) if trades_df is not None else 0}
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
