"""analysis_001 更新四 —— 双过滤，但**变盘指数改用申万二级（117 个）**计算。

与更新一（双过滤 + 行业优先）的**唯一差异**（用户指定 1、2）：

| 项 | 更新一 | 更新四 |
|---|---|---|
| **变盘指数** | 申万**一级** 31 个行业 | 申万**二级** 117 个行业 |

其余**完全相同**：闸门 = MA200 ∩ 变盘指数下行 · 全局参数 · 信号源 · 池失效 · 持仓离场 ·
优先级（行业收益率排名 → COMBO）· 仓位与执行 · ATR14。

⚠ 注意：**优先级用的仍是"一级行业收益率排名"**（用户只说改变盘指标的计算，没说改优先级）。
本更新只换变盘指数的横截面口径。

预计算：变盘指数 L2 版由 `build_regime_index_l2.py` 新算（`../_precomputed/regime_index_l2.parquet`），
其余全部复用 `../_precomputed/`。
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
REGIME_FILE = os.environ.get("REGIME_FILE", "regime_index_l2.parquet")  # ★ 默认二级版

# ── 事件（复用）──
_ev = pd.read_parquet(PRE / "events_combo.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[(_ev["degree"] >= 1) & (_ev["degree"] <= 5) & _ev["COMBO"].notna()]
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}

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

# ── 闸门：MA200 ∩ 变盘指数下行（★ 变盘指数换二级版）──
_idx["date"] = pd.to_datetime(_idx["date"])
_s = _idx.set_index("date")["close"]
_MA200 = set(_s.index[_s > _s.rolling(200).mean()])
_rg = pd.read_parquet(PRE / REGIME_FILE)[["date", "down"]]
_rg["date"] = pd.to_datetime(_rg["date"])
_REG_DOWN = set(_rg.loc[_rg["down"], "date"])
_GATE_DAYS = _MA200 & _REG_DOWN
print(f"[u4] 变盘指数 = {REGIME_FILE} | MA200 {len(_MA200)} 日 ∩ 变盘下行 {len(_REG_DOWN)} 日 "
      f"→ **双过滤开门 {len(_GATE_DAYS)} 日**（占 MA200 的 {len(_GATE_DAYS)/len(_MA200)*100:.0f}%）",
      flush=True)

# ── 优先级：行业收益率排名（一级，同更新一）──
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
    if d not in _GATE_DAYS:
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

    def key(s):
        ir = industry_rank(s, d)
        ir = 999.0 if ir is None else ir
        return (ir, -_combo_score(open_pool[s]))

    return sorted(open_pool, key=key)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
