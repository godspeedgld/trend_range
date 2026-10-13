"""analysis_007 — 随机**因子集**对照：strategy_004 的 3 个新槽位换成库里随机因子，跑 20 个种子。

承 strategy_004（迭代四：六因子 = 方案 B）的**否结论**。它比基线差 11.9%（共同区间 3.173x vs 3.600x）。
但要小心一个解释陷阱：**基线四因子本来就是被优化过的一组，随便动它大概率也会变差。**
所以必须问：这 −11.9% 是**"方案 B 挑得差"**，还是**"在这个骨架上换任何 3 个因子都会差"**？

设计（唯一变量 = 3 个新槽位放哪个因子）：
  · 骨架固定 = [turn_ratio, px_ma20, **?1**, liq_amount, **?2**, **?3**]（与 strategy_004 的 b6 逐项对齐）
  · 三个随机槽从**库 512 因子**里随机抽（剔除方案 B 的 R076/R221/R222 本身），每个用 analysis_005
    扫描出的**该因子最优方向**（与当初选中 R076/R221/R222 的口径一致 ⇒ 随机因子也拿"最好的一面"，更严）
  · 行业层 / 候选池 / 选股 / 缓冲 / 权重 / 成本 / 引擎 **全同 b6**（`shared/build_random_factor_targets.py`）
  · 种子 1001~1020（可复现）；引擎 `run_weight_backtest` **进程内调用**（行情只读一次）
  · 基准：共同区间（≥2017-05-12）—— 方案 B = strategy_004/backtest_strategy；基线 = …/backtest_strategy_baseline

产物：runs_summary.csv + result_view.html
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

from build_random_factor_targets import build_random_factor, load_pool   # noqa: E402
from expand_targets_daily import expand_to_daily                        # noqa: E402
from local_weight_backtest import PERIODS, WeightBacktestConfig, run_weight_backtest  # noqa: E402

MARKET = SHARED / "_cache" / "engine_market_weekly_indpre_rawpx.parquet"
CUT = pd.Timestamp("2017-05-12")        # 共同区间起点 = 基线首个满仓日
B6 = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy/backtest_logs"
BL = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy_baseline/backtest_logs"
N_RUNS, SEED0 = 20, 1001


def metrics_common(daily: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """★ 共同区间（≥CUT）指标 —— 全部由**逐日净值/成交**推算，口径与 strategy_004 报告一致。

    ★ 收益率在**全序列**上算 pct_change 后再按日期切 —— 否则「先切再 pct_change」会丢掉
      窗口首日（2017-05-12）那一天的收益（实测让 b6 从 3.173 变成 3.215）。
    """
    dt = pd.to_datetime(daily["date"]).to_numpy()
    ret_all = pd.Series(daily["nav"].to_numpy(dtype=float)).pct_change().to_numpy()
    ret = ret_all[dt >= CUT]
    ret = ret[~np.isnan(ret)]
    d = daily[dt >= CUT].reset_index(drop=True)
    n = len(ret)
    navf = float((1 + ret).prod())
    sd = ret.std(ddof=1)
    c = (1 + ret).cumprod()
    dd = float((c / np.maximum.accumulate(c) - 1).min())
    t = trades[pd.to_datetime(trades["date"]) >= CUT]
    return {"final_nav": navf, "total_return": navf - 1,
            "annual_return": navf ** (252 / n) - 1 if n else np.nan,
            "sharpe": float(ret.mean() / sd * np.sqrt(252)) if sd else np.nan,
            "max_drawdown": dd, "n_trades": int(len(t)), "n_days": n}


def read_ref(d: Path) -> dict:
    nav = pd.read_csv(d / "nav_from_trades.csv")
    tr = pd.read_csv(d / "trades.csv")
    return metrics_common(nav, tr)


def run_one(seed, market, cal, cfg, period, pool, dirs_map, panel_base) -> dict:
    t0 = time.time()
    tg, rnd3 = build_random_factor(seed, pool, dirs_map, panel_base)
    tg = tg.rename(columns={"signal_date": "date", "symbol": "instrument"})
    daily_tg = expand_to_daily(tg[["date", "instrument", "weight"]], cal)
    daily_tg = daily_tg.rename(columns={"instrument": "symbol"})
    daily, trades, _ = run_weight_backtest(market, daily_tg, cfg, period)
    m = metrics_common(daily, trades)
    return {"seed": seed, "rnd1": rnd3[0], "rnd2": rnd3[1], "rnd3": rnd3[2], **m,
            "secs": round(time.time() - t0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=N_RUNS)
    ap.add_argument("--seeds", type=int, default=SEED0)
    a = ap.parse_args()

    pool, dirs_map = load_pool()
    print(f"随机池 = 库因子 {len(pool)} 个（已剔除 R076/R221/R222）")
    market = pd.read_parquet(MARKET)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(market["date"]).unique()))
    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = PERIODS["trading_days"](1)
    panel_base = pd.read_parquet(SHARED / "_cache/signal_panel_weekly_indpre.parquet")
    print(f"行情 {len(market):,} 行 / {len(cal)} 交易日；随机对照 {a.runs} 个种子（{a.seeds} 起），"
          f"共同区间 ≥ {CUT.date()}")

    rows = [run_one(a.seeds + k, market, cal, cfg, period, pool, dirs_map, panel_base)
            for k in range(a.runs)]
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "runs_summary.csv", index=False, encoding="utf-8-sig")

    ref = {"方案B(6因子)": read_ref(B6), "基线(4因子)": read_ref(BL)}
    from scipy import stats as sps
    print("\n── 随机因子集分布 vs 方案B / 基线（★ 全部在共同区间）──")
    keys = [("final_nav", "净值"), ("annual_return", "年化"), ("sharpe", "Sharpe"),
            ("max_drawdown", "回撤"), ("n_trades", "成交")]
    hdr = f"{'指标':<8}{'方案B':>10}{'基线':>10}{'随机均值':>10}{'随机中位':>10}{'P5':>10}{'P95':>10}{'方案B分位':>10}"
    print(hdr)
    for k, lab in keys:
        v = df[k].values
        print(f"{lab:<8}{ref['方案B(6因子)'][k]:>10.4f}{ref['基线(4因子)'][k]:>10.4f}"
              f"{v.mean():>10.4f}{np.median(v):>10.4f}{np.percentile(v,5):>10.4f}"
              f"{np.percentile(v,95):>10.4f}{sps.percentileofscore(v, ref['方案B(6因子)'][k], kind='mean'):>9.0f}%")

    # ── HTML ──
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    d = df.round(4)
    tbl = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8"),
                             cells=dict(values=[d[c] for c in d.columns], height=24)))
    tbl.update_layout(title=f"{a.runs} 次随机因子集明细（明细含每次抽中的 3 个因子）",
                      height=200 + 26 * len(d))
    fig = make_subplots(rows=1, cols=2, subplot_titles=("净值分布", "Sharpe 分布"))
    for j, (col, _) in enumerate([("final_nav", "净值"), ("sharpe", "Sharpe")], start=1):
        fig.add_histogram(x=df[col], nbinsx=12, marker_color="#95a5a6", name="随机因子集", row=1, col=j)
        fig.add_vline(x=ref["方案B(6因子)"][col], line_color="#c0392b", line_width=2, row=1, col=j)
        fig.add_vline(x=ref["基线(4因子)"][col], line_color="#27ae60", line_width=2,
                      line_dash="dash", row=1, col=j)
    fig.update_layout(title=f"随机因子集（{a.runs} 种子）· 红=方案B · 绿虚线=基线（共同区间 ≥{CUT.date()}）",
                      template="plotly_white", height=460, showlegend=False)
    parts = [f"<h2>analysis_007 — 随机因子集对照（strategy_004 的 3 个新槽位随机化，{a.runs} 种子）</h2>",
             "<h3>明细</h3>" + tbl.to_html(full_html=False, include_plotlyjs=True),
             "<h3>分布</h3>" + fig.to_html(full_html=False, include_plotlyjs=False)]
    (HERE / "result_view.html").write_text(
        '<html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
        + "".join(parts) + "</body></html>", encoding="utf-8")
    print(f"\n图表已写 {HERE / 'result_view.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
