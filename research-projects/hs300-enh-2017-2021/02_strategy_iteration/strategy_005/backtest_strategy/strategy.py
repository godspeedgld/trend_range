"""strategy_005 — 趋势线突破 v2.7 组合版（沪深300当日成分 + 固定名义 10 仓）。

【更新一 2026-08-27】平仓规则替换：10% 回撤 + 30 交易日 → **固定止损 5% + 吊灯 2×ATR(14)**
（shared/exit_rules_v3.py；ATR14 预计算 shared/atr14_precompute.py）。
  ① close < 突破价格(信号日收盘) × 0.95 → fixed_stop
  ② close < 突破后最高价(自信号日起最高 high) − 2×ATR14 → chandelier
  收盘决策次日开盘执行；无 ATR（NaN）时只判固定止损。

其余不变：开仓 v2.7 事件查表 + 当日成分过滤；固定名义 10 万/仓；优先级=最近突破优先。
铁律：严禁未来数据。
  - entry_signal 查 v2.7 事件表：t 日事件仅由 ≤t 的 bar 推出（状态机增量推进），无未来
  - 股票池用**当日**沪深300成分（index_component 当日记录，members_asof 无未来）
  - 引擎在 t+1 开盘执行
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT = Path(__file__).resolve().parents[3]
SHARED = PROJECT / "shared"
sys.path.insert(0, str(SHARED))

from atr14_precompute import load_atr14  # noqa: E402
from exit_rules_v3 import exit_triggered_v3  # noqa: E402
from plateau_events_v27 import load_breakup_events  # noqa: E402

INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[6] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
PANEL = PROJECT / "_market_hs300_panel.parquet"

STOP_PCT = 0.05           # 固定止损：跌破突破价格 5%
ATR_MULT = 2.0            # 吊灯：突破后最高价 − 2×ATR(14)
POOL_TIMEOUT_DAYS = 5     # 开仓池超时（自然日，沿迭代一 suppress_days 惯例）
POOL_DD = 0.10            # 开仓池信号失效回撤

# ── v2.7 突破事件（预计算查表；无缓存时自动重算并落盘）──
_EVENTS = load_breakup_events(PANEL, SHARED)
BREAKUP_MAP = {(r.symbol, pd.Timestamp(r.date)) for r in _EVENTS.itertuples()}

# ── ATR(14) 预计算（date × symbol 透视，查表 (d, sym)）──
_ATR = load_atr14(PANEL, SHARED)
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()

# ── 沪深300 每日成分（当日记录，无未来）──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute(
    f"SELECT date, member_code FROM index_component WHERE instrument='{INDEX_CODE}'"
).fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MEMBER_DATES = sorted(MEMBERSHIP.keys())


def members_asof(d) -> set:
    """≤d 的最近一次成分记录（当日无记录时取最近历史成分，无未来）。"""
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    earlier = [x for x in _ALL_MEMBER_DATES if x <= d]
    return MEMBERSHIP[earlier[-1]] if earlier else set()


def entry_signal(hist_df: pd.DataFrame) -> bool:
    """① 开仓：v2.7 趋势线突破事件（查表）+ 当日成分过滤。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if sym not in members_asof(d):
        return False
    return (sym, d) in BREAKUP_MAP


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓（更新一）：固定止损 5% 或 吊灯 2×ATR(14)（shared/exit_rules_v3.py）。

    突破价格 = 信号日收盘（入场日前最后一根 bar）；
    突破后最高价 = 自信号日起最高 high（含信号日）；
    ATR14 查预计算表（当日值，≤t 数据）；NaN 时只判固定止损。
    """
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1]        # 信号日 = 入场日前最后一根 bar
    breakout_price = float(hist_df.loc[sig_idx, "close"])
    post_high = float(hist_df.loc[sig_idx:, "high"].max())
    c = float(hist_df["close"].iloc[-1])
    sym = hist_df["symbol"].iloc[-1]
    d = dates.iloc[-1]
    try:
        atr = float(ATR_PIV.at[d, sym])
    except KeyError:
        atr = None
    hit, _reason = exit_triggered_v3(c, breakout_price, post_high, atr,
                                     stop_pct=STOP_PCT, atr_mult=ATR_MULT)
    return hit


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """③ 开仓池剔除：信号后 5 自然日超时或回撤 10%（沿迭代一惯例）。"""
    if len(hist_df) == 0:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(signal_date)).days
    if days > POOL_TIMEOUT_DAYS:
        return True
    c = hist_df["close"].iloc[-1]
    sig = hist_df.loc[pd.to_datetime(hist_df["date"]) == pd.Timestamp(signal_date), "close"]
    if len(sig) and sig.iloc[0] > 0:
        if c / sig.iloc[0] - 1.0 < -POOL_DD:
            return True
    return False


def select_order(open_pool: dict) -> list:
    """④ 开仓优先级：突破时间距离当前日最近优先。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：固定名义模式下引擎直接给 10 万/仓，此接口仅兜底 1/n。"""
    return 1.0 / n
