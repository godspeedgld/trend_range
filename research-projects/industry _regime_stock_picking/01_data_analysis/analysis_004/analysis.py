"""analysis_004 — 随机对照：选股层复合分换成【随机分】，其余脚手架全同基线，跑 20 个种子。

四步计划第 2 步（承接 analysis_003 标尺）：判定当前口径下**选股层有没有 alpha**。
analysis_003 已证复合分 IC=0.060/t=7.5（信息存在）；本分析回答"这层信息**落到组合绩效**上
是否显著优于随机排序"——旧口径曾得「≈随机（50 分位）」，本分析在**当前口径**重做。

设计（唯一变量 = 打分）：
  · 行业层 / 稳定性过滤：直接复用 weekly_plan.parquet（与基线逐周相同）
  · 候选池 / 行业内选 2 / 缓冲 / 1/vol 权重 / 成本 / 引擎：全同基线（build_random_targets.py）
  · 复合分 → 每周 uniform 随机分（种子 1001~1020，可复现）
  · 引擎：local_weight_backtest.run_weight_backtest **进程内调用**（行情只读一次，省 20 次重读）
  · 基准：strategy_002/backtest_strategy_baseline（云端原版，净值 3.600x / Sharpe 0.904）

产物：runs_summary.csv + result_view.html（分布直方图 + 基准线 + 汇总表）
用法：python analysis.py [--runs 20] [--seeds 1001]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SHARED = PROJ / "shared"
REPO = PROJ.parents[1]
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(REPO / ".claude/skills/skill-research-assistant/scripts"))

from build_random_targets import build_random                      # noqa: E402
from expand_targets_daily import expand_to_daily                   # noqa: E402
from local_weight_backtest import PERIODS, WeightBacktestConfig, run_weight_backtest  # noqa: E402

MARKET = SHARED / "_cache" / "engine_market_weekly_indpre_rawpx.parquet"
BASELINE = PROJ / "02_strategy_iteration/strategy_002/backtest_strategy_baseline/backtest_logs/performance_metrics.csv"
N_RUNS, SEED0 = 20, 1001


def run_one(seed: int, market: pd.DataFrame, cal: pd.DatetimeIndex, cfg, period) -> dict:
    t0 = time.time()
    tg = build_random(seed).rename(columns={"signal_date": "date", "symbol": "instrument"})
    daily_tg = expand_to_daily(tg[["date", "instrument", "weight"]], cal)
    daily_tg = daily_tg.rename(columns={"instrument": "symbol"})   # 引擎进程内口径用 symbol
    daily, trades, _ = run_weight_backtest(market, daily_tg, cfg, period)
    nav = daily.set_index("date")["nav"]
    ret = nav.pct_change().dropna()
    sd = ret.std()
    return {"seed": seed,
            "final_nav": float(nav.iloc[-1]),
            "total_return": float(nav.iloc[-1] - 1),
            "annual_return": float(nav.iloc[-1] ** (252 / len(ret)) - 1),
            "sharpe": float(ret.mean() / sd * np.sqrt(252)) if sd else np.nan,
            "max_drawdown": float(daily["drawdown"].min()),
            "n_trades": int(len(trades)),
            "secs": round(time.time() - t0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=N_RUNS)
    ap.add_argument("--seeds", type=int, default=SEED0)
    a = ap.parse_args()

    market = pd.read_parquet(MARKET)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(market["date"]).unique()))
    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = PERIODS["trading_days"](1)
    print(f"行情 {len(market):,} 行 / {len(cal)} 交易日；随机对照 {a.runs} 个种子（{a.seeds} 起）")

    rows = [run_one(a.seeds + k, market, cal, cfg, period) for k in range(a.runs)]
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "runs_summary.csv", index=False)

    base = pd.read_csv(BASELINE, encoding="utf-8-sig").iloc[0]
    b = {"final_nav": base.final_nav, "total_return": base.total_return,
         "annual_return": base.annual_return, "sharpe": base.sharpe,
         "max_drawdown": base.max_drawdown, "n_trades": base.n_trades}

    print("\n── 随机对照分布 vs 基线 ──")
    print(f"{'指标':<14}{'基线':>10}{'随机均值':>10}{'随机中位':>10}{'P5':>10}{'P95':>10}{'基线分位':>9}")
    from scipy import stats as sps
    for k, label in [("total_return", "总收益"), ("annual_return", "年化"),
                     ("sharpe", "Sharpe"), ("max_drawdown", "回撤"), ("n_trades", "成交笔数")]:
        v = df[k].values
        pct = sps.percentileofscore(v, b[k], kind="mean")
        print(f"{label:<14}{b[k]:>10.4f}{v.mean():>10.4f}{np.median(v):>10.4f}"
              f"{np.percentile(v,5):>10.4f}{np.percentile(v,95):>10.4f}{pct:>8.0f}%")

    # ── HTML（自包含）──
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    def _hist(col, title):
        f = go.Figure()
        f.add_histogram(x=df[col], name="随机对照(20)", nbinsx=12, marker_color="#95a5a6")
        f.add_vline(x=b[col], line_color="#c0392b", line_width=2,
                    annotation_text=f"基线 {b[col]:.3f}", annotation_position="top")
        f.update_layout(title=title, template="plotly_white", height=420, bargap=.1)
        return f

    fig_hist = make_subplots(rows=1, cols=2, subplot_titles=("总收益分布", "Sharpe 分布"))
    fig_hist.add_histogram(x=df["total_return"], nbinsx=12, marker_color="#95a5a6",
                           name="随机", row=1, col=1)
    fig_hist.add_histogram(x=df["sharpe"], nbinsx=12, marker_color="#95a5a6",
                           name="随机", row=1, col=2)
    fig_hist.add_vline(x=b["total_return"], line_color="#c0392b", line_width=2, row=1, col=1)
    fig_hist.add_vline(x=b["sharpe"], line_color="#c0392b", line_width=2, row=1, col=2)
    fig_hist.update_layout(title="随机对照（20 种子） vs 基线（红线）", template="plotly_white",
                           height=460, showlegend=False)

    fig_sc = go.Figure()
    fig_sc.add_scatter(x=df["n_trades"], y=df["total_return"], mode="markers", name="随机",
                       marker=dict(color="#7f8c8d", size=9))
    fig_sc.add_scatter(x=[b["n_trades"]], y=[b["total_return"]], mode="markers", name="基线",
                       marker=dict(color="#c0392b", size=14, symbol="star"))
    fig_sc.update_layout(title="成交笔数 × 总收益（星 = 基线）", template="plotly_white", height=440)

    d = df.round(4).reset_index(drop=True)
    tbl_runs = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8"),
                                  cells=dict(values=[d[c] for c in d.columns], height=24)))
    tbl_runs.update_layout(title="20 次随机对照明细", height=200 + 26 * len(d))

    parts = ["<h2>analysis_004 — 随机对照：选股层复合分 → 随机分（20 种子，脚手架全同基线）</h2>",
             "<h3>随机对照明细</h3>" + tbl_runs.to_html(full_html=False, include_plotlyjs=True),
             "<h3>分布 vs 基线</h3>" + fig_hist.to_html(full_html=False, include_plotlyjs=False),
             "<h3>成交 × 收益</h3>" + fig_sc.to_html(full_html=False, include_plotlyjs=False)]
    (HERE / "result_view.html").write_text(
        '<html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
        + "".join(parts) + "</body></html>", encoding="utf-8")
    print(f"\n图表已写 {HERE / 'result_view.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
