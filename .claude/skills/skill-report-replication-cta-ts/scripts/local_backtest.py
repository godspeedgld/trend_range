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
    out = df[need].copy()
    out.columns = ["date", "symbol", "open", "high", "low", "close"]
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str)
    for c in ["open", "high", "low", "close"]:
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


def rolling_vol(close, window):
    return np.log(close).diff().rolling(window).std()


# ── 事件驱动状态机（核心，numba 加速）─────────────────
@njit(cache=True)
def _simulate(open_, high, low, close, entry_long, entry_short, atr_v,
              pos_size, stop_type, k_stop, pct_stop, cost_rate, allow_short):
    """逐根事件驱动。返回 (rets, pos_series, dir_series)。"""
    n = len(close)
    rets = np.zeros(n, dtype=np.float64)
    pos_series = np.zeros(n, dtype=np.float64)
    dir_series = np.zeros(n, dtype=np.int32)
    pos = 0.0
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
            sp = 0.0
            if stop_type == 1:
                sp = entry_price - k_stop * atr_v[t] if pos > 0 else entry_price + k_stop * atr_v[t]
            elif stop_type == 2:
                sp = since_high - k_stop * atr_v[t] if pos > 0 else since_low + k_stop * atr_v[t]
            elif stop_type == 3:
                sp = entry_price * (1 - pct_stop) if pos > 0 else entry_price * (1 + pct_stop)
            hit = False
            if stop_type != 0:
                hit = (low[t] <= sp) if pos > 0 else (high[t] >= sp)
            if hit:
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
        if pos == 0.0:
            sig = 0
            if entry_long[t]:
                sig = 1
            elif entry_short[t] and allow_short == 1:
                sig = -1
            if sig != 0:
                size = pos_size[t]
                pos = sig * size
                entry_price = close[t]
                since_high = close[t]
                since_low = close[t]
                rets[t] = rets[t] - abs(pos) * cost_rate
                pos_series[t] = pos
                dir_series[t] = sig
    return rets, pos_series, dir_series


def run_symbol(df: pd.DataFrame, spec: dict, cfg: BacktestConfig):
    stop = spec.get("stop", {}) or {}
    stop_type = STOP_MAP.get(stop.get("type", "none"), 0)
    atr_period = int(stop.get("atr_period", 14))
    k_stop = float(stop.get("k", 2.0))
    pct_stop = float(stop.get("pct", 0.05))
    sizing = spec.get("sizing", {}) or {}
    vol_win = int(sizing.get("vol_window", 20))
    if sizing.get("type") == "vol_target":
        tv = float(sizing.get("target_vol", 0.15)) / math.sqrt(cfg.annualization)
        rv = rolling_vol(df["close"], vol_win).bfill()
        pos_size = (tv / rv.replace(0, np.nan)).fillna(0.0).clip(upper=3.0).to_numpy()
    else:
        pos_size = np.ones(len(df))
    atr_v = atr(df["high"], df["low"], df["close"], atr_period).bfill().to_numpy()
    el = spec["entry_long"].reindex(df.index).fillna(False).astype(bool).to_numpy()
    es_s = spec.get("entry_short", pd.Series(False, index=df.index))
    es = es_s.reindex(df.index).fillna(False).astype(bool).to_numpy()
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 10000.0
    allow = 1 if (cfg.allow_short and spec.get("allow_short", True)) else 0
    rets, pos, direc = _simulate(
        df["open"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(),
        el, es, atr_v, pos_size, stop_type, k_stop, pct_stop, cost_rate, allow)
    return (pd.Series(rets, index=df.index, name="ret"),
            pd.Series(pos, index=df.index, name="pos"),
            pd.Series(direc, index=df.index, name="direction", dtype=int))


# ── 指标（复用 -factor compute_metrics 口径）──────────
def compute_metrics(returns: pd.Series, cfg: BacktestConfig) -> dict:
    r = returns.fillna(0.0)
    n = len(r)
    if n == 0:
        return {"periods": 0}
    nav = (1 + r).cumprod()
    final_nav = float(nav.iloc[-1])
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
        "periods": float(n), "final_nav": final_nav, "total_return": final_nav - 1.0,
        "annual_return": ann_return, "annual_volatility": ann_vol, "downside_volatility": dv,
        "sharpe": sharpe, "sortino": sortino, "calmar": calmar, "max_drawdown": max_dd,
        "win_rate": float((r > 0).mean()), "profit_factor": pf,
    }


