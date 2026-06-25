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


# ====================================================================
# 公共函数（步骤 0/3/4，可被任意策略复用）
# ====================================================================

K_DATA_DB = PROJECT_ROOT / "data_cache" / "k_data.db"


def load_daily_klines(symbol, start_date=None, end_date=None):
    """【步骤0·公共】从 k_data.db 取日频 K 线（主力连续·后复权）。

    Returns:
        pd.DataFrame，列 date/open/close/high/low/vol/oi/adj_factor，按 date 升序。
    """
    sql = 'SELECT date,open,close,high,low,vol,oi,adj_factor FROM "1d_k_data" WHERE symbol=?'
    params = [symbol]
    if start_date:
        sql += " AND date >= ?"; params.append(start_date)
    if end_date:
        sql += " AND date <= ?"; params.append(end_date)
    sql += " ORDER BY date"
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    return df


def cross_positions(fast, slow):
    """【步骤1+2·公共】双线交叉仓位规则（翻仓制，首次信号后永远在仓）。

    - fast 上穿 slow（昨≤、今>）：满仓做多（+1）。无论之前是多/空/空仓 → 一律变 +1
    - fast 下穿 slow（昨≥、今<）：满仓做空（−1）。无论之前 → 一律变 −1
    - 无穿越日：仓位保持不变
    - 均线 warmup（NaN）期及首次信号前：空仓（0）

    Args:
        fast / slow: pd.Series，快/慢均线（同索引、同长）

    Returns:
        pd.Series，仓位 ∈ {+1, 0, −1}，仅在穿越日变化。
    """
    up = (fast > slow) & (fast.shift(1) <= slow.shift(1))     # 上穿
    dn = (fast < slow) & (fast.shift(1) >= slow.shift(1))     # 下穿
    pos = pd.Series(0, index=fast.index, dtype=int)
    cur = 0
    for i in range(len(fast)):
        if up.iloc[i]:
            cur = 1
        elif dn.iloc[i]:
            cur = -1
        pos.iloc[i] = cur
    return pos


def build_trade_records(positions, returns, dates=None):
    """【步骤3·公共】由仓位序列 + 收益序列生成交易记录。

    每笔交易 = 从开仓到平仓的一段。收益采用「持仓时累计、平仓结算」。

    Args:
        positions: pd.Series，每日仓位 ∈ {+1, 0, −1}
        returns:   pd.Series，每日标的价格收益（log 或 simple 均可，与累计口径一致）
        dates:     可选，交易日序列；None 用 positions.index

    Returns:
        list[dict]，每笔：entry_date / exit_date / direction / entry_price(累计收益基)
        / exit_price(累计收益) / pnl / bars
    """
    if dates is None:
        dates = positions.index
    trades = []
    in_pos = False
    entry_i = direction = None
    cum = 0.0
    strat_ret = (positions.shift(1, fill_value=0) * returns).fillna(0.0)

    for i in range(len(positions)):
        p = positions.iloc[i]
        prev = positions.iloc[i - 1] if i > 0 else 0
        # 累计当前持仓段收益
        if in_pos and p == direction:
            cum += strat_ret.iloc[i]
        # 平仓触发：仓位方向变化或归零
        if in_pos and (p != direction):
            trades.append({
                "entry_date": dates[entry_i], "exit_date": dates[i],
                "direction": "多" if direction == 1 else "空",
                "bars": i - entry_i, "pnl": cum,
            })
            in_pos = False
            cum = 0.0
        # 开新仓
        if not in_pos and p != 0 and p != prev:
            in_pos = True
            entry_i = i
            direction = p
    # 末笔未平仓则按最后一天结算
    if in_pos:
        trades.append({
            "entry_date": dates[entry_i], "exit_date": dates[len(positions) - 1],
            "direction": "多" if direction == 1 else "空",
            "bars": len(positions) - 1 - entry_i, "pnl": cum,
        })
    return trades


