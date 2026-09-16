"""更新三策略 — v4 事件 × COMBO 阀门/优先级（A_v2 引擎 5 变体，env VARIANT 切换）。

脚手架（006更新三款，除闸门外一致）：v4 deg≤5 + 当日成分 + 破线止损(收盘<信号带 line)
+ 4×ATR14 吊灯 + 10坑×10万 + 15bps + t收盘→t+1开盘。**无 MA200**（用户：测 COMBO 单独作用）。

本版三处新规则（用户 09-10 指定）：
  池（无超时）：候选每 t 收盘检查——① 收盘<信号带线(破线) ② 收盘<信号日起最高−4×ATR14
              ③ 收盘>信号日收盘×1.10（涨过头）——任一触发即清出池
  阀门：COMBO>θ 且 RV<3.8（巨量禁区）
  优先级：score = COMBO − 突破至今自然日/45，降序（COMBO 用事件级 expanding 因果值）

VARIANT：V1=无闸+最近优先 | V2=无闸+COMBO优先 | V3=闸θ=0 | V4=θ=0.5 | V5=θ=1（V3-V5 均含 RV<3.8 与 COMBO 优先）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[6]                      # trend_range
PROJ = HERE.parents[3]                      # hs300-enh-2017-2021
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from atr14_precompute import load_atr14          # noqa: E402

WAREHOUSE = ROOT / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
INDEX_CODE = "000300.SH"
ATR_MULT = 4.0
VARIANT = os.environ.get("VARIANT", "V3")
THETA = {"V1": None, "V2": None, "V3": 0.0, "V4": 0.5, "V5": 1.0}[VARIANT]

_ev = pd.read_parquet(HERE / "events_combo.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[_ev["COMBO"].notna()]                       # burn-in 事件无 COMBO
if THETA is not None:
    _ev = _ev[(_ev["COMBO"] > THETA) & (_ev["RV"] < 3.8)]
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}
print(f"[{VARIANT}] 事件 {len(EVENT)}（θ={THETA}）", flush=True)

_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MD = sorted(MEMBERSHIP.keys())

_ATR = load_atr14(PROJ / "_market_hs300_panel.parquet", SHARED)
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()

_TODAY = [None]                                       # entry_signal 每日被扫 → 记当前决策日


def members_asof(d) -> set:
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    import bisect
    i = bisect.bisect_right(_ALL_MD, d) - 1
    return MEMBERSHIP[_ALL_MD[i]] if i >= 0 else set()


def entry_signal(hist_df: pd.DataFrame) -> bool:
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    _TODAY[0] = d
    if sym not in members_asof(d):
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
        return False                                  # 事件表查不到（不应发生），保守保留
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


def select_order(open_pool: dict) -> list:
    if VARIANT == "V1":                               # 最近信号优先（对照）
        return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)
    def score(s):
        v = open_pool[s]
        age = (_TODAY[0] - pd.Timestamp(v.get("signal_date"))).days if _TODAY[0] else 0
        return float(v.get("COMBO", 0.0)) - age / 45.0
    return sorted(open_pool, key=score, reverse=True)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
