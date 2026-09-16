"""analysis_011 更新一 — decile≥4 过滤 A_v2 交易记录 + 正式指标 + 可视化。

过滤：信号日十分位（生成版口径，过去 252 日收盘分布）≥4 才保留（剔除 1~3 档负期望区）。
指标：strategy_005/metrics_from_trades.py 同尺子（指标铁律）。
⚠ 简化静态筛选口径（同 analysis_008）：不重排坑位，真实引擎中被剔交易不占仓、
其他信号可能提前入场——结果偏保守估计，方向性参考。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
METRICS_CLI = PROJ / "02_strategy_iteration/strategy_005/metrics_from_trades.py"
PANEL = PROJ / "_market_hs300_panel_2017.parquet"

tr = pd.read_csv(HERE / "trades_deciled.csv", encoding="utf-8-sig")
# 还原 trades_paired 全列：从 A_v2 原表 merge
a2 = pd.read_csv(PROJ / "02_strategy_iteration/strategy_006/ab_tests/A_v2/backtest_logs/trades_paired.csv",
                 encoding="utf-8-sig")
tr["key"] = tr["symbol"] + "|" + pd.to_datetime(tr["entry_date"]).dt.strftime("%Y-%m-%d")
a2["key"] = a2["symbol"] + "|" + pd.to_datetime(a2["entry_date"]).dt.strftime("%Y-%m-%d")
full = a2.merge(tr[["key", "decile", "ok"]], on="key", how="inner")

for thr in (4,):
    kept = full[full["decile"] >= thr].drop(columns=["key", "decile", "ok"])
    dropped = full[full["decile"] < thr]
    kept.to_csv(HERE / f"A_v2_decile{thr}.csv", index=False, encoding="utf-8-sig")
    print(f"[decile>={thr}] 保留 {len(kept)} / 剔除 {len(dropped)} 笔"
          f"（被剔除合计收益 {dropped['return_pct'].sum():+.1f}pp，"
          f"均值 {dropped['return_pct'].mean():+.2f}%/笔）")

    out = HERE / f"gates_decile{thr}"
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(METRICS_CLI),
                        "--trades", str(HERE / f"A_v2_decile{thr}.csv"),
                        "--market", str(PANEL), "--out-dir", str(out),
                        "--initial-cash", "1000000", "--notional", "100000",
                        "--cost-bps", "15"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-500:] + r.stderr[-500:])

base = PROJ / "02_strategy_iteration/strategy_006/ab_tests/A_v2/backtest_logs/metrics_from_trades.csv"
rows = {"A_v2 原版": pd.read_csv(base).iloc[0],
        f"decile≥4": pd.read_csv(HERE / "gates_decile4/metrics_from_trades.csv").iloc[0]}
cols = ["total_return", "annual_return", "sharpe", "max_drawdown", "n_trades",
        "win_rate_pct", "payoff", "avg_return_pct"]
cmp = pd.DataFrame(rows).T[cols]
print()
print(cmp.round(3).to_string())
cmp.round(4).to_csv(HERE / "update1_comparison.csv", encoding="utf-8-sig")
