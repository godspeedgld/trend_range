"""analysis_001 更新二 —— 行业优先从「排序」改为「过滤（前 N 名行业）」+ COMBO 排序。

与更新一（双过滤 + 行业优先排序）的**唯一差异**（用户指定 1、2）：

| 项 | 更新一 | 更新二 |
|---|---|---|
| **优先级** | 按行业收益率排名**排序**（越靠前越优先），全部行业都可开仓 | **只允许行业收益率排名前 N 的行业开仓**（过滤），组内按 COMBO 排序 |

其余**完全相同**：闸门 = MA200 ∩ 变盘下行 · 全局参数 · 信号源 · 池失效 · 持仓离场 · 仓位与执行 · ATR14。

规则 3：**行业排名相同 → 按 W2 的 COMBO 规则**（score = COMBO − age/45，降序）。

实现：`select_order` 先剔除 `industry_rank > TOP_N` 的候选，**再按 (行业排名, −COMBO score) 排序**。
即"过滤 + 组内双键排序"，而非更新一的"纯排序"。

对照：`TOP_N=10`（用户指定 2 的对照组）；`TOP_N=999` 等价于更新一（不设行业过滤）。

预计算：全部复用 `../_precomputed/`（零重算）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
PRE = HERE.parent / "_precomputed"           # 复用 analysis_001 的预计算
ROOT = HERE.parents[4]                        # trend_range
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

INDEX_CODE = "000300.SH"
ATR_MULT = 4.0
TOP_N = int(os.environ.get("TOP_N", "5"))     # ★ 只做行业排名前 N 名的行业（主档 5 / 对照 10）

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

# ── 闸门：MA200 ∩ 变盘下行（同更新一）──
_idx["date"] = pd.to_datetime(_idx["date"])
_s = _idx.set_index("date")["close"]
_MA200 = set(_s.index[_s > _s.rolling(200).mean()])
_rg = pd.read_parquet(PRE / "regime_index.parquet")[["date", "down"]]
_rg["date"] = pd.to_datetime(_rg["date"])
_GATE_DAYS = _MA200 & set(_rg.loc[_rg["down"], "date"])
print(f"[u2] 双过滤开门 {len(_GATE_DAYS)} 日 | **只做行业排名前 {TOP_N} 名**", flush=True)

# ── 行业排名（复用）──
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
    """★ 更新二核心：先**过滤**掉行业排名不在前 TOP_N 的候选，再按
    (行业排名 ASC, −COMBO score) 排序 —— 规则 3：行业排名相同则 COMBO 优先。"""
    d = _TODAY[0]

    def ir_of(s):
        v = industry_rank(s, d)
        return 999.0 if v is None else v

    elig = [s for s in open_pool if ir_of(s) <= TOP_N]        # ★ 过滤
    return sorted(elig, key=lambda s: (ir_of(s), -_combo_score(open_pool[s])))


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
