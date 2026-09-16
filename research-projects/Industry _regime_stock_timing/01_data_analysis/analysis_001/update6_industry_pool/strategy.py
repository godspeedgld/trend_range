"""analysis_001 更新六 —— **在 W2 框架内接「行业池」**（借用另一个策略的 L0/L1 思路）。

与 W2 相比**只有两处改动**（用户指定 4）：

| 项 | W2 | **更新六** |
|---|---|---|
| **候选池剔除** | 破线 / 吊灯 / 涨超10%（三条） | 三条 **+ 新增第四条：不在行业池的 3 个行业内 → 剔除；行业池为空则全部剔除** |
| **优先级** | COMBO | **先按池内行业排名，行业相同再按 COMBO** |

其余**完全不变**：全局参数（1M/10坑/10万/15bps/warmup60）· 信号源（v4活带 deg1~5 无阀）·
**MA200 闸门** · 持仓离场（破线/吊灯）· 仓位与执行（1/n · t收盘→t+1开盘）· ATR14。

**行业池**（周频，申万一级，见 `build_industry_pool.py`）：
  L0  变盘指数 T′ < 0 → 启用；T′ ≥ 0 → **行业池为空**
  L1  用 **240 日动量**给 31 个行业排名 → 取前 **3**
  信号日 = 每周最后一个交易日，**下一交易日起生效**
  （主档不做 L2 稳定性过滤；`POOL_FILE=industry_pool_l2.parquet` 可切对照）

预计算：行业池新算（`../_precomputed/industry_pool.parquet`），其余全部复用。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
PRE = HERE.parent / "_precomputed"
ROOT = HERE.parents[4]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

INDEX_CODE = "000300.SH"
ATR_MULT = 4.0
POOL_FILE = os.environ.get("POOL_FILE", "industry_pool.parquet")
PRIORITY = os.environ.get("PRIORITY", "industry")   # industry（本版）| combo（W2 原版）

# ── 事件（复用）──
_ev = pd.read_parquet(PRE / "events_combo.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[(_ev["degree"] >= 1) & (_ev["degree"] <= 5) & _ev["COMBO"].notna()]
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}

# ── 行业池：日频展开 {date: {p2: rank_in_pool}} ──
_p = pd.read_parquet(PRE / POOL_FILE)
_p["date"] = pd.to_datetime(_p["date"])
POOL = {d: dict(zip(g["p2"], g["rank_in_pool"])) for d, g in _p.groupby("date")}
print(f"[u6] 行业池 = {POOL_FILE} | 覆盖 {len(POOL):,} 个交易日 | "
      f"每池行业数 {_p.groupby('date').size().median():.0f}", flush=True)

# ── 当日成分 ──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_idx = _con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                    "ORDER BY date").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MD = sorted(MEMBERSHIP.keys())

# ── MA200 闸门（W2 原样保留）──
_idx["date"] = pd.to_datetime(_idx["date"])
_s = _idx.set_index("date")["close"]
_GATE_DAYS = set(_s.index[_s > _s.rolling(200).mean()])
print(f"[u6] MA200 开门 {len(_GATE_DAYS)} 日", flush=True)

# ── 个股一级行业归属（复用）──
_si_piv = pd.read_parquet(PRE / "stock_industry.parquet").pivot(
    index="date", columns="symbol", values="p2")

_ATR = pd.read_parquet(PRE / "atr14.parquet")
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()

_TODAY = [None]


def members_asof(d) -> set:
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    import bisect
    i = bisect.bisect_right(_ALL_MD, d) - 1
    return MEMBERSHIP[_ALL_MD[i]] if i >= 0 else set()


def stock_industry(sym, d):
    """该股当日所属申万一级行业（2 位码）。缺失返回 None。"""
    try:
        v = _si_piv.at[d, sym]
    except KeyError:
        return None
    return None if (v is None or (isinstance(v, float) and v != v)) else v


def entry_signal(hist_df: pd.DataFrame) -> bool:
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    _TODAY[0] = d
    if sym not in members_asof(d):
        return False
    if d not in _GATE_DAYS:                      # MA200（W2 原样）
        return False
    return (sym, d) in EVENT


def entry_payload(hist_df: pd.DataFrame) -> dict:
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    return dict(EVENT.get((sym, d), {}))


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """W2 三条 + **更新六第四条（行业池）**。"""
    if len(hist_df) == 0:
        return True
    sym = hist_df["symbol"].iloc[-1]
    sd = pd.Timestamp(signal_date)
    info = EVENT.get((sym, sd))
    dates = pd.to_datetime(hist_df["date"])
    d = dates.iloc[-1]
    c = float(hist_df["close"].iloc[-1])
    if info is None:
        return False
    peak = float(hist_df.loc[dates >= sd, "high"].max())
    try:
        atr = float(ATR_PIV.at[d, sym])
    except KeyError:
        atr = None
    if c < info["line"]:
        return True                                   # ① 破线
    if atr is not None and atr == atr and atr > 0 and c < peak - ATR_MULT * atr:
        return True                                   # ② 吊灯式回撤
    if c > info["close_sig"] * 1.10:
        return True                                   # ③ 涨超突破价10%
    # ★ ④ 行业池：不在池内 3 个行业 → 剔除；池为空 → 全部剔除
    pool = POOL.get(d)
    if not pool:
        return True
    if stock_industry(sym, d) not in pool:
        return True
    return False


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """持仓：破线止损（收盘<信号带线）或 吊灯（收盘<入场前一日起最高−4×ATR14）。"""
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1] if (dates < entry_d).any() else hist_df.index[0]
    sym = hist_df["symbol"].iloc[-1]
    info = (entry_info.get("signal_info") or {})
    line = info.get("line")
    if line is None:
        line = EVENT.get((sym, dates.loc[sig_idx]), {}).get("line")
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


def _combo_score(v) -> float:
    d = _TODAY[0]
    age = (d - pd.Timestamp(v.get("signal_date"))).days if d is not None else 0
    return float(v.get("COMBO", 0.0)) - age / 45.0


def select_order(open_pool: dict) -> list:
    """★ 更新六优先级：先按**池内行业排名**（1/2/3），行业相同再按 COMBO（降序）。"""
    d = _TODAY[0]
    if PRIORITY == "combo":
        return sorted(open_pool, key=lambda s: _combo_score(open_pool[s]), reverse=True)
    pool = POOL.get(d, {})

    def key(s):
        ir = pool.get(stock_industry(s, d), 999)
        return (ir, -_combo_score(open_pool[s]))

    return sorted(open_pool, key=key)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
