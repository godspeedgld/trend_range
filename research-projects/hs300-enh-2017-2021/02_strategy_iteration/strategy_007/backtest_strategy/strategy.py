"""strategy_007 — v3 平台突破 + 个股 LLT(60) 牛熊闸门（承接 A_v2，其余规则不变）。

相对 ab_tests/A_v2（无闸门基线）唯一改动：开仓过滤增加
【个股 LLT(d=60) 切线斜率 > 0】——事件日 t 该股自身处于 LLT 牛市才允许入池。
LLT 预计算：shared/llt60_precompute.py（2015 全面板算，t 日值仅由 ≤t 收盘推出，无未来）。

平仓/仓位/优先级/池/成本 = A_v2 逐条不变：
  止损破带线（entry_payload 随仓位传递，v2 修复版）+ 4×ATR14 吊灯（Wilder）；
  固定名义 10 万 × 10 仓；最近信号优先；5 自然日池超时/10% 回撤失效；15bps 双边。

铁律：严禁未来数据。
  - v3/ATR14/LLT 预计算 t 日值仅由 ≤t 的 bar 推出
  - 股票池用当日沪深300成分（index_component 当日记录）
  - 引擎在 t+1 开盘执行
仓位：固定名义 10 万/仓（n=10，总资金 100 万），不复利。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

PROJECT = Path(__file__).resolve().parents[3]
SHARED = PROJECT / "shared"
sys.path.insert(0, str(SHARED))

from atr14_precompute import load_atr14            # noqa: E402
from llt60_precompute import load_llt60            # noqa: E402
from plateau_events_v3 import load_events          # noqa: E402

INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[6] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
PANEL = PROJECT / "_market_hs300_panel.parquet"    # 2015 全面板（事件/LLT 暖机；回测窗由引擎数据定）

ATR_MULT = 4.0        # 吊灯：信号日起最高价 − 4×ATR(14)
MAX_DEGREE = 5        # 突破程度 ≤5 过滤（6+ 剔除）
POOL_TIMEOUT_DAYS = 5  # 开仓池超时（自然日，沿迭代一惯例）
POOL_DD = 0.10         # 开仓池信号失效回撤

# ── v3 突破事件（预计算查表；同日多事件取 degree 最大者的 line）──
_EVENTS = load_events(PANEL, SHARED)
_EV = (_EVENTS.sort_values("degree", ascending=False)
       .drop_duplicates(["symbol", "date"], keep="first"))
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): (int(r.degree), float(r.line))
             for r in _EV.itertuples()}

# ── 个股 LLT(60) 牛市日集合（预计算查表；k>0 = 该股当日多头）──
_LLT = load_llt60(PANEL, SHARED)
LLT_BULL = {(r.symbol, pd.Timestamp(r.date)) for r in _LLT.itertuples() if r.llt_bull}

# ── ATR(14) 预计算（date × symbol 透视查表）──
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
    """① 开仓：v3 事件（degree≤5）+ 当日成分 + **个股 LLT(60) 斜率>0（本迭代新增）**。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if sym not in members_asof(d):
        return False
    ev = EVENT_MAP.get((sym, d))
    if ev is None or ev[0] > MAX_DEGREE:
        return False
    if (sym, d) not in LLT_BULL:            # LLT 个股牛市闸门
        return False
    return True


def entry_payload(hist_df: pd.DataFrame) -> dict:
    """⑥ 入池载荷：信号日事件的止损线随仓位传递（v2 修复版，防排队开仓丢线）。"""
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    ev = EVENT_MAP.get((sym, d))
    return {"line": float(ev[1])} if ev else {}


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓：止损（收盘<信号日被破带阻力线，优先）或 吊灯（收盘<信号日起最高价−4×ATR14）。

    阻力线优先取 entry_payload 传入的 signal_info["line"]；兜底：入场日前一交易日重查。
    """
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1]        # 信号日 = 入场日前最后一根 bar
    sym = hist_df["symbol"].iloc[-1]
    sig_d = dates.loc[sig_idx]
    line = (entry_info.get("signal_info") or {}).get("line")
    if line is None:
        ev = EVENT_MAP.get((sym, sig_d))
        line = float(ev[1]) if ev else None
    c = float(hist_df["close"].iloc[-1])
    post_high = float(hist_df.loc[sig_idx:, "high"].max())
    d = dates.iloc[-1]
    try:
        atr = float(ATR_PIV.at[d, sym])
    except KeyError:
        atr = None
    if line is not None and c < line:
        return True
    if atr is not None and atr == atr and atr > 0 and c < post_high - ATR_MULT * atr:
        return True
    return False


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """③ 开仓池剔除：信号后 5 自然日超时或回撤 10%。"""
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
    """④ 开仓优先级：最近突破优先（A 变体口径）。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：固定名义模式下引擎直接给 10 万/仓，此接口仅兜底 1/n。"""
    return 1.0 / n