# ── 输出 ────────────────────────────────────────────────
def write_outputs(cfg: BacktestConfig, daily: pd.Series, all_pos: pd.DataFrame,
                  metrics: dict, per_sym: dict, raw: dict) -> None:
    sdir = cfg.project_dir / "03_backtest_strategy"
    logs = sdir / "backtest_logs"
    logs.mkdir(parents=True, exist_ok=True)
    nav = (1 + daily).cumprod()
    pd.DataFrame({"date": daily.index, "net_return": daily.values, "nav": nav.values,
                  "drawdown": (nav / nav.cummax() - 1.0).values}).to_csv(
        logs / "equity_curve.csv", index=False, encoding="utf-8-sig")
    all_pos.to_csv(logs / "position_return_detail.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([metrics]).to_csv(logs / "performance_metrics.csv", index=False, encoding="utf-8-sig")
    # signal_log：实现方向（审计用，引擎产出）
    with (logs / "signal_log.jsonl").open("w", encoding="utf-8") as f:
        for (d, s), grp in all_pos.groupby(["date", "symbol"]):
            f.write(json.dumps({"date": pd.Timestamp(d).strftime("%Y-%m-%d"),
                                "signals": {str(s): {"factor": 0.0,
                                                     "direction": int(grp["direction"].iloc[0])}}},
                               ensure_ascii=False) + "\n")
    write_html(sdir, metrics, per_sym)
    (sdir / "backtest_report_raw.html").write_text(
        "<pre>" + html.escape(json.dumps(raw, ensure_ascii=False, indent=2, default=str)) + "</pre>",
        encoding="utf-8")


def write_html(sdir: Path, metrics: dict, per_sym: dict) -> None:
    def fmt(v):
        if v is None:
            return "NA"
        try:
            return "NA" if (isinstance(v, float) and not np.isfinite(v)) else f"{v:.4f}"
        except Exception:
            return str(v)
    rows = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{fmt(v)}</td></tr>" for k, v in metrics.items())
    sym_rows = "".join(
        f"<tr><td>{html.escape(str(s))}</td><td>{fmt(m.get('final_nav'))}</td><td>{fmt(m.get('sharpe'))}</td>"
        f"<td>{fmt(m.get('max_drawdown'))}</td></tr>" for s, m in per_sym.items())
    (sdir / "backtest_report.html").write_text(
        f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>时序 CTA 回测报告</title>
<style>body{{font-family:Arial,"Microsoft YaHei",sans-serif;margin:32px;color:#18212f;line-height:1.6;}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px;}}
th,td{{border:1px solid #d6dae1;padding:8px;}}th{{background:#f3f5f8;}}
.note{{background:#f8fafc;border-left:4px solid #64748b;padding:12px;}}</style></head><body>
<h1>时序 CTA 回测报告（事件驱动引擎）</h1>
<div class="note">由 skill 内置<b>事件驱动引擎</b>生成：开仓信号即时进场、ATR 吊灯止损用 high/low 命中价即时触发、
收益 close-to-close、含手续费/滑点。日频 bar 口径，非逐笔 intraday。</div>
<h2>核心绩效</h2><table>{rows}</table>
<h2>分品种</h2><table><tr><th>品种</th><th>final_nav</th><th>sharpe</th><th>max_drawdown</th></tr>{sym_rows}</table>
<h2>已知局限</h2><ul><li>bar 级别（日频/周频）事件驱动，非逐笔 intraday</li>
<li>gap 用命中价/open 近似</li><li>signal_log.jsonl 为引擎产出的实现方向（审计），非输入</li></ul>
</body></html>""", encoding="utf-8")


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
        rets, pos, direc = run_symbol(df, spec, cfg)
        per_sym[sym] = compute_metrics(rets, cfg)
        frames.append(pd.DataFrame({"date": df["date"], "symbol": sym, "ret": rets.values,
                                    "pos": pos.values, "direction": direc.values}))
    all_pos = pd.concat(frames, ignore_index=True)
    daily = all_pos.groupby("date")["ret"].mean().sort_index()
    metrics = compute_metrics(daily, cfg)
    write_outputs(cfg, daily, all_pos, metrics, per_sym,
                  {"metrics": metrics, "per_symbol": per_sym, "numba": _HAS_NUMBA,
                   "n_bars": int(len(all_pos)), "symbols": list(per_sym.keys())})
    update_manifest(cfg, metrics)
    print(json.dumps({"ok": True, "numba": _HAS_NUMBA, "metrics": metrics,
                      "per_symbol": per_sym}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
