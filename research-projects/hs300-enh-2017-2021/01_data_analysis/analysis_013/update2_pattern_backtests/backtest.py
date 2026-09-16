"""analysis_013 更新二 — 11 种形态/通道各自独立回测 + 全部突破对照（沪深300 指数择时化）。

研报是事件研究（形态×持有 5/10/20 日收益统计），非完整择时回测——本更新把每种形态
做成一个**可交易回测**（研报方法 + 显式交易规则），检验形态信息在执行层是否留存。

数据：沪深300 指数 000300.SH，2015-01-01 至今（本地 warehouse index_bar1d）。
信号（画法=渤海复现变体B，因果口径，已过一致性检查）：
  rolling N=120 / w=5 / τ=0.9,0.1（shared/quantreg_sr_algo.py，阈值可参数化，本跑用默认）
规则（用户指定）：
  开仓：空仓且 close[t] > R_t（当日因果压力线）且当日形态=目标形态（对照=全部突破）
       → t+1 开盘成交（铁律：t 收盘决策，t+1 开盘执行）
  止损：entry − 3×ATR14(信号日)（静态）；止盈：入场以来最高 high − 3×ATR14(当日)（吊灯）
       盘中 low 触发，成交价 = min(open, 触发价)（跳空按开盘）
  仓位：满仓；成本：单边 10bps（ETF/股指期货近似，显式假设）
产物：runs/{run_id}/trades.csv|nav.csv|metrics.json + summary_table.csv（外层汇总）
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ / "shared"))
from quantreg_sr_algo import (DURATION_PATTERNS, breakout_signals,  # noqa: E402
                              rolling_lines)

WAREHOUSE = PROJ.parents[2] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
START = "2015-01-01"
ATR_N, ATR_K = 14, 3.0
COST = 10 / 1e4          # 单边
warnings.filterwarnings("ignore", module="statsmodels.*")


def load_index() -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute("SELECT date, open, high, low, close FROM index_bar1d "
                     "WHERE instrument='000300.SH' AND date >= ? ORDER BY date",
                     [START]).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna().reset_index(drop=True)
    df.to_parquet(HERE / "hs300_index.parquet", index=False)   # 数据缓存
    return df


def atr14(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_N, adjust=False).mean()


def simulate(df: pd.DataFrame, sig: pd.DataFrame, atr: np.ndarray, run_name: str):
    """事件驱动：空仓 close>R(且形态过滤) 次日开盘入；止损/吊灯盘中触发；满仓。"""
    n = len(df)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    dates = df["date"]
    has_line = sig["R"].reindex(dates).notna().to_numpy()
    R = sig["R"].reindex(dates).to_numpy()
    dur = sig["dur_pattern"].reindex(dates).to_numpy()
    chan = sig["chan_pattern"].reindex(dates).to_numpy()
    rets = np.zeros(n)
    trades, i = [], 0
    while i < n - 1:
        entry_ok = has_line[i] and c[i] > R[i] and (
            run_name == "全部对照" or dur[i] == run_name or chan[i] == run_name)
        if not entry_ok:
            i += 1
            continue
        e = i + 1                                  # t+1 开盘成交
        ep = o[e]
        floor_static = ep - ATR_K * atr[i]         # 信号日 ATR
        peak = h[e]
        j, xp, reason = e, np.nan, None
        for j in range(e, n):
            floor = max(floor_static, peak - ATR_K * atr[j])
            if l[j] <= floor:
                xp = min(o[j], floor)
                reason = "止损" if floor == floor_static else "吊灯止盈"
                break
            peak = max(peak, h[j])
        else:
            j, xp, reason = n - 1, c[n - 1], "期末"   # 数据末仍持仓 → 期末收盘记平（含成本）
        trades.append({"entry_date": dates[e].date(), "entry_price": round(ep, 2),
                       "exit_date": dates[j].date(), "exit_price": round(xp, 2),
                       "ret_pct": round((xp / ep - 1) * 100, 3), "reason": reason,
                       "hold_days": int(j - e + 1)})
        # 日收益：入场日 open→close；中间 close→close；离场日 prev_close→exit
        rets[e] = (c[e] / ep - 1) - COST
        for k in range(e + 1, j):
            rets[k] = c[k] / c[k - 1] - 1
        if j > e:
            rets[j] = (xp / c[j - 1] - 1) - COST
        else:
            rets[e] = (xp / ep - 1) - 2 * COST     # 当日进出的极端情况
        i = j                                      # 离场后从 j 起可再评估入场（无同日重入）
    return rets, trades


def metrics(rets: np.ndarray, trades: list) -> dict:
    nav = np.cumprod(1 + rets)
    r = pd.Series(rets)
    total = nav[-1] - 1
    ann = nav[-1] ** (252 / len(rets)) - 1
    sharpe = (r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    t = pd.DataFrame(trades)
    wins, losses = t[t.ret_pct > 0].ret_pct, t[t.ret_pct <= 0].ret_pct
    return {"n_trades": len(t), "win_rate_pct": round(len(wins) / len(t) * 100, 1) if len(t) else np.nan,
            "payoff": round(wins.mean() / abs(losses.mean()), 2) if len(wins) and len(losses) and losses.mean() != 0 else np.nan,
            "avg_ret_pct": round(t.ret_pct.mean(), 3) if len(t) else np.nan,
            "avg_hold_days": round(t.hold_days.mean(), 1) if len(t) else np.nan,
            "total_return_pct": round(total * 100, 1), "annual_pct": round(ann * 100, 2),
            "sharpe": round(sharpe, 2), "maxDD_pct": round(dd * 100, 1)}


def main():
    df = load_index()
    df = df.set_index("date")
    atr = atr14(df).to_numpy()
    sig = breakout_signals(rolling_lines(df, causal=True), df["close"])   # 变体B 画法（因果）

    runs = ([(f"dur_{k}", k) for k in DURATION_PATTERNS]
            + [(f"chan_{k}", k) for k in ("上升通道收敛", "上升通道发散", "横盘",
                                          "下降通道收敛", "下降通道发散")]
            + [("all_全部对照", "全部对照")])
    rows = []
    for run_id, name in runs:
        rets, trades = simulate(df.reset_index(), sig, atr, name)
        m = metrics(rets, trades)
        rd = HERE / "runs" / run_id
        rd.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(trades).to_csv(rd / "trades.csv", index=False, encoding="utf-8-sig")
        nav = pd.DataFrame({"date": df.index, "ret": rets})
        nav["nav"] = (1 + nav["ret"]).cumprod()
        nav.to_csv(rd / "nav.csv", index=False)
        (rd / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=2), "utf-8")
        rows.append({"run_id": run_id, "形态": name, **m})
        print(f"{run_id:14s} {name:8s} 笔数{m['n_trades']:4d} 总收益{m['total_return_pct']:+8.1f}% "
              f"年化{m['annual_pct']:+7.2f}% Sharpe{m['sharpe']:+6.2f} maxDD{m['maxDD_pct']:+7.1f}% "
              f"胜率{m['win_rate_pct']}%")
    pd.DataFrame(rows).to_csv(HERE / "summary_table.csv", index=False, encoding="utf-8-sig")
    print("\nsummary_table.csv 写出:", HERE / "summary_table.csv")


if __name__ == "__main__":
    main()
