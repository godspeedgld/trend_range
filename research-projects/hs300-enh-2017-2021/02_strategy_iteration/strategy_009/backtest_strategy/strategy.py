"""strategy_009 — v4 活带突破 + 指数偏离 MA200 闸门。

v0：偏离 [0,+6%) 甜点带，10×10万（防守型，Sharpe0.49/maxDD-27.7% 最优但总收益<MA200）
更新一：偏离 [-2%,+12%) 放宽 + 引擎 30×10万（300万）——看放宽+加仓能否提总量

规则：
  开仓：v4 break_up 事件（活带，degree≤5）+ 当日沪深300成分 + 信号日指数偏离 ∈[DEV_LO,DEV_HI)
  平仓/仓位/优先级 = A_v2 同款：止损破 line（entry_payload）+ 4×ATR14 吊灯；坑位由引擎传

信号源 v4_events（v4_backtest/v4_events.parquet，活带突破，已含 sig_i）。
偏离闸门：信号日 t 用沪深300 (close-MA200)/MA200 ∈ [DEV_LO, DEV_HI)，无未来（≤t 数据）。
铁律：无未来；t 收盘决策 → t+1 开盘执行。
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

INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[6] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
PANEL = PROJECT / "_market_hs300_panel.parquet"
V4_EVENTS = PROJECT / "01_data_analysis/analysis_012/v4_backtest/v4_events.parquet"

ATR_MULT = 4.0
MAX_DEGREE = 5
DEV_LO, DEV_HI = -0.02, 0.12      # 指数偏离年线 [-2%,+12%) 闸门（更新一放宽）
POOL_TIMEOUT_DAYS = 5
POOL_DD = 0.10

# ── v4 活带突破事件（同日取 degree 最大者）──
_EV = pd.read_parquet(V4_EVENTS)
_EV["date"] = pd.to_datetime(_EV["date"])
_EV = (_EV.sort_values("degree", ascending=False)
       .drop_duplicates(["symbol", "date"], keep="first"))
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): (int(r.degree), float(r.line))
             for r in _EV.itertuples()}

# ── ATR(14) 透视 ──
_ATR = load_atr14(PANEL, SHARED)
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()

# ── 沪深300 当日成分 ──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute(
    f"SELECT date, member_code FROM index_component WHERE instrument='{INDEX_CODE}'"
).fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MEMBER_DATES = sorted(MEMBERSHIP.keys())

# ── 指数偏离 MA200 ∈[0,6%) 日期集合（≤t，无未来）──
_con3 = duckdb.connect(str(WAREHOUSE), read_only=True)
_idx_df = _con3.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                        "ORDER BY date").fetchdf()
_con3.close()
_idx_df["date"] = pd.to_datetime(_idx_df["date"])
_idx_s = _idx_df.set_index("date")["close"]
_ma200 = _idx_s.rolling(200).mean()
_dev = (_idx_s - _ma200) / _ma200
SWEET_DAYS = set(_dev.index[(_dev >= DEV_LO) & (_dev < DEV_HI)])
print(f"[009] v4事件 {len(EVENT_MAP)} | 偏离闸门 {len(SWEET_DAYS)} 日 | "
      f"偏离样本 {_dev.dropna().min():+.2f}~{_dev.dropna().max():+.2f}")


def members_asof(d) -> set:
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    earlier = [x for x in _ALL_MEMBER_DATES if x <= d]
    return MEMBERSHIP[earlier[-1]] if earlier else set()


def entry_signal(hist_df: pd.DataFrame) -> bool:
    """开仓：v4 突破(degree≤5) + 当日成分 + 指数偏离∈[0,6%) 闸门。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if sym not in members_asof(d):
        return False
    ev = EVENT_MAP.get((sym, d))
    if ev is None or ev[0] > MAX_DEGREE:
        return False
    if d not in SWEET_DAYS:            # 指数偏离闸门（非牛市初段不开）
        return False
    return True


def entry_payload(hist_df: pd.DataFrame) -> dict:
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    ev = EVENT_MAP.get((sym, d))
    return {"line": float(ev[1])} if ev else {}


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """平仓：止损(收盘<信号日被破带 line，优先) 或 吊灯(收盘<信号日起最高−4×ATR14)。"""
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1]
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
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    return 1.0 / n
