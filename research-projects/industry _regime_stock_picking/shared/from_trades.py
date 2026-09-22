"""共享 —— **由交易记录直接推算**净值与统计指标（技能「指标铁律」）。

技能铁律：回测结束后，净值、统计指标（年化/Sharpe/回撤/胜率等）与相应可视化**必须用
生成的交易记录（trades_paired）直接推算**，严禁另算一套 —— 交易记录是策略实际执行的
唯一事实源。若引擎口径与 trades 推算不符，须修引擎或明确标注差异，不得静默采用。

本脚本只读 `trades_paired.csv` + 行情，重建逐日组合收益 → nav → metrics，
产出（与 hs300-enh 工程同名）：
  nav_from_trades.csv           date, ret, nav, drawdown
  metrics_from_trades.csv       periods, final_nav, total_return, ...
  yearly_returns_from_trades.csv
  trade_stats_from_trades.csv   交易级胜率/盈亏比/右尾（本策略族的核心口径）

收益口径（与引擎一致，故可直接对账）：
  入场日   open → close          （t+1 开盘成交）
  持有中   close → close
  平仓日   prev_close → exit_price（开盘价卖出，当日仍计入收益）
  每日组合收益 = Σ weightᵢ × retᵢ，减去当日调仓成本 turnover × cost_bps
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

COST_BPS = 8.0          # 与引擎 --cost-bps 一致（对称双边近似；策略真实为买0.03%/卖0.13%）


def load_prices(market_path: Path) -> pd.DataFrame:
    mk = pd.read_parquet(market_path, columns=["date", "symbol", "open", "close"])
    mk["date"] = pd.to_datetime(mk["date"])
    return mk


def rebuild(logs: Path, market_path: Path) -> tuple[pd.Series, pd.DataFrame]:
    tr = pd.read_csv(logs / "trades_paired.csv", encoding="utf-8-sig")
    tr["entry_date"] = pd.to_datetime(tr["entry_date"])
    tr["exit_date"] = pd.to_datetime(tr["exit_date"])
    mk = load_prices(market_path)

    open_px = mk.pivot_table(index="date", columns="symbol", values="open").sort_index().ffill()
    close_px = mk.pivot_table(index="date", columns="symbol", values="close").sort_index().ffill()
    dates = close_px.index

    rets = {}
    for r in tr.itertuples():
        if r.symbol not in close_px.columns:
            continue
        seg = dates[(dates >= r.entry_date) & (dates <= r.exit_date)]
        if len(seg) == 0:
            continue
        prev_c = None
        for d in seg:
            c = close_px.at[d, r.symbol]
            if pd.isna(c):
                prev_c = c
                continue
            if d == r.entry_date:
                o = open_px.at[d, r.symbol]
                rr = (c / o - 1.0) if pd.notna(o) and o > 0 else 0.0
            elif d == r.exit_date:
                rr = (r.exit_price / prev_c - 1.0) if prev_c and prev_c > 0 else 0.0
            else:
                rr = (c / prev_c - 1.0) if prev_c and prev_c > 0 else 0.0
            rets[d] = rets.get(d, 0.0) + r.weight * rr
            prev_c = c

    daily = pd.Series(rets).sort_index()
    # 调仓成本：交易记录里每笔的开/平各算一次 weight 的换手
    cost = pd.Series(0.0, index=daily.index)
    for r in tr.itertuples():
        cost[r.entry_date] = cost.get(r.entry_date, 0.0) + r.weight * COST_BPS / 1e4
        cost[r.exit_date] = cost.get(r.exit_date, 0.0) + r.weight * COST_BPS / 1e4
    daily = (daily - cost.reindex(daily.index).fillna(0.0)).sort_index()
    # ★ 必须重索引到**全部交易日**（空仓日收益 0）：否则 periods 只有"有持仓的天数"，
    #   年化 = nav^(252/n) 的 n 偏小 → 年化被系统性高估。
    span = dates[(dates >= tr["entry_date"].min()) & (dates <= tr["exit_date"].max())]
    daily = daily.reindex(span).fillna(0.0)
    return daily, tr


def metrics_from(daily: pd.Series, annualization: float = 252.0) -> dict:
    nav = (1 + daily).cumprod()
    n = len(daily)
    total = float(nav.iloc[-1] - 1.0)
    ann = float(nav.iloc[-1] ** (annualization / n) - 1.0) if n else np.nan
    vol = float(daily.std(ddof=1) * np.sqrt(annualization)) if n > 1 else np.nan
    dn = daily[daily < 0]
    dv = float(dn.std(ddof=1) * np.sqrt(annualization)) if len(dn) > 1 else np.nan
    dd = float((nav / nav.cummax() - 1.0).min())
    gains, losses = daily[daily > 0], daily[daily < 0]
    return {
        "periods": float(n), "final_nav": float(nav.iloc[-1]), "total_return": total,
        "annual_return": ann, "annual_volatility": vol, "downside_volatility": dv,
        "sharpe": ann / vol if vol else np.nan, "sortino": ann / dv if dv else np.nan,
        "calmar": ann / abs(dd) if dd else np.nan, "max_drawdown": dd,
        "win_rate": float(gains.mean() if len(gains) else np.nan),
        "daily_win_rate": float((daily > 0).mean()),
        "profit_factor": float(gains.sum() / abs(losses.sum())) if len(losses) else np.nan,
    }


def trade_stats(tr: pd.DataFrame) -> pd.DataFrame:
    """交易级统计 —— 本策略族的核心口径（引擎 performance_metrics 的 win_rate 是日频）。"""
    r = tr["return_pct"]
    rows = [{
        "n_trades": len(tr),
        "trade_win_rate": float((r > 0).mean()),
        "avg_ret_pct": float(r.mean()),
        "median_ret_pct": float(r.median()),
        "avg_win_pct": float(r[r > 0].mean()) if (r > 0).any() else np.nan,
        "avg_loss_pct": float(r[r < 0].mean()) if (r < 0).any() else np.nan,
        "payoff_ratio": float(r[r > 0].mean() / abs(r[r < 0].mean()))
                        if (r > 0).any() and (r < 0).any() else np.nan,
        "profit_factor": float(r[r > 0].sum() / abs(r[r < 0].sum())) if (r < 0).any() else np.nan,
        "tail_gt10_pct": float((r > 10).mean()),
        "tail_lt_minus10_pct": float((r < -10).mean()),
        "avg_holding_days": float(tr["holding_days"].mean()),
    }]
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs_dir", help="backtest_logs 目录")
    ap.add_argument("--market", required=True)
    args = ap.parse_args()
    logs = Path(args.logs_dir).resolve()
    daily, tr = rebuild(logs, Path(args.market).resolve())

    nav = (1 + daily).cumprod()
    pd.DataFrame({"date": daily.index, "ret": daily.values, "nav": nav.values,
                  "drawdown": (nav / nav.cummax() - 1.0).values}).to_csv(
        logs / "nav_from_trades.csv", index=False, encoding="utf-8-sig")
    m = metrics_from(daily)
    pd.DataFrame([m]).to_csv(logs / "metrics_from_trades.csv", index=False,
                             encoding="utf-8-sig")
    yr = (daily.groupby(daily.index.year).apply(lambda s: (1 + s).prod() - 1)
          .mul(100).round(2).rename("ret_pct").to_frame())
    yr.to_csv(logs / "yearly_returns_from_trades.csv", encoding="utf-8-sig")
    trade_stats(tr).to_csv(logs / "trade_stats_from_trades.csv", index=False,
                           encoding="utf-8-sig")

    # 与引擎口径对账
    eng = logs / "performance_metrics.csv"
    print(f"— {logs.parent.name}/{logs.name}")
    if eng.exists():
        e = pd.read_csv(eng, encoding="utf-8-sig").iloc[0]
        for k in ["total_return", "annual_return", "sharpe", "max_drawdown"]:
            if k in e:
                d = m[k] - float(e[k])
                print(f"    {k:<16} 引擎 {float(e[k]):>9.4f}   trades {m[k]:>9.4f}   Δ {d:+.4f}")
    ts = trade_stats(tr).iloc[0]
    print(f"    交易级: {int(ts.n_trades)} 笔 / 胜率 {ts.trade_win_rate:.1%} / "
          f"盈亏比 {ts.payoff_ratio:.3f} / 单笔均值 {ts.avg_ret_pct:+.2f}%")


if __name__ == "__main__":
    main()
