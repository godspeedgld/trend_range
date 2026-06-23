"""trend_following.backtest — TSMOM 趋势跟踪策略回测。

基于 tsmom_regression 的 z_t = r_t/σ_{t-1} 作信号，vol-targeted 仓位，
计算策略收益及绩效指标。

用法:
    from trend_following.backtest import tsmom_backtest
    result = tsmom_backtest(period="mon", h=1)
    # result 含 strategy_returns, sharpe, max_dd 等
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from trend_following.check_trend_valid import _PERIOD_MAP, _PERIOD_VOL_COL, RETURNS_DB

# 结果输出
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"


def tsmom_backtest(period="mon", h=1, start_date=None, end_date=None,
                   symbols=None, min_years=2.0, return_col="log_return",
                   vol_target=0.20, top_frac=None):
    """TSMOM 趋势跟踪回测（时序 + 可选截面增强）。

    每期 t，计算信号 z_t = r_t/σ_{t-1}。仓位权重 w_t 正比于 z_t 的符号和幅度，
    同时 vol-target 到年度波动率 vol_target。每期策略收益 = Σ w_{t-1} × r_t。

    Args:
        period:     "1d" / "week" / "mon"
        h:          信号滞后阶数（z_{t-h} 用于预测 r_t）
        start_date: 样本起始日
        end_date:   样本结束日
        symbols:    品种集合（None=全部）
        min_years:  最低上市年数
        return_col: 收益列 "log_return" / "simple_return"
        vol_target: 年度波动率目标（默认 20%）
        top_frac:   截面筛选比例（None=全品种做时序；0.33=只看 z 排前1/3做多+后1/3做空）

    Returns:
        dict: period, h, n_periods, n_symbols, total_return, ann_return,
              ann_vol, sharpe, max_dd, calmar, strategy_returns(DataFrame)
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}")
    table = _PERIOD_MAP[period][1]
    vol_col = _PERIOD_VOL_COL[period]

    if not RETURNS_DB.exists():
        print(f"[backtest] 无收益率库 {RETURNS_DB}")
        return None

    # ---------- 取数 ----------
    sql = (f'SELECT datetime, symbol, "{return_col}" AS r, "{vol_col}" AS vol '
           f'FROM "{table}" '
           f'WHERE "{return_col}" IS NOT NULL AND "{vol_col}" IS NOT NULL')
    params = []
    if start_date:
        sql += " AND datetime >= ?"; params.append(f"{start_date} 00:00:00")
    if end_date:
        sql += " AND datetime <= ?"; params.append(f"{end_date} 23:59:59")
    if symbols is not None:
        syms = list(symbols)
        if not syms:
            return None
        ph = ",".join("?" * len(syms))
        sql += f" AND symbol IN ({ph})"; params.extend(str(s) for s in syms)
    if min_years is not None:
        bpy = {"1d": 252, "week": 52, "mon": 12}[period]
        sql += (f' AND symbol IN (SELECT symbol FROM "{table}" '
                f'GROUP BY symbol HAVING COUNT(*) >= {int(min_years * bpy)})')

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(sql + " ORDER BY datetime", conn, params=params)
    finally:
        conn.close()
    if df.empty:
        print("[backtest] 无数据")
        return None

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values(["symbol", "datetime"]).reset_index(drop=True)

    # ---------- 信号 z_t = r_t / σ_{t-1} ----------
    df["z"] = (df["r"].astype(float) / df.groupby("symbol")["vol"].shift(1))
    df["z"] = df["z"].replace([np.inf, -np.inf], np.nan)

    # 用 t-h 时刻的 z 预测 t 时刻（信号）
    df["signal"] = df.groupby("symbol")["z"].shift(h)

    # 波动率目标化：权重 w = signal × vol_target / σ_{t-1}，之后截面归一
    df["w_raw"] = df["signal"] * vol_target / df.groupby("symbol")["vol"].shift(1)

    v = df.dropna(subset=["r", "signal", "w_raw"]).copy()
    v = v[np.isfinite(v["r"]) & np.isfinite(v["w_raw"])]
    if v.empty:
        print("[backtest] 无有效观测")
        return None

    # ---------- 截面筛选（可选） ----------
    if top_frac is not None and top_frac > 0 and top_frac < 1:
        def _select(grp):
            n = max(1, int(len(grp) * top_frac))
            grp = grp.copy()
            grp["w_raw"] = 0.0
            top = grp.nlargest(n, "signal").index
            bot = grp.nsmallest(n, "signal").index
            grp.loc[top, "w_raw"] = 1.0
            grp.loc[bot, "w_raw"] = -1.0
            return grp
        v = v.groupby("datetime", group_keys=False).apply(_select)
        v["w_raw"] = v["w_raw"] * vol_target / v["vol"]

    # ---------- 按时间归一化 ----------
    w_sum = v.groupby("datetime")["w_raw"].transform(lambda x: np.abs(x).sum())
    v["weight"] = v["w_raw"] / w_sum.replace(0, np.nan)

    # ---------- 策略收益 ----------
    v["pnl"] = v["r"] * v["weight"].shift(1, fill_value=0)
    v["pnl"] = v["pnl"].fillna(0.0)

    # 每日策略收益 = Σ 各品种 pnl
    sr = v.groupby("datetime")["pnl"].sum().sort_index()
    sr = sr[sr != 0]  # 去掉未建仓期

    if sr.empty:
        print("[backtest] 策略收益全为零")
        return None

    # ---------- 绩效 ----------
    ann = {"1d": 252, "week": 52, "mon": 12}[period]
    cum = (1 + sr).cumprod()
    total_ret = float(cum.iloc[-1] - 1) if len(cum) else 0.0
    ann_ret = float(sr.mean() * ann)
    ann_vol = float(sr.std() * np.sqrt(ann))
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0
    peak = cum.expanding().max()
    dd = (cum / peak - 1).dropna()
    max_dd = float(dd.min()) if len(dd) else 0.0
    calmar = float(ann_ret / abs(max_dd)) if max_dd != 0 else 0.0

    result = {
        "period": period, "h": h, "vol_target": vol_target, "top_frac": top_frac,
        "n_periods": len(sr), "n_symbols": int(v["symbol"].nunique()),
        "total_return": total_ret, "ann_return": ann_ret, "ann_vol": ann_vol,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "strategy_returns": sr,
    }

    print(f"[backtest] {period} h={h}: 年化收益={ann_ret:.2%}, 年化波动={ann_vol:.2%}, "
          f"Sharpe={sharpe:.2f}, MaxDD={max_dd:.2%}, Calmar={calmar:.2f}, "
          f"n={len(sr)}期 x {result['n_symbols']}品")

    return result


