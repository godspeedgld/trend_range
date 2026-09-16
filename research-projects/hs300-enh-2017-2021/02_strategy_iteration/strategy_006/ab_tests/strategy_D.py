"""[ab_tests/D] degree≤5 过滤 + 突破程度优先（degree 降序；n=10/100万）。对照 A 隔离优先级改动效应。

【更新二 2026-08-28】① 开仓加 **degree ≤ 5 过滤**（6+ 档剔除——组合层供给过剩 21 倍，
坑位让给高期望档）；② **n=20 仓、每只 10 万、总资金 200 万**（引擎 --max-positions 20
--initial-cash 2000000 --fixed-notional 100000）；③ 优先级改 **突破程度优先**（degree 降序），
相同 degree 最近突破优先。其余规则不变。

原版（更新一前）：v3 事件 degree≥1 全保留、n=10/100万、最近突破优先。

开仓：v3 break_up 事件查表（shared/plateau_events_v3.py 预计算）+ degree≤5 + 当日成分过滤。
平仓（analysis_007 更新四同款）：① 止损=收盘 < 被破带阻力线（优先）；② 吊灯=收盘 < 突破后最高价
− 4×ATR(14)（最高价自信号日起含；ATR14 预计算；NaN 当日只判止损）。
本文件只 import 共享模块，不内联算法。

铁律：严禁未来数据。
  - v3/ATR14 预计算 t 日值仅由 ≤t 的 bar 推出（状态机/ewm 增量）
  - 股票池用当日沪深300成分（index_component 当日记录）
  - 引擎在 t+1 开盘执行
仓位：固定名义 10 万/仓，不复利。
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
from plateau_events_v3 import load_events          # noqa: E402

INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[6] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
PANEL = PROJECT / "_market_hs300_panel.parquet"

ATR_MULT = 4.0        # 吊灯：突破后最高价 − 4×ATR(14)
MAX_DEGREE = 5        # 更新二：突破程度 ≤5 过滤（6+ 剔除）
POOL_TIMEOUT_DAYS = 5  # 开仓池超时（自然日，沿迭代一惯例）
POOL_DD = 0.10         # 开仓池信号失效回撤

# ── v3 突破事件（预计算查表；同日多事件取 degree 最大者的 line）──
_EVENTS = load_events(PANEL, SHARED)
_EV = (_EVENTS.sort_values("degree", ascending=False)
       .drop_duplicates(["symbol", "date"], keep="first"))
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): (int(r.degree), float(r.line))
             for r in _EV.itertuples()}

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
    """① 开仓：v3 水平带突破事件（查表，degree≤5）+ 当日成分过滤。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if sym not in members_asof(d):
        return False
    ev = EVENT_MAP.get((sym, d))
    return ev is not None and ev[0] <= MAX_DEGREE


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓：止损（收盘<信号日被破带阻力线，优先）或 吊灯（收盘<突破后最高价−4×ATR14）。

    阻力线 = 入场信号日事件（同日取 degree 最大）的 line；
    突破后最高价 = 自信号日（入场日前最后一根 bar）起含的最高 high。
    """
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1]        # 信号日 = 入场日前最后一根 bar
    sym = hist_df["symbol"].iloc[-1]
    sig_d = dates.loc[sig_idx]
    ev = EVENT_MAP.get((sym, sig_d))
    line = float(ev[1]) if ev else None               # 兜底：查不到事件则不用止损线
    c = float(hist_df["close"].iloc[-1])
    post_high = float(hist_df.loc[sig_idx:, "high"].max())
    d = dates.iloc[-1]
    try:
        atr = float(ATR_PIV.at[d, sym])
    except KeyError:
        atr = None
    # ① 止损（优先）
    if line is not None and c < line:
        return True
    # ② 吊灯（ATR NaN 当日跳过）
    if atr is not None and atr == atr and atr > 0 and c < post_high - ATR_MULT * atr:
        return True
    return False


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
    """④ 开仓优先级（更新二）：突破程度优先（degree 降序），相同 degree 最近突破优先。"""
    def key(s):
        sd = open_pool[s].get("signal_date")
        deg = EVENT_MAP.get((s, pd.Timestamp(sd)))
        return (-(deg[0] if deg else 0), pd.Timestamp(sd))
    return sorted(open_pool, key=key)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：固定名义模式下引擎直接给 10 万/仓，此接口仅兜底 1/n。"""
    return 1.0 / n
