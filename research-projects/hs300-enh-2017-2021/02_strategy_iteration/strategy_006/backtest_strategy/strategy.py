"""strategy_006 — v3 水平带突破组合版（沪深300当日成分 + 固定名义 + 4×ATR14 吊灯）。

【更新三 2026-08-28（当前版）】= **变体 A 全部规则**（degree≤5 过滤 + n=10/100万 + 最近突破优先
+ m=4 吊灯 + 止损破线）**+ 年线开仓闸门**：**沪深300指数收盘 > MA200 才允许开新仓**
（用户指定；指数 regime 用 ≤t 数据逐日查表，无未来；存量持仓仍按止损/吊灯离场，不受闸门影响）。

【历史】更新二（degree≤5+n=20/200万+突破程度优先）负贡献 → A/B 分解定责（见 final_report 附二）；
原版（degree≥1/n=10/最近优先）年化 +7.84%；A（=原版+degree≤5）年化 +14.30%。

开仓：v3 break_up 事件查表（shared/plateau_events_v3.py 预计算）+ degree≤5 + 指数在年线上
+ 当日成分过滤。平仓（analysis_007 更新四同款）：① 止损=收盘 < 被破带阻力线（优先）；
② 吊灯=收盘 < 突破后最高价 − 4×ATR(14)（最高价自信号日起含；ATR14 预计算；NaN 当日只判止损）。
本文件只 import 共享模块，不内联算法。

铁律：严禁未来数据。
  - v3/ATR14 预计算 t 日值仅由 ≤t 的 bar 推出（状态机/ewm 增量）
  - 年线闸门：t 日 regime = t 日指数收盘 vs t 日 MA200（rolling(200) 截至当日），无未来
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
from plateau_events_v3 import load_events          # noqa: E402

INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[6] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
PANEL = PROJECT / "_market_hs300_panel.parquet"

ATR_MULT = 4.0        # 吊灯：突破后最高价 − 4×ATR(14)
MAX_DEGREE = 5        # 突破程度 ≤5 过滤（6+ 剔除）
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
_idx = _con.execute(
    f"SELECT date, close FROM index_bar1d WHERE instrument='{INDEX_CODE}' ORDER BY date"
).fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MEMBER_DATES = sorted(MEMBERSHIP.keys())

# ── 年线闸门（更新三）：t 日指数收盘 > t 日 MA200 的日期集合（≤t 数据，无未来）──
_idx["date"] = pd.to_datetime(_idx["date"])
_idx = _idx.set_index("date")["close"]
_bull = (_idx > _idx.rolling(200).mean()).fillna(False)
BULL_DAYS = set(_bull[_bull].index)


def members_asof(d) -> set:
    """≤d 的最近一次成分记录（当日无记录时取最近历史成分，无未来）。"""
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    earlier = [x for x in _ALL_MEMBER_DATES if x <= d]
    return MEMBERSHIP[earlier[-1]] if earlier else set()


def entry_signal(hist_df: pd.DataFrame) -> bool:
    """① 开仓：v3 突破事件（degree≤5）+ **指数收盘在 MA200 之上** + 当日成分过滤。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if d not in BULL_DAYS:                    # 年线闸门：指数在线下不开新仓
        return False
    if sym not in members_asof(d):
        return False
    ev = EVENT_MAP.get((sym, d))
    return ev is not None and ev[0] <= MAX_DEGREE


def entry_payload(hist_df: pd.DataFrame) -> dict:
    """⑥ 入池载荷（引擎可选接口）：信号日事件的止损线随仓位传递。

    修 2026-09-01（BigQuant 移植分歧复盘）：原 exit_check 以"入场日前最后一根 bar"
    重查 EVENT_MAP 取阻力线——池中排队 >1 天开仓的仓，入场前一交易日并非信号日，
    查不到事件 → line=None 丢止损线（只剩吊灯）。引擎现把本载荷存入
    holdings["signal_info"]，exit_check 优先取此处 line（与移植版池语义一致）。
    """
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    ev = EVENT_MAP.get((sym, d))
    return {"line": float(ev[1])} if ev else {}


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓：止损（收盘<信号日被破带阻力线，优先）或 吊灯（收盘<突破后最高价−4×ATR14）。

    阻力线 = 入场信号日事件（同日取 degree 最大）的 line —— 优先取引擎传入的
    signal_info["line"]（entry_payload 入池载荷；2026-09-01 修：排队开仓不再丢止损线）；
    兜底：以入场日前最后一根 bar 重查 EVENT_MAP（仅次日入场时与信号日等价）。
    突破后最高价 = 自信号日（入场日前最后一根 bar）起含的最高 high。
    """
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1]        # 信号日 = 入场日前最后一根 bar
    sym = hist_df["symbol"].iloc[-1]
    sig_d = dates.loc[sig_idx]
    line = (entry_info.get("signal_info") or {}).get("line")
    if line is None:                                  # 兜底：旧口径重查
        ev = EVENT_MAP.get((sym, sig_d))
        line = float(ev[1]) if ev else None           # 查不到事件则不用止损线
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
    """④ 开仓优先级（更新三回 A 口径）：突破时间距离当前日最近优先。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：固定名义模式下引擎直接给 10 万/仓，此接口仅兜底 1/n。"""
    return 1.0 / n
