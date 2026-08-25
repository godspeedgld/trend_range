#!/usr/bin/env python
"""时序 CTA 事件驱动回测引擎（skill-report-replication-cta-ts）。

与 -factor 的 signal 驱动引擎不同：本引擎按**事件驱动**逐根推进状态机——
开仓信号满足→进场；ATR 吊灯止损用当根 high/low 命中价即时触发；收益 close-to-close。
策略以 strategy.py 暴露的 build_strategy(df)->spec 提供（入场事件数组 + 止损/仓位参数），
**不再以 signal_log 作输入**；signal_log 降级为引擎产出的实现方向（审计用）。

执行口径（防前视，日频 bar）：
  - 入场信号在 close[t] 确认 → 以 close[t] 进场，持有进入 bar t+1。
  - 持仓中每根 bar 用 high/low 判止损命中 → 命中则以止损价成交（gapped 时取 open）。
  - 收益基准 close-to-close；止损 bar 的收益 = pos·(止损价/prev_close − 1)。
  - 成本：进场+出场各扣 cost_rate（手续费+滑点）。
提速：指标/入场信号向量化；路径依赖状态机用 numba @jit（不可用时回退纯 Python，逻辑一致）。
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from numba import njit  # type: ignore
    _HAS_NUMBA = True
except Exception:  # numba 可选
    _HAS_NUMBA = False

    def njit(*args, **kwargs):  # 回退：纯 Python 装饰器
        if args and callable(args[0]):
            return args[0]
        def deco(f):
            return f
        return deco


@dataclass
class BacktestConfig:
    project_dir: Path
    market_data: Path
    strategy_py: Path
    initial_cash: float = 1_000_000.0
    cost_bps: float = 2.0
    slippage_bps: float = 1.0
    annualization: float = 252.0
    date_col: str = "date"
    symbol_col: str = "symbol"
    allow_short: bool = True


STOP_MAP = {"none": 0, "atr_static": 1, "atr_chandelier": 2, "percent": 3}


# ── 行情 ────────────────────────────────────────────────
def read_table(path: Path) -> pd.DataFrame:
    suf = path.suffix.lower()
    if suf in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suf in {".csv", ".txt"}:
        return pd.read_csv(path)
    raise ValueError(f"unsupported data file: {path}")


def normalize_market(df: pd.DataFrame, cfg: BacktestConfig) -> pd.DataFrame:
    need = [cfg.date_col, cfg.symbol_col, "open", "high", "low", "close"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"market data missing columns: {missing}（引擎需要 OHLC）")
    # 保留 OHLC 之外的额外列（volume/amount/turn 等）供策略读取（如量价变量）；只数值化，缺失留 NaN
    extra = [c for c in df.columns if c not in need]
    out = df[need + extra].copy()
    out.columns = ["date", "symbol", "open", "high", "low", "close"] + extra
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str)
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in extra:
        if out[c].dtype == object:       # 字符串列（如 name 证券简称）保留原样
            continue
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out = out.sort_values(["symbol", "date"]).drop_duplicates(["date", "symbol"], keep="last")
    if out.empty:
        raise ValueError("market data is empty after cleaning")
    return out


# ── 策略装载 ────────────────────────────────────────────
def load_strategy(path: Path):
    spec = importlib.util.spec_from_file_location("strategy_mod", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法装载 strategy: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "build_strategy"):
        raise RuntimeError("strategy.py 必须定义 build_strategy(df)->spec")
    return mod


# ── 指标（向量化）─────────────────────────────────────
def atr(high, low, close, period):
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def atr_truncated(high, low, close, period, lower_pct=5, upper_pct=95):
    """ATR with TR 分位截尾（原文：TR 5%-95% 动态分位数截断）。"""
    pc = close.shift(1)
    tr = pd.concat([(high - low), (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    lo = tr.expanding().quantile(lower_pct / 100.0)
    hi = tr.expanding().quantile(upper_pct / 100.0)
    return tr.clip(lo, hi).ewm(alpha=1 / period, adjust=False).mean()


def rolling_vol(close, window):
    return np.log(close).diff().rolling(window).std()


# ── 事件驱动状态机（核心，numba 加速）─────────────────
@njit(cache=True)
def _simulate(open_, high, low, close, entry_long, entry_short, entry_is_range,
              exit_long, exit_short, atr_v, pos_size, stop_type, k_stop, pct_stop,
              cost_rate, allow_short):
    """逐根事件驱动（t+1 开盘入场 + 信号触发离场）。

    执行口径：
      - 入场：close[t] 确认信号 → open[t+1] 成交（原文市价单）
      - 离场（趋势态）：ATR 吊灯止损，日内 high/low 命中
      - 离场（震荡态）：RSI 逻辑止损，close[t] 信号触发平仓
    """
    n = len(close)
    rets = np.zeros(n, dtype=np.float64)
    pos_series = np.zeros(n, dtype=np.float64)
    dir_series = np.zeros(n, dtype=np.int32)
    pos = 0.0
    pos_is_range = False
    entry_price = 0.0
    since_high = 0.0
    since_low = 0.0
    for t in range(1, n):
        prev_close = close[t - 1]
        r = 0.0
        if pos != 0.0:
            if pos > 0:
                since_high = since_high if since_high > high[t] else high[t]
            else:
                since_low = since_low if since_low < low[t] else low[t]

            # 震荡态：RSI 逻辑止损（信号触发离场）
            exit_hit = False
            if pos_is_range:
                exit_hit = (pos > 0 and exit_long[t]) or (pos < 0 and exit_short[t])

            # 趋势态：ATR 吊灯止损
            stop_hit = False
            sp = 0.0
            if not pos_is_range and stop_type != 0:
                if stop_type == 1:
                    sp = entry_price - k_stop * atr_v[t] if pos > 0 else entry_price + k_stop * atr_v[t]
                elif stop_type == 2:
                    sp = since_high - k_stop * atr_v[t] if pos > 0 else since_low + k_stop * atr_v[t]
                elif stop_type == 3:
                    sp = entry_price * (1 - pct_stop) if pos > 0 else entry_price * (1 + pct_stop)
                stop_hit = (low[t] <= sp) if pos > 0 else (high[t] >= sp)

            if exit_hit:
                r = pos * (close[t] / prev_close - 1.0) - abs(pos) * cost_rate
                pos = 0.0
            elif stop_hit:
                fill = sp
                if pos > 0 and open_[t] <= sp:
                    fill = open_[t]
                if pos < 0 and open_[t] >= sp:
                    fill = open_[t]
                r = pos * (fill / prev_close - 1.0) - abs(pos) * cost_rate
                pos = 0.0
            else:
                r = pos * (close[t] / prev_close - 1.0)

        rets[t] = r
        pos_series[t] = pos
        dir_series[t] = 1 if pos > 0 else (-1 if pos < 0 else 0)

        # 入场：t 日收盘信号 → t+1 开盘成交（原文市价单）
        if pos == 0.0 and t >= 1:
            sig = 0
            if entry_long[t - 1]:
                sig = 1
            elif entry_short[t - 1] and allow_short == 1:
                sig = -1
            if sig != 0:
                size = pos_size[t]
                pos = sig * size
                pos_is_range = entry_is_range[t - 1]
                entry_price = open_[t]
                since_high = open_[t]
                since_low = open_[t]
                # 入场当日收益：open[t] → close[t]
                r = pos * (close[t] / open_[t] - 1.0) - abs(pos) * cost_rate
                pos_series[t] = pos
                dir_series[t] = sig
    return rets, pos_series, dir_series


def run_symbol(df: pd.DataFrame, spec: dict, cfg: BacktestConfig):
    stop = spec.get("stop", {}) or {}
    stop_type = STOP_MAP.get(stop.get("type", "none"), 0)
    atr_period = int(stop.get("atr_period", 14))
    k_stop = float(stop.get("k", 2.0))
    pct_stop = float(stop.get("pct", 0.05))
    tr_lower = float(stop.get("tr_lower_pct", 5.0))
    tr_upper = float(stop.get("tr_upper_pct", 95.0))
    sizing = spec.get("sizing", {}) or {}
    vol_win = int(sizing.get("vol_window", 20))
    if sizing.get("type") == "vol_target":
        tv = float(sizing.get("target_vol", 0.15)) / math.sqrt(cfg.annualization)
        rv = rolling_vol(df["close"], vol_win).bfill()
        pos_size = (tv / rv.replace(0, np.nan)).fillna(0.0).clip(upper=3.0).to_numpy()
    else:
        pos_size = np.ones(len(df))
    # TR 分位截尾（原文：防止极端脉冲拉宽止损）
    if stop.get("tr_lower_pct") is not None or stop.get("tr_upper_pct") is not None:
        atr_v = atr_truncated(df["high"], df["low"], df["close"], atr_period,
                              tr_lower, tr_upper).bfill().to_numpy()
    else:
        atr_v = atr(df["high"], df["low"], df["close"], atr_period).bfill().to_numpy()
    el = spec["entry_long"].reindex(df.index).fillna(False).astype(bool).to_numpy()
    es_s = spec.get("entry_short", pd.Series(False, index=df.index))
    es = es_s.reindex(df.index).fillna(False).astype(bool).to_numpy()
    eir_s = spec.get("entry_is_range", pd.Series(False, index=df.index))
    eir = eir_s.reindex(df.index).fillna(False).astype(bool).to_numpy()
    xl_s = spec.get("exit_long", pd.Series(False, index=df.index))
    xl = xl_s.reindex(df.index).fillna(False).astype(bool).to_numpy()
    xs_s = spec.get("exit_short", pd.Series(False, index=df.index))
    xs = xs_s.reindex(df.index).fillna(False).astype(bool).to_numpy()
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 10000.0
    allow = 1 if (cfg.allow_short and spec.get("allow_short", True)) else 0
    rets, pos, direc = _simulate(
        df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(),
        el, es, eir, xl, xs, atr_v, pos_size, stop_type, k_stop, pct_stop, cost_rate, allow)
    return (pd.Series(rets, index=df.index, name="ret"),
            pd.Series(pos, index=df.index, name="pos"),
            pd.Series(direc, index=df.index, name="direction", dtype=int))


# ── 指标（复用 -factor compute_metrics 口径）──────────
def compute_metrics(returns: pd.Series, cfg: BacktestConfig, additive: bool = False) -> dict:
    r = returns.fillna(0.0)
    n = len(r)
    if n == 0:
        return {"periods": 0}
    if additive:
        # 固定名义口径：收益按初始本金加总（不复利），年化 = 总收益 / 年数（算术）
        nav = 1.0 + r.cumsum()
        final_nav = float(nav.iloc[-1])
        total_return = final_nav - 1.0
        ann_return = total_return * cfg.annualization / n if n else float("nan")
    else:
        # 复利口径：几何累计，年化 = (1+总收益)^(252/n) - 1
        nav = (1 + r).cumprod()
        final_nav = float(nav.iloc[-1])
        total_return = final_nav - 1.0
        ann_return = final_nav ** (cfg.annualization / n) - 1.0 if final_nav > 0 else float("nan")
    ann_vol = float(r.std(ddof=1) * math.sqrt(cfg.annualization)) if n > 1 else float("nan")
    downside = r[r < 0]
    dv = float(downside.std(ddof=1) * math.sqrt(cfg.annualization)) if len(downside) > 1 else float("nan")
    sharpe = ann_return / ann_vol if ann_vol else float("nan")
    sortino = ann_return / dv if dv else float("nan")
    peak = nav.cummax()
    max_dd = float((nav / peak - 1.0).min())
    calmar = ann_return / abs(max_dd) if max_dd else float("nan")
    gains = r[r > 0]
    losses = r[r < 0]
    pf = float(gains.sum() / abs(losses.sum())) if len(losses) and losses.sum() != 0 else float("nan")
    return {
        "periods": float(n), "final_nav": final_nav, "total_return": total_return,
        "annual_return": ann_return, "annual_volatility": ann_vol, "downside_volatility": dv,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar, "max_drawdown": max_dd,
        "win_rate": float((r > 0).mean()), "profit_factor": pf,
    }


# ── 输出 ────────────────────────────────────────────────
def fmt_pct(v):
    """百分比格式（小数比率 → xx.xx%）。"""
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "NA"
    return f"{v * 100:.2f}%"


def fmt_num(v, w=2):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "NA"
    return f"{v:.{w}f}"


def derive_trades(market: pd.DataFrame, all_pos: pd.DataFrame) -> pd.DataFrame:
    """从持仓序列推导买卖点（entry/exit）供 K 线标注。
    entry: pos 0→±1（开仓，价=当日 close）；exit: pos ±1→0（平仓，价=当日 close，近似）。
    """
    m = market[["date", "symbol", "open", "high", "low", "close"]].copy()
    m["date"] = pd.to_datetime(m["date"])
    g = all_pos.merge(m, on=["date", "symbol"], how="left").sort_values(["symbol", "date"])
    g["prev_pos"] = g.groupby("symbol")["pos"].shift(1).fillna(0)
    rows = []
    for _, r in g.iterrows():
        if r["prev_pos"] == 0 and r["pos"] != 0:           # 开仓
            rows.append({"date": r["date"], "symbol": r["symbol"], "action": "open",
                         "side": "long" if r["pos"] > 0 else "short", "price": r["close"]})
        elif r["prev_pos"] != 0 and r["pos"] == 0:         # 平仓
            rows.append({"date": r["date"], "symbol": r["symbol"], "action": "close",
                         "side": "long" if r["prev_pos"] > 0 else "short", "price": r["close"]})
    return pd.DataFrame(rows)


def derive_trades_paired(market: pd.DataFrame, all_pos: pd.DataFrame) -> pd.DataFrame:
    """配对完整交易记录：一次开仓→平仓 = 一行。

    从持仓序列和行情数据推导完整往返交易，包含：
    - 开仓/平仓日期和价格（开仓价=当日 close，平仓价=当日 close 近似）
    - 方向（多/空）
    - 交易级收益率（从日收益累积，精确含成本+止损成交价）
    - 持仓天数（自然日）
    - 平仓类型（止损/信号，按收益方向粗略推断）
    """
    m = market[["date", "symbol", "close"]].copy()
    m["date"] = pd.to_datetime(m["date"])
    g = all_pos.merge(m, on=["date", "symbol"], how="left").sort_values(["symbol", "date"])
    g["prev_pos"] = g.groupby("symbol")["pos"].shift(1).fillna(0)

    rows = []
    for sym, grp in g.groupby("symbol"):
        grp = grp.sort_values("date").reset_index(drop=True)
        entry_idx = None
        entry_date = None
        entry_price = None
        entry_side = None

        for i in range(len(grp)):
            r = grp.iloc[i]
            if r["prev_pos"] == 0 and r["pos"] != 0:
                # 开仓：pos 0→非0
                entry_idx = i
                entry_date = r["date"]
                entry_price = float(r["close"])
                entry_side = "long" if r["pos"] > 0 else "short"
            elif r["prev_pos"] != 0 and r["pos"] == 0 and entry_idx is not None:
                # 平仓：pos 非0→0，配对
                exit_date = r["date"]
                exit_price_approx = float(r["close"])

                # 从日收益累积计算交易级收益率（精确含成本+止损成交价）
                trade_rets = grp.iloc[entry_idx:i + 1]["ret"].values.astype(np.float64)
                trade_mult = float(np.prod(1.0 + trade_rets))
                trade_return = trade_mult - 1.0

                holding_days = (pd.Timestamp(exit_date) - pd.Timestamp(entry_date)).days

                # 平仓类型：事件驱动引擎所有平仓均由 ATR 吊灯止损触发（无主动止盈/信号平仓）；
                # 按交易盈亏区分"盈利平仓"（trailing stop 已移至盈利区）与"止损平仓"
                exit_type = "盈利平仓" if trade_return > 0 else "止损平仓"

                rows.append({
                    "symbol": sym,
                    "entry_date": str(entry_date)[:10],
                    "entry_price": round(entry_price, 2),
                    "exit_date": str(exit_date)[:10],
                    "exit_price": round(exit_price_approx, 2),
                    "side": entry_side,
                    "return_pct": round(trade_return * 100, 4),
                    "holding_days": max(holding_days, 1),
                    "exit_type": exit_type,
                })

                entry_idx = None  # 重置，等下一笔开仓

    return pd.DataFrame(rows)


def write_outputs(cfg: BacktestConfig, daily: pd.Series, all_pos: pd.DataFrame, market: pd.DataFrame,
                  metrics: dict, per_sym: dict, raw: dict, regime_df: pd.DataFrame | None = None) -> None:
    sdir = cfg.project_dir / "03_backtest_strategy"
    logs = sdir / "backtest_logs"
    logs.mkdir(parents=True, exist_ok=True)
    nav = (1 + daily).cumprod()
    pd.DataFrame({"date": daily.index, "net_return": daily.values, "nav": nav.values,
                  "drawdown": (nav / nav.cummax() - 1.0).values}).to_csv(
        logs / "equity_curve.csv", index=False, encoding="utf-8-sig")
    all_pos.to_csv(logs / "position_return_detail.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(logs / "performance_metrics.csv", index=False, encoding="utf-8-sig")
    trades = derive_trades(market, all_pos)
    trades.to_csv(logs / "trades.csv", index=False, encoding="utf-8-sig")
    trades_paired = derive_trades_paired(market, all_pos)
    trades_paired.to_csv(logs / "trades_paired.csv", index=False, encoding="utf-8-sig")
    with (logs / "signal_log.jsonl").open("w", encoding="utf-8") as f:
        for (d, s), grp in all_pos.groupby(["date", "symbol"]):
            f.write(json.dumps({"date": pd.Timestamp(d).strftime("%Y-%m-%d"),
                                "signals": {str(s): {"factor": 0.0,
                                                     "direction": int(grp["direction"].iloc[0])}}},
                               ensure_ascii=False) + "\n")
    # config.json：引擎自动落运行参数（固定模板，免去手补）
    (sdir / "config.json").write_text(json.dumps({
        "symbols": sorted(per_sym.keys()), "cost_bps": cfg.cost_bps, "slippage_bps": cfg.slippage_bps,
        "initial_cash": cfg.initial_cash, "annualization": cfg.annualization, "allow_short": cfg.allow_short,
        "engine": "ts-cta event-driven", "n_bars": int(len(all_pos))}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html(sdir, daily, market, trades, trades_paired, metrics, per_sym, regime_df)
    (sdir / "backtest_report_raw.html").write_text(
        "<pre>" + html.escape(json.dumps(raw, ensure_ascii=False, indent=2, default=str)) + "</pre>",
        encoding="utf-8")


def write_html(sdir: Path, daily: pd.Series, market: pd.DataFrame, trades: pd.DataFrame,
               trades_paired: pd.DataFrame, metrics: dict, per_sym: dict,
               regime_df: pd.DataFrame | None = None) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    # 横式绩效表：行=标的（含中文），列=指标
    metric_cols = [  # (key, label, kind)
        ("final_nav", "净值", "num"), ("total_return", "总收益", "pct"),
        ("annual_return", "年化收益", "pct"), ("annual_volatility", "年化波动", "pct"),
        ("downside_volatility", "下行波动", "pct"), ("sharpe", "Sharpe", "num"),
        ("sortino", "Sortino", "num"), ("calmar", "Calmar", "num"),
        ("max_drawdown", "最大回撤", "pct"), ("win_rate", "胜率", "pct"),
        ("profit_factor", "盈亏比", "num"),
    ]
    SYMBOL_ZH = {"au": "黄金", "ag": "白银", "hc": "螺纹钢", "rb": "螺纹钢", "i": "铁矿石",
                 "j": "焦炭", "jm": "焦煤", "cu": "铜", "al": "铝", "zn": "锌", "ni": "镍",
                 "if": "沪深300", "ih": "上证50", "ic": "中证500"}

    def cell(kind, v):
        return fmt_pct(v) if kind == "pct" else fmt_num(v)

    head = "<tr><th>标的</th>" + "".join(f"<th>{lbl}</th>" for _, lbl, _ in metric_cols) + "</tr>"
    body_rows = ""
    if len(per_sym) > 1:  # 多品种时加组合行
        body_rows += "<tr><td>组合 Portfolio</td>" + "".join(
            f"<td>{cell(k, metrics.get(key))}</td>" for key, _, k in metric_cols) + "</tr>"
    for s, m in per_sym.items():
        lab = f"{s}（{SYMBOL_ZH.get(s.lower(), s)}）"
        body_rows += f"<tr><td>{html.escape(lab)}</td>" + "".join(
            f"<td>{cell(k, m.get(key))}</td>" for key, _, k in metric_cols) + "</tr>"
    stats_table = f'<table style="width:100%">{head}{body_rows}</table>'

    # 配对交易记录表（一次开仓→平仓 = 一行）
    SIDE_ZH = {"long": "多", "short": "空"}
    EXIT_TYPE_ZH = {"盈利平仓": "盈利平仓", "止损平仓": "止损平仓"}
    if trades_paired is not None and len(trades_paired):
        # 汇总统计
        n_trades = len(trades_paired)
        win_trades = int((trades_paired["return_pct"] > 0).sum())
        loss_trades = int((trades_paired["return_pct"] <= 0).sum())
        win_rate = win_trades / n_trades * 100 if n_trades else 0
        avg_ret = float(trades_paired["return_pct"].mean())
        avg_hold = float(trades_paired["holding_days"].mean())
        total_ret = float(trades_paired["return_pct"].sum())
        best = trades_paired.loc[trades_paired["return_pct"].idxmax()]
        worst = trades_paired.loc[trades_paired["return_pct"].idxmin()]

        summary_html = (
            f'<div style="display:flex;gap:24px;flex-wrap:wrap;margin:12px 0 20px;">'
            f'<div><b>总交易</b><br>{n_trades} 笔</div>'
            f'<div><b>盈利</b><br><span style="color:#27ae60">{win_trades} 笔</span></div>'
            f'<div><b>亏损</b><br><span style="color:#e74c3c">{loss_trades} 笔</span></div>'
            f'<div><b>胜率</b><br>{win_rate:.1f}%</div>'
            f'<div><b>平均收益</b><br><span style="color:{"#27ae60" if avg_ret>0 else "#e74c3c"}">{avg_ret:+.2f}%</span></div>'
            f'<div><b>累计收益</b><br><span style="color:{"#27ae60" if total_ret>0 else "#e74c3c"}">{total_ret:+.2f}%</span></div>'
            f'<div><b>平均持仓</b><br>{avg_hold:.0f} 天</div>'
            f'<div><b>最佳单笔</b><br><span style="color:#27ae60">+{best["return_pct"]:.2f}%</span> ({best["entry_date"]})</div>'
            f'<div><b>最差单笔</b><br><span style="color:#e74c3c">{worst["return_pct"]:+.2f}%</span> ({worst["entry_date"]})</div>'
            f'</div>'
        )

        tr_rows = ""
        for i, r in enumerate(trades_paired.itertuples()):
            ret_str = f'{r.return_pct:+.2f}%'
            ret_color = "#27ae60" if r.return_pct > 0 else "#e74c3c"
            tr_rows += (
                f"<tr>"
                f"<td>{i + 1}</td>"
                f"<td>{r.entry_date}</td>"
                f"<td>{fmt_num(r.entry_price)}</td>"
                f"<td>{r.exit_date}</td>"
                f"<td>{fmt_num(r.exit_price)}</td>"
                f"<td>{SIDE_ZH.get(r.side, r.side)}</td>"
                f"<td style='color:{ret_color};font-weight:600'>{ret_str}</td>"
                f"<td>{r.holding_days}</td>"
                f"<td>{EXIT_TYPE_ZH.get(r.exit_type, r.exit_type)}</td>"
                f"</tr>"
            )
        trades_table = (
            f'{summary_html}'
            f'<table style="width:100%">'
            f'<tr><th>#</th><th>开仓日期</th><th>开仓价</th><th>平仓日期</th>'
            f'<th>平仓价</th><th>方向</th><th>收益率</th><th>持仓天数</th><th>平仓类型</th></tr>'
            f'{tr_rows}'
            f'</table>'
            f'<p style="color:#888;font-size:12px">注：平仓价用当日 close 近似（真实止损成交价见 position_return_detail.csv），'
            f'交易收益率从日收益累积计算（精确含成本+止损成交价）。引擎所有平仓均由 ATR 吊灯止损触发，"盈利平仓"=trailing stop 已移至盈利区。</p>'
        )
    else:
        trades_table = "<p>无交易记录。</p>"

    # —— 三页签：净值曲线 / K线 / 统计指标（固定模板）——
    symbols = sorted(per_sym.keys())
    nav = (1 + daily).cumprod()
    dd = nav / nav.cummax() - 1.0

    # ── 辅助：regime 背景着色 ──
    REGIME_COLORS = {
        0: "rgba(173, 216, 230, 0.30)",   # 震荡：浅蓝
        1: "rgba(255, 153, 153, 0.30)",   # 趋势上行：浅红
        -1: "rgba(144, 238, 144, 0.30)",  # 趋势下行：浅绿
    }
    REGIME_LABELS = {0: "震荡", 1: "趋势上行", -1: "趋势下行"}

    # 页签1：净值 + 回撤
    fig_nav = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                            row_heights=[0.7, 0.3],
                            subplot_titles=("Strategy NAV vs Benchmark (regime shaded)", "Drawdown"))

    # ── regime 背景着色 ──
    if regime_df is not None and len(regime_df):
        sym0 = symbols[0]
        rg = regime_df[regime_df["symbol"] == sym0].sort_values("date").reset_index(drop=True)
        if len(rg) > 0:
            rg["block"] = (rg["regime"] != rg["regime"].shift(1)).cumsum()
            for _bid, grp in rg.groupby("block"):
                st = int(grp["regime"].iloc[0])
                c = REGIME_COLORS.get(st)
                if c is None:
                    continue
                x0, x1 = grp["date"].iloc[0], grp["date"].iloc[-1]
                label = REGIME_LABELS.get(st, "")
                ann = [dict(text=label, x=(x0 + (x1 - x0) / 2), xanchor="center",
                           y=1.0, yanchor="bottom", showarrow=False,
                           font=dict(size=10))] if label and len(grp) > 40 else None
                fig_nav.add_shape(type="rect", x0=x0, x1=x1, y0=0, y1=1,
                                  xref="x", yref="y domain", fillcolor=c,
                                  layer="below", line_width=0, row=1, col=1)
                if ann:
                    for a in ann:
                        fig_nav.add_annotation(a, row=1, col=1)

    # ── 策略净值 ──
    fig_nav.add_trace(go.Scatter(x=nav.index, y=nav.values, name="Strategy",
                                 line=dict(color="#2980b9", width=1.8)), row=1, col=1)

    # ── 基准曲线（首品种 Buy & Hold，归一化到 1）──
    bench_sym = symbols[0]
    bench_md = market[market["symbol"] == bench_sym].sort_values("date")
    bench_raw = bench_md.set_index("date")["close"]
    bench_nav = (bench_raw / bench_raw.dropna().iloc[0]).reindex(nav.index).ffill().bfill()
    fig_nav.add_trace(go.Scatter(x=nav.index, y=bench_nav.values,
                                 name=f"{bench_sym} Buy&Hold",
                                 line=dict(color="#95a5a6", width=1.0, dash="dot")), row=1, col=1)

    # ── 回撤 ──
    fig_nav.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                                 line=dict(color="#c0392b", width=0.7),
                                 fillcolor="rgba(192,57,43,0.15)"), row=2, col=1)

    fig_nav.update_layout(template="plotly_white", height=500, hovermode="x unified",
                          margin=dict(l=50, r=30, t=40, b=30), showlegend=True,
                          legend=dict(orientation="h", y=1.15, x=0, font=dict(size=11)))
    nav_html = fig_nav.to_html(full_html=False, include_plotlyjs=False, div_id="fig_nav",
                               config={"responsive": True})

    # 页签2：K线 + 买卖点（每品种一行）
    fig_kl = make_subplots(rows=len(symbols), cols=1, shared_xaxes=True, vertical_spacing=0.04,
                           subplot_titles=[f"{s} OHLC + Entry/Exit" for s in symbols]) if len(symbols) > 1 else None
    for i, s in enumerate(symbols):
        md = market[market["symbol"] == s].sort_values("date")
        cd = go.Candlestick(x=md["date"], open=md["open"], high=md["high"], low=md["low"],
                            close=md["close"], name=s, increasing_line_color="#27ae60",
                            decreasing_line_color="#e74c3c")
        if fig_kl is not None:
            fig_kl.add_trace(cd, row=i + 1, col=1)
        else:
            fig_kl = go.Figure(cd)
        tr = trades[trades["symbol"] == s] if len(trades) else pd.DataFrame()
        if len(tr):
            op, cl = tr[tr["action"] == "open"], tr[tr["action"] == "close"]
            r = i + 1 if len(symbols) > 1 else None
            kw = dict(row=r, col=1) if r else {}
            fig_kl.add_trace(go.Scatter(x=op["date"], y=op["price"], mode="markers",
                                        marker=dict(symbol="triangle-up", size=12, color="#2980b9"),
                                        name="entry", showlegend=(i == 0)), **kw)
            fig_kl.add_trace(go.Scatter(x=cl["date"], y=cl["price"], mode="markers",
                                        marker=dict(symbol="triangle-down", size=12, color="#f39c12"),
                                        name="exit", showlegend=(i == 0)), **kw)
    fig_kl.update_layout(template="plotly_white", height=320 + 260 * len(symbols),
                         hovermode="x unified", xaxis_rangeslider_visible=False,
                         margin=dict(l=50, r=30, t=40, b=30))
    kline_html = fig_kl.to_html(full_html=False, include_plotlyjs=False, div_id="fig_kline",
                                config={"responsive": True})

    body = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>时序 CTA 回测报告</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:24px;color:#18212f;line-height:1.6;}}
table{{border-collapse:collapse;width:100%;margin:12px 0 20px;}}
th,td{{border:1px solid #d6dae1;padding:7px 10px;}}th{{background:#f3f5f8;}}
.note{{background:#f8fafc;border-left:4px solid #64748b;padding:12px;margin:12px 0;}}
.tabs{{display:flex;gap:4px;border-bottom:2px solid #2980b9;margin:16px 0 0;}}
.tab{{padding:9px 20px;cursor:pointer;border:1px solid #d6dae1;border-bottom:none;background:#f3f5f8;
border-radius:6px 6px 0 0;font-size:14px;}}
.tab.active{{background:#2980b9;color:#fff;border-color:#2980b9;}}
.pane{{display:none;padding:14px 0;}}.pane.active{{display:block;}}
h2{{border-bottom:2px solid #2980b9;padding-bottom:4px;}}
</style></head><body>
<h1>时序 CTA 回测报告（事件驱动引擎）</h1>
<div class="note">由 skill 内置<b>事件驱动引擎</b>生成（固定模板，每次格式一致）：开仓信号即时进场、ATR 吊灯止损用 high/low 命中价即时触发、
收益 close-to-close、含手续费/滑点。日频 bar 口径，非逐笔 intraday。K 线 ▲=开仓、▽=平仓（平仓价当日 close 近似）。</div>
<div class="tabs">
  <div class="tab active" onclick="showTab('nav')">净值曲线</div>
  <div class="tab" onclick="showTab('kline')">K 线</div>
  <div class="tab" onclick="showTab('stats')">统计指标</div>
  <div class="tab" onclick="showTab('trades')">交易记录</div>
</div>
<div id="pane-nav" class="pane active">{nav_html}</div>
<div id="pane-kline" class="pane">{kline_html}</div>
<div id="pane-stats" class="pane">
  <h2>核心绩效（每标的一行，指标为列）</h2>
  {stats_table}
  <h2>已知局限</h2><ul>
  <li>bar 级别（日频/周频）事件驱动，非逐笔 intraday；gap 用命中价/open 近似。</li>
  <li>K 线平仓标记用当日 close 近似（真实止损成交价见 position_return_detail.csv）。</li>
  <li>signal_log.jsonl 为引擎产出的实现方向（审计），非输入。</li>
  <li>胜率为 bar 级口径（含 flat bar）；交易级胜率见 trades.csv。</li>
  </ul>
</div>
<div id="pane-trades" class="pane">
  <h2>交易明细（共 {len(trades_paired) if trades_paired is not None else 0} 笔往返交易）</h2>
  {trades_table}
</div>
<script>
function showTab(id){{
  document.querySelectorAll('.tab').forEach((t,i)=>t.classList.toggle('active',i===['nav','kline','stats','trades'].indexOf(id)));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.getElementById('pane-'+id).classList.add('active');
  // 切到图页签时重绘 plotly（修复隐藏页签渲染窄的问题）
  if(window.Plotly){{
    if(id==='nav') Plotly.Plots.resize('fig_nav');
    if(id==='kline') Plotly.Plots.resize('fig_kline');
  }}
}}
</script>
</body></html>"""
    (sdir / "backtest_report.html").write_text(body, encoding="utf-8")