def backtest_report(result, out_name=None):
    """回测结果可视化：净值曲线 + 回撤曲线 + 绩效表，输出 HTML。"""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    sr = result["strategy_returns"]
    if sr.empty:
        return None
    cum = (1 + sr).cumprod()
    dd = cum / cum.expanding().max() - 1

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.65, 0.35],
                        subplot_titles=("净值曲线", "回撤"),
                        vertical_spacing=0.06)

    fig.add_trace(go.Scatter(x=cum.index, y=cum.values, mode="lines",
                             name="净值", line=dict(color="steelblue", width=1)),
                  row=1, col=1)

    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy",
                             name="回撤", line=dict(color="crimson", width=0.5),
                             fillcolor="rgba(220,20,60,0.15)"),
                  row=2, col=1)

    info = (f"period={result['period']} h={result['h']} | "
            f"年化收益={result['ann_return']:.2%} 年化波动={result['ann_vol']:.2%} | "
            f"Sharpe={result['sharpe']:.2f} MaxDD={result['max_dd']:.2%} Calmar={result['calmar']:.2f} | "
            f"{result['n_periods']}期 x {result['n_symbols']}品")
    fig.update_layout(title=f"TSMOM 回测  {info}", template="plotly_white", height=650)
    fig.add_hline(y=1, line_color="gray", line_width=0.5, row=1, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=0.5, row=2, col=1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / (out_name or f"backtest_{result['period']}_h{result['h']}.html")
    fig.write_html(str(out))
    print(f"[backtest] 报告已输出: {out}")
    return str(out)


if __name__ == "__main__":
    r = tsmom_backtest(period="mon", h=1)
    if r:
        backtest_report(r)