def perf_stats(returns, ann=252):
    """【步骤4·公共】由日频策略收益序列算绩效。

    Args:
        returns: pd.Series，日策略收益（持仓×标的收益）
        ann:     年化系数（日频=252）

    Returns:
        dict: ann_return / ann_vol / sharpe / max_dd / calmar / total_return /
              n_periods / win_rate(若有交易)
    """
    if returns.empty:
        return {}
    cum = (1 + returns).cumprod()
    total_ret = float(cum.iloc[-1] - 1)
    ann_ret = float(returns.mean() * ann)
    ann_vol = float(returns.std() * np.sqrt(ann))
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0
    peak = cum.expanding().max()
    dd = (cum / peak - 1).dropna()
    max_dd = float(dd.min()) if len(dd) else 0.0
    calmar = float(ann_ret / abs(max_dd)) if max_dd != 0 else 0.0
    return {
        "total_return": total_ret, "ann_return": ann_ret, "ann_vol": ann_vol,
        "sharpe": sharpe, "max_dd": max_dd, "calmar": calmar,
        "n_periods": len(returns),
    }


def plot_equity_curve(returns, title="策略净值曲线", out_name=None, trades=None):
    """【步骤4·公共】画净值 + 回撤曲线 HTML。

    Args:
        returns: 日策略收益 pd.Series
        title:   标题
        out_name: 文件名；None 自动命名
        trades:  可选，build_trade_records 的输出，叠在净值上标开/平仓点
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    cum = (1 + returns).cumprod()
    dd = cum / cum.expanding().max() - 1
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35],
                        subplot_titles=("净值曲线", "回撤"), vertical_spacing=0.06)
    fig.add_trace(go.Scatter(x=cum.index, y=cum.values, mode="lines", name="净值",
                             line=dict(color="steelblue", width=1)), row=1, col=1)
    if trades:
        for tr in trades:
            color = "#2ecc71" if tr["direction"] == "多" else "#e74c3c"
            fig.add_vline(x=tr["entry_date"], line_color=color, line_width=1, line_dash="dot",
                          opacity=0.6, row=1, col=1)
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", name="回撤",
                             line=dict(color="crimson", width=0.5),
                             fillcolor="rgba(220,20,60,0.15)"), row=2, col=1)
    fig.update_layout(title=title, template="plotly_white", height=650)
    fig.add_hline(y=1, line_color="gray", line_width=0.5, row=1, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=0.5, row=2, col=1)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / (out_name or "equity_curve.html")
    fig.write_html(str(out))
    print(f"[backtest] 净值图已输出: {out}")
    return str(out)


# ====================================================================
# HMA 双均线交叉策略（组合公共函数）
# ====================================================================

def hma_cross_backtest(symbol="hc", fast_n=10, slow_n=60,
                       start_date=None, end_date=None):
    """HMA(fast) / HMA(slow) 双均线交叉回测。

    规则：
      - HMA_fast 上穿 HMA_slow：空仓→满仓做多；多单不动；空单平仓→做多
      - HMA_fast 下穿 HMA_slow：空仓→满仓做空；多单平仓→做空；空单不动
      仓位 ∈ {+1, 0, −1}，无杠杆、无止损。

    Args:
        symbol:   品种代码（默认 hc）
        fast_n:   快线 HMA 周期（默认 10）
        slow_n:   慢线 HMA 周期（默认 60）

    Returns:
        dict: positions / strategy_returns / trades / perf 统计 + n_trades / fast_n / slow_n
    """
    from trend_following.indicators import hma

    df = load_daily_klines(symbol, start_date, end_date)
    if df.empty:
        print(f"[hma_cross] {symbol} 无数据")
        return None
    close = df["close"].astype(float)
    close.index = df["date"]   # 统一用 date 索引，避免后续相乘时索引对不齐
    fast = hma(close, fast_n)
    slow = hma(close, slow_n)

    pos = cross_positions(fast, slow)   # 已是 date 索引

    ret = np.log(close / close.shift(1))   # 日对数收益（date 索引）
    strat_ret = (pos.shift(1, fill_value=0) * ret).fillna(0.0)

    trades = build_trade_records(pos, ret, dates=df["date"].tolist())
    perf = perf_stats(strat_ret, ann=252)
    n_win = sum(1 for t in trades if t["pnl"] > 0)
    perf["win_rate"] = n_win / len(trades) if trades else 0.0

    result = {
        "symbol": symbol, "fast_n": fast_n, "slow_n": slow_n,
        "positions": pos, "strategy_returns": strat_ret,
        "trades": trades, "n_trades": len(trades), **perf,
    }
    print(f"[hma_cross] {symbol} HMA{fast_n}/{slow_n}: "
          f"年化={perf['ann_return']:.2%}, Sharpe={perf['sharpe']:.2f}, "
          f"MaxDD={perf['max_dd']:.2%}, {len(trades)}笔(胜率{perf['win_rate']:.0%})")
    return result


def ema_cross_backtest(symbol="hc", fast_n=30, slow_n=120,
                       start_date=None, end_date=None):
    """EMA(fast) / EMA(slow) 双均线交叉回测（规则同 hma_cross_backtest，仅指标换 EMA）。

      - EMA_fast 上穿 EMA_slow → 满仓做多（+1）
      - EMA_fast 下穿 EMA_slow → 满仓做空（−1）
      首次信号后永远在仓；仓位 ∈ {+1, 0, −1}。

    Args:
        symbol:   品种代码
        fast_n:   快线 EMA 周期（默认 30）
        slow_n:   慢线 EMA 周期（默认 120）

    Returns:
        dict: 同 hma_cross_backtest，但键名 indicator='EMA'。
    """
    from trend_following.indicators import ema

    df = load_daily_klines(symbol, start_date, end_date)
    if df.empty:
        print(f"[ema_cross] {symbol} 无数据")
        return None
    close = df["close"].astype(float)
    close.index = df["date"]
    fast = ema(close, fast_n)
    slow = ema(close, slow_n)

    pos = cross_positions(fast, slow)
    ret = np.log(close / close.shift(1))
    strat_ret = (pos.shift(1, fill_value=0) * ret).fillna(0.0)

    trades = build_trade_records(pos, ret, dates=df["date"].tolist())
    perf = perf_stats(strat_ret, ann=252)
    n_win = sum(1 for t in trades if t["pnl"] > 0)
    perf["win_rate"] = n_win / len(trades) if trades else 0.0

    result = {
        "symbol": symbol, "indicator": "EMA", "fast_n": fast_n, "slow_n": slow_n,
        "positions": pos, "strategy_returns": strat_ret,
        "trades": trades, "n_trades": len(trades), **perf,
    }
    print(f"[ema_cross] {symbol} EMA{fast_n}/{slow_n}: "
          f"年化={perf['ann_return']:.2%}, Sharpe={perf['sharpe']:.2f}, "
          f"MaxDD={perf['max_dd']:.2%}, {len(trades)}笔(胜率{perf['win_rate']:.0%})")
    return result


def kama_hma_cross_backtest(symbol="hc", kama_n=8, kama_fast=2, kama_slow=30,
                            hma_n=120, start_date=None, end_date=None):
    """KAMA(快线) 上/下穿 HMA(慢线) 的混合双线交叉回测。

      - KAMA 上穿 HMA → 满仓做多（+1）
      - KAMA 下穿 HMA → 满仓做空（−1）
    KAMA 自适应（趋势段加速、震荡段减速）做快线，HMA 低延迟做慢线（趋势滤波）。

    Args:
        symbol:    品种代码
        kama_n:    KAMA 效率比窗口（默认 8）
        kama_fast: KAMA 最快周期（默认 2）
        kama_slow: KAMA 最慢周期（默认 30）
        hma_n:     HMA 慢线周期（默认 120）

    Returns:
        dict: 同 hma_cross_backtest，含 indicator='KAMA/HMA' + kama 参数。
    """
    from trend_following.indicators import kama, hma

    df = load_daily_klines(symbol, start_date, end_date)
    if df.empty:
        print(f"[kama_hma_cross] {symbol} 无数据")
        return None
    close = df["close"].astype(float)
    close.index = df["date"]
    fast = kama(close, n=kama_n, fast=kama_fast, slow=kama_slow)
    slow = hma(close, hma_n)

    pos = cross_positions(fast, slow)
    ret = np.log(close / close.shift(1))
    strat_ret = (pos.shift(1, fill_value=0) * ret).fillna(0.0)

    trades = build_trade_records(pos, ret, dates=df["date"].tolist())
    perf = perf_stats(strat_ret, ann=252)
    n_win = sum(1 for t in trades if t["pnl"] > 0)
    perf["win_rate"] = n_win / len(trades) if trades else 0.0

    result = {
        "symbol": symbol, "indicator": "KAMA/HMA",
        "kama_n": kama_n, "kama_fast": kama_fast, "kama_slow": kama_slow, "hma_n": hma_n,
        "positions": pos, "strategy_returns": strat_ret,
        "trades": trades, "n_trades": len(trades), **perf,
    }
    print(f"[kama_hma_cross] {symbol} KAMA({kama_n},{kama_fast},{kama_slow})/HMA{hma_n}: "
          f"年化={perf['ann_return']:.2%}, Sharpe={perf['sharpe']:.2f}, "
          f"MaxDD={perf['max_dd']:.2%}, {len(trades)}笔(胜率{perf['win_rate']:.0%})")
    return result


def hma_kama_cross_backtest(symbol="hc", hma_n=30, kama_n=32, kama_fast=8, kama_slow=120,
                            start_date=None, end_date=None):
    """HMA(快线) 上/下穿 KAMA(慢线) 的混合双线交叉回测。

      - HMA 上穿 KAMA → 满仓做多（+1）
      - HMA 下穿 KAMA → 满仓做空（−1）
    HMA 低延迟做快线（敏感发信号），KAMA 自适应做慢线（稳定趋势滤波）。

    Args:
        symbol:    品种代码
        hma_n:     HMA 快线周期（默认 30）
        kama_n:    KAMA 效率比窗口（默认 32）
        kama_fast: KAMA 最快周期（默认 8）
        kama_slow: KAMA 最慢周期（默认 120）

    Returns:
        dict: 同 hma_cross_backtest，含 indicator='HMA/KAMA' + 参数。
    """
    from trend_following.indicators import hma, kama

    df = load_daily_klines(symbol, start_date, end_date)
    if df.empty:
        print(f"[hma_kama_cross] {symbol} 无数据")
        return None
    close = df["close"].astype(float)
    close.index = df["date"]
    fast = hma(close, hma_n)
    slow = kama(close, n=kama_n, fast=kama_fast, slow=kama_slow)

    pos = cross_positions(fast, slow)
    ret = np.log(close / close.shift(1))
    strat_ret = (pos.shift(1, fill_value=0) * ret).fillna(0.0)

    trades = build_trade_records(pos, ret, dates=df["date"].tolist())
    perf = perf_stats(strat_ret, ann=252)
    n_win = sum(1 for t in trades if t["pnl"] > 0)
    perf["win_rate"] = n_win / len(trades) if trades else 0.0

    result = {
        "symbol": symbol, "indicator": "HMA/KAMA",
        "hma_n": hma_n, "kama_n": kama_n, "kama_fast": kama_fast, "kama_slow": kama_slow,
        "positions": pos, "strategy_returns": strat_ret,
        "trades": trades, "n_trades": len(trades), **perf,
    }
    print(f"[hma_kama_cross] {symbol} HMA{hma_n}/KAMA({kama_n},{kama_fast},{kama_slow}): "
          f"年化={perf['ann_return']:.2%}, Sharpe={perf['sharpe']:.2f}, "
          f"MaxDD={perf['max_dd']:.2%}, {len(trades)}笔(胜率{perf['win_rate']:.0%})")
    return result



if __name__ == "__main__":
    r = hma_cross_backtest("hc", fast_n=10, slow_n=60)
    if r:
        plot_equity_curve(r["strategy_returns"],
                          title=f"HMA 双均线回测  hc·HMA{r['fast_n']}/{r['slow_n']}  "
                                f"年化={r['ann_return']:.2%} Sharpe={r['sharpe']:.2f} "
                                f"MaxDD={r['max_dd']:.2%}  {r['n_trades']}笔",
                          trades=r["trades"])