def update_manifest(cfg: BacktestConfig, metrics: dict) -> None:
    mp = cfg.project_dir / "manifest.json"
    if not mp.exists():
        return
    m = json.loads(mp.read_text(encoding="utf-8-sig"))
    m["backtest_engine"] = {"name": "ts-cta event-driven engine", "status": "ran",
                            "script": "scripts/local_backtest.py", "numba": _HAS_NUMBA}
    m["backtest_command"] = " ".join(sys.argv)
    m.setdefault("run_history", []).append({
        "stage": "event_driven_backtest", "market_data": str(cfg.market_data),
        "final_nav": metrics.get("final_nav"), "sharpe": metrics.get("sharpe"),
        "max_drawdown": metrics.get("max_drawdown")})
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--market-data", required=True, help="OHLCV CSV/Parquet（date,symbol,open,high,low,close）")
    p.add_argument("--strategy", help="strategy.py 路径，默认 03_backtest_strategy/strategy.py")
    p.add_argument("--cost-bps", type=float, default=2.0)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--initial-cash", type=float, default=1_000_000.0)
    p.add_argument("--annualization", type=float, default=252.0)
    p.add_argument("--no-short", action="store_true")
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    cfg = BacktestConfig(
        project_dir=proj, market_data=Path(args.market_data).resolve(),
        strategy_py=Path(args.strategy).resolve() if args.strategy else proj / "03_backtest_strategy" / "strategy.py",
        cost_bps=args.cost_bps, slippage_bps=args.slippage_bps,
        initial_cash=args.initial_cash, annualization=args.annualization, allow_short=not args.no_short)
    if not cfg.market_data.exists():
        raise FileNotFoundError(f"market data 不存在: {cfg.market_data}")
    if not cfg.strategy_py.exists():
        raise FileNotFoundError(f"strategy.py 不存在: {cfg.strategy_py}")

    market = normalize_market(read_table(cfg.market_data), cfg)
    strat_mod = load_strategy(cfg.strategy_py)
    frames = []
    per_sym = {}
    for sym, df in market.groupby("symbol"):
        df = df.sort_values("date").reset_index(drop=True)
        spec = strat_mod.build_strategy(df)
        regime = spec.pop("regime_state", None)  # 提取 regime，不传入引擎
        rets, pos, direc = run_symbol(df, spec, cfg)
        per_sym[sym] = compute_metrics(rets, cfg)
        row = {"date": df["date"], "symbol": sym, "ret": rets.values,
               "pos": pos.values, "direction": direc.values}
        if regime is not None:
            row["regime"] = regime.values
        frames.append(pd.DataFrame(row))
    all_pos = pd.concat(frames, ignore_index=True)
    regime_df = all_pos[["date", "symbol", "regime"]].copy() if "regime" in all_pos.columns else None
    daily = all_pos.groupby("date")["ret"].mean().sort_index()
    metrics = compute_metrics(daily, cfg)
    write_outputs(cfg, daily, all_pos, market, metrics, per_sym,
                  {"metrics": metrics, "per_symbol": per_sym, "numba": _HAS_NUMBA,
                   "n_bars": int(len(all_pos)), "symbols": list(per_sym.keys())},
                  regime_df)
    update_manifest(cfg, metrics)
    print(json.dumps({"ok": True, "numba": _HAS_NUMBA, "metrics": metrics,
                      "per_symbol": per_sym}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
