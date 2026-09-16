"""analysis_001 策略 —— **W2 规则的改造版**（结合银河证券「变盘指数」研报）。

与 W2（hs300-enh/analysis_014/volume/update6_combo_asof）的差异**只有两处**：

| 项 | W2 | 本版 |
|---|---|---|
| **入场闸门** | MA200（沪深300 close > MA200） | **变盘指数下行（T′ < 0）** |
| **优先级** | COMBO 优先 | **先行业收益率排名，再 COMBO**（规则 6） |

其余全部保持不变：全局参数 / 信号源 / 池失效 / 持仓离场 / 仓位与执行 / ATR14 口径。

规则逐条（用户 2026-09-16 指定）：
  1 全局参数   ：1,000,000 本金 · 10 坑 · 100,000/仓固定名义 · 15bps · warmup 60
  2 信号源     ：v4 活带 break_up · degree 1~5 · COMBO 非 NaN · **无阀**
  3 入场       ：当日成分 + **变盘指数下行**（T′<0）+ 事件表命中 → t+1 开盘
  4 池失效     ：① 破线 ② 收盘<信号日起最高−4×ATR14 ③ 收盘>close_sig×1.10（任一）
  5 持仓离场   ：① 破线 ② 收盘<**持仓期最高**−4×ATR14(前一日)（任一）
  6 优先级     ：6.1 行业 trailing-20 收益率排名（1=最强，越强越优先）
                 6.2 同排名时按 W2 的 COMBO 规则（score = COMBO − age/45）
                 6.3 即先比行业排名，再比 COMBO
  7 仓位/执行  ：weight=1/n · t 收盘决策 → t+1 开盘成交
  8 ATR14      ：Wilder ewm(α=1/14)，独立缓存
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]                      # trend_range
PRE = HERE / "_precomputed"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

INDEX_CODE = "000300.SH"
ATR_MULT = 4.0
GATE = os.environ.get("GATE", "regime_down")     # regime_down（本版）| ma200（对照 W2）
PRIORITY = os.environ.get("PRIORITY", "industry")  # industry（本版 规则6）| combo（W2 原版）

# ── 事件（v4 活带 + COMBO v2，独立重算）──
_ev = pd.read_parquet(PRE / "events_combo.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[(_ev["degree"] >= 1) & (_ev["degree"] <= 5) & _ev["COMBO"].notna()]
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}
print(f"[analysis_001] 事件 {len(EVENT)}（deg1~5，无阀）", flush=True)

# ── 当日成分 ──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MD = sorted(MEMBERSHIP.keys())

# ── 入场闸门 ──
if GATE == "ma200":
    _c2 = duckdb.connect(str(WAREHOUSE), read_only=True)
    _idx = _c2.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                       "ORDER BY date").fetchdf()
    _c2.close()
    _idx["date"] = pd.to_datetime(_idx["date"])
    _s = _idx.set_index("date")["close"]
    _GATE_DAYS = set(_s.index[_s > _s.rolling(200).mean()])
    print(f"[analysis_001] 闸门=MA200，开门 {len(_GATE_DAYS)} 日", flush=True)
else:
    _rg = pd.read_parquet(PRE / "regime_index.parquet")[["date", "T_prime", "down"]]
    _rg["date"] = pd.to_datetime(_rg["date"])
    _GATE_DAYS = set(_rg.loc[_rg["down"], "date"])          # 变盘指数下行日
    print(f"[analysis_001] 闸门=变盘指数下行(T'<0)，开门 {len(_GATE_DAYS)} 日 "
          f"（占比 {len(_GATE_DAYS)/len(_rg)*100:.1f}%）", flush=True)

# ── 优先级 6.1：个股 → 一级行业 → 行业收益率排名 ──
_si = pd.read_parquet(PRE / "stock_industry.parquet")
_si_piv = _si.pivot(index="date", columns="symbol", values="p2")
_ir = pd.read_parquet(PRE / "ind_ret_rank.parquet")
_rk_piv = _ir.pivot(index="date", columns="p2", values="rank")
print(f"[analysis_001] 行业排名表 {_rk_piv.shape}（{_rk_piv.index.min().date()}~"
      f"{_rk_piv.index.max().date()}）", flush=True)

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
    """该股当日所属一级行业的收益率排名（1=最强）。缺失返回 None。"""
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
    post = hist_df.loc[dates >= sd]
    peak = float(post["high"].max())
    try:
        atr = float(ATR_PIV.at[d, sym])
    except KeyError:
        atr = None
    if c < info["line"]:
        return True                                   # ① 破线
    if atr is not None and atr == atr and atr > 0 and c < peak - ATR_MULT * atr:
        return True                                   # ② 吊灯式回撤（信号日起最高−4ATR）
    if c > info["close_sig"] * 1.10:
        return True                                   # ③ 涨超突破价10%
    return False


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """持仓：破线止损（收盘<信号带线）或 吊灯（收盘<信号日起最高−4×ATR14）。"""
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
    """规则 6：先比行业收益率排名（1=最强最优先），再比 COMBO score（降序）。
    PRIORITY=combo 时退化为 W2 原版（只看 COMBO score）——用于隔离变量做对照。"""
    d = _TODAY[0]
    if PRIORITY == "combo":
        return sorted(open_pool, key=lambda s: _combo_score(open_pool[s]), reverse=True)

    def key(s):
        ir = industry_rank(s, d)
        ir = 999.0 if ir is None else ir                    # 6.1 缺失排最后
        return (ir, -_combo_score(open_pool[s]))            # 6.2/6.3 同排名再比 COMBO

    return sorted(open_pool, key=key)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
