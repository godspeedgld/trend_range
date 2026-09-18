"""analysis_001 更新一 —— **双过滤：MA200 以上 AND 变盘指数下行**。

与分析一当前规则（④ 变盘下行 + 行业优先）的**唯一差异** = 入场闸门：

| 项 | 分析一（④） | 更新一 |
|---|---|---|
| **入场闸门** | 变盘指数下行（T′<0） | **MA200（沪深300 close>MA200）AND 变盘指数下行（T′<0）** |

其余**完全相同**（用户指定 2）：
  全局参数 1M/10坑/10万/15bps/warmup60 · 信号源 v4活带 deg1~5 无阀 ·
  优先级 **先行业收益率排名，再 COMBO**（规则 6）· 池失效三条件 · 持仓离场两条件 ·
  仓位与执行 1/n · t收盘→t+1开盘 · ATR14 Wilder

**预计算复用**（用户指定 3）：直接用 `../_precomputed/`（分析一的产物），
本更新**不重算任何预计算** —— 双过滤只是把两张已有的日频布尔序列取交集。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent                            # analysis_001
ROOT = HERE.parents[4]                      # trend_range
PRE = UP / "_precomputed"                   # ← 复用分析一的预计算
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

INDEX_CODE = "000300.SH"
ATR_MULT = 4.0
PRIORITY = os.environ.get("PRIORITY", "industry")   # industry（同分析一）| combo（对照用）

# ── 事件（复用）──
_ev = pd.read_parquet(PRE / "events_combo.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[(_ev["degree"] >= 1) & (_ev["degree"] <= 5) & _ev["COMBO"].notna()]
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}

# ── 当日成分（复用逻辑，读同一 warehouse）──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_idx = _con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                    "ORDER BY date").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MD = sorted(MEMBERSHIP.keys())

# ── 双过滤闸门：MA200 开门 AND 变盘下行 ──
_idx["date"] = pd.to_datetime(_idx["date"])
_s = _idx.set_index("date")["close"]
_MA200 = set(_s.index[_s > _s.rolling(200).mean()])
_rg = pd.read_parquet(PRE / "regime_index.parquet")[["date", "down"]]
_rg["date"] = pd.to_datetime(_rg["date"])
_REG_DOWN = set(_rg.loc[_rg["down"], "date"])
_GATE_DAYS = _MA200 & _REG_DOWN                      # ★ 交集 = 双过滤
print(f"[u1] MA200 开门 {len(_MA200)} 日 ∩ 变盘下行 {len(_REG_DOWN)} 日 "
      f"→ **双过滤开门 {len(_GATE_DAYS)} 日**（占 MA200 的 {len(_GATE_DAYS)/len(_MA200)*100:.0f}%）",
      flush=True)

# ── 优先级（规则 6，复用）──
_si_piv = pd.read_parquet(PRE / "stock_industry.parquet").pivot(
    index="date", columns="symbol", values="p2")
_rk_piv = pd.read_parquet(PRE / "ind_ret_rank.parquet").pivot(
    index="date", columns="p2", values="rank")

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


def industry_rank(sym, d):
    try:
        p2 = _si_piv.at[d, sym]
    except KeyError:
        return None
    if p2 is None or (isinstance(p2, float) and p2 != p2):
        return None
    try:
        v = _rk_piv.at[d, p2]
    except KeyError:
        return None
    return None if (v is None or (isinstance(v, float) and v != v)) else float(v)


def entry_signal(hist_df: pd.DataFrame) -> bool:
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    _TODAY[0] = d
    if sym not in members_asof(d):
        return False
    if d not in _GATE_DAYS:                           # ★ MA200 ∩ 变盘下行
        return False
    return (sym, d) in EVENT


def entry_payload(hist_df: pd.DataFrame) -> dict:
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    return dict(EVENT.get((sym, d), {}))


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """无超时；三条件任一清出：破线 / 吊灯式回撤 / 收盘较突破价涨超10%。"""
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
        return True
    if atr is not None and atr == atr and atr > 0 and c < peak - ATR_MULT * atr:
        return True
    if c > info["close_sig"] * 1.10:
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
    """规则 6：先比行业收益率排名（1=最强最优先），再比 COMBO score（降序）。"""
    d = _TODAY[0]
    if PRIORITY == "combo":
        return sorted(open_pool, key=lambda s: _combo_score(open_pool[s]), reverse=True)

    def key(s):
        ir = industry_rank(s, d)
        ir = 999.0 if ir is None else ir
        return (ir, -_combo_score(open_pool[s]))

    return sorted(open_pool, key=key)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
