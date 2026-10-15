"""analysis_010 — A2 臂：随机行业对照（block bootstrap，20 种子）——行业层贡献量化。

四臂消融的最后一臂（用户 2026-10-15 定：只做 A2）：
  A0 基线        3.600x（行业真实 + 四因子 + 空仓过滤）
  A1 去空仓      2.369x（strategy_006，exposure≡1）
  A3 随机选股    中位 2.199x（analysis_004，20 种子）
  A2 随机行业    本分析 —— 真实切换时间表 + 随机 top3 + 真实四因子 + 空仓过滤

设计：`shared/build_random_industry_targets.py`（块自助法——只在真实 top3 切换点重抽
3 个随机行业，exposure 日程与基线逐周一致，构建后 assert）。
引擎：`run_weight_backtest` 进程内调用（行情只读一次）；指标全部 trades 口径、共同区间
≥2017-05-12（analysis_004/007 同款）。

用法：python analysis.py [--runs 20] [--seeds 1001]
产物：runs_summary.csv + result_view.html（records.md 手写）
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

from build_random_industry_targets import build_random_industry   # noqa: E402
from expand_targets_daily import expand_to_daily                  # noqa: E402
from local_weight_backtest import PERIODS, WeightBacktestConfig, run_weight_backtest  # noqa: E402

MARKET = SHARED / "_cache/engine_market_weekly_indpre_rawpx.parquet"
BL = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy_baseline/backtest_logs"
CUT = pd.Timestamp("2017-05-12")
N_RUNS, SEED0 = 20, 1001
A3_MED = 2.1988      # analysis_004 随机选股臂中位（共同区间，trades 口径）
A1_NAV = 2.3685      # strategy_006 去空仓臂（全窗口）

C_BASE, C_RND = "#2a78d6", "#eb6834"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


def metrics_common(daily: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """共同区间（≥CUT）指标 —— 全序列 pct_change 后再切（analysis_007 同款）。"""
    dt = pd.to_datetime(daily["date"]).to_numpy()
    ret_all = pd.Series(daily["nav"].to_numpy(dtype=float)).pct_change().to_numpy()
    ret = ret_all[dt >= CUT]
    ret = ret[~np.isnan(ret)]
    n = len(ret)
    navf = float((1 + ret).prod())
    sd = ret.std(ddof=1)
    c = (1 + ret).cumprod()
    dd = float((c / np.maximum.accumulate(c) - 1).min())
    t = trades[pd.to_datetime(trades["date"]) >= CUT]
    return {"final_nav": navf, "annual_return": navf ** (252 / n) - 1 if n else np.nan,
            "sharpe": float(ret.mean() / sd * np.sqrt(252)) if sd else np.nan,
            "max_drawdown": dd, "n_trades": int(len(t))}


def read_ref(d: Path) -> dict:
    nav = pd.read_csv(d / "nav_from_trades.csv")
    tr = pd.read_csv(d / "trades.csv")
    return metrics_common(nav, tr)


def run_one(seed, market, cal, cfg, period) -> dict:
    t0 = time.time()
    tg, chk = build_random_industry(seed)
    assert chk["exposure_mismatch_vs_plan"] == 0, f"exposure 日程与基线不一致: {chk}"
    tg = tg.rename(columns={"signal_date": "date", "symbol": "instrument"})
    daily_tg = expand_to_daily(tg[["date", "instrument", "weight"]], cal)
    daily_tg = daily_tg.rename(columns={"instrument": "symbol"})
    daily, trades, _ = run_weight_backtest(market, daily_tg, cfg, period)
    m = metrics_common(daily, trades)
    return {"seed": seed, **m, "n_switch": chk["n_switch"], "secs": round(time.time() - t0)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=N_RUNS)
    ap.add_argument("--seeds", type=int, default=SEED0)
    a = ap.parse_args()

    market = pd.read_parquet(MARKET)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(market["date"]).unique()))
    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = PERIODS["trading_days"](1)
    print(f"行情 {len(market):,} 行 / {len(cal)} 交易日；A2 随机行业 {a.runs} 种子"
          f"（{a.seeds} 起），共同区间 ≥ {CUT.date()}")

    rows = [run_one(a.seeds + k, market, cal, cfg, period) for k in range(a.runs)]
    df = pd.DataFrame(rows)
    df.to_csv(HERE / "runs_summary.csv", index=False, encoding="utf-8-sig")

    ref = read_ref(BL)      # A0 基线（共同区间 = 3.6001）
    from scipy import stats as sps
    print("\n── A2 随机行业分布 vs 基线（★ 共同区间，trades 口径）──")
    keys = [("final_nav", "净值"), ("annual_return", "年化"), ("sharpe", "Sharpe"),
            ("max_drawdown", "回撤"), ("n_trades", "成交")]
    for k, lab in keys:
        v = df[k].values
        print(f"{lab:<8} 基线 {ref[k]:>9.4f}  随机均值 {v.mean():>9.4f}  中位 {np.median(v):>9.4f}  "
              f"P5 {np.percentile(v,5):>9.4f}  P95 {np.percentile(v,95):>9.4f}  "
              f"基线分位 {sps.percentileofscore(v, ref[k], kind='mean'):>6.0f}%")
    med = float(np.median(df["final_nav"]))
    print(f"\n── 四臂消融表（净值）──")
    print(f"  A0 基线          3.6001")
    print(f"  A1 去空仓        {A1_NAV:.4f}  → 空仓贡献   {3.6001 - A1_NAV:+.3f}x")
    print(f"  A3 随机选股(中位) {A3_MED:.4f}  → 选股贡献   {3.6001 - A3_MED:+.3f}x")
    print(f"  A2 随机行业(中位) {med:.4f}  → 行业贡献   {3.6001 - med:+.3f}x")

    html = build_view(df, ref)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("完成。")
    return 0


def build_view(df: pd.DataFrame, ref: dict) -> str:
    import plotly.graph_objects as go
    LAY = dict(font=dict(family="Arial,'Microsoft YaHei',sans-serif", color=INK2, size=13),
               paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
               xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               hovermode="x unified", margin=dict(l=56, r=24, t=56, b=44), showlegend=True)

    f1 = go.Figure()
    f1.add_trace(go.Histogram(x=df["final_nav"], nbinsx=10, name="A2 随机行业",
                              marker_color=C_RND, opacity=0.8))
    f1.add_vline(x=ref["final_nav"], line=dict(color=C_BASE, width=2, dash="dash"),
                 annotation_text=f"A0 基线 {ref['final_nav']:.3f}", annotation_font_color=C_BASE)
    f1.add_vline(x=A3_MED, line=dict(color=MUTED, width=2, dash="dot"),
                 annotation_text=f"A3 随机选股中位 {A3_MED:.3f}", annotation_font_color=MUTED)
    f1.add_vline(x=A1_NAV, line=dict(color="#e34948", width=2, dash="dot"),
                 annotation_text=f"A1 去空仓 {A1_NAV:.3f}", annotation_font_color="#e34948")
    f1.update_layout(height=380, **{k: v for k, v in LAY.items() if k != "showlegend"},
                     showlegend=False,
                     title="图1 · A2 随机行业的净值分布（20 种子，共同区间）vs A0/A1/A3")
    f1.update_xaxes(title_text="净值")

    d = df.round(4)
    tbl = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8"),
                             cells=dict(values=[d[c] for c in d.columns], height=24)))
    tbl.update_layout(title="20 个种子明细", height=220 + 24 * len(d))

    arms = ["A0 基线", "A1 去空仓", "A3 随机选股(中位)", "A2 随机行业(中位)"]
    navs = [3.6001, A1_NAV, A3_MED, float(np.median(df["final_nav"]))]
    f2 = go.Figure(go.Bar(x=arms, y=navs,
                          marker_color=[C_BASE, "#e34948", MUTED, C_RND]))
    f2.update_layout(height=340, showlegend=False,
                     title="图2 · 四臂消融（净值；各差值=该层的条件贡献，其余层保持真实）")
    f2.update_yaxes(title_text="净值")

    parts = "".join(f"<div class='fig'>{f.to_html(full_html=False, include_plotlyjs=(i == 0))}</div>"
                    for i, f in enumerate([f1, f2, tbl]))
    css = f"""
    <style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      h2 {{ color:{INK}; }}
      .fig {{ margin:8px 0 28px 0; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_010 — A2 随机行业对照（block bootstrap，20 种子）</h2>{parts}</body></html>")


if __name__ == "__main__":
    raise SystemExit(main())
