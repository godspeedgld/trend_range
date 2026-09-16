"""analysis_014/volume 更新七 — **中证500 池**跑 W2 配方（规则与 W2 逐条一致）。

W2 配方（不动）：v4 活带 deg≤5 事件 + 当日成分 + MA200 硬开关 + COMBO 优先排序
              + 破线/吊灯止损 + 无超时 + 10坑×10万 + 15bps + t收盘→t+1开盘 + 无阀

与 update6_combo_asof/strategy.py 的**唯一差异** = 池子：
  股票池成分  INDEX_CODE  000300.SH → **000905.SH**（中证500）
  事件源      events_combo_v2.parquet → **events_combo_csi500.parquet**（本目录独立标定）
  ATR 面板    _market_hs300_panel.parquet → **_market_csi500_panel.parquet**

MA200 闸门指数由环境变量 GATE_INDEX 控制（默认 000300.SH，与 W2 一致；设 000905.SH 用中证500 自身）：
  · GATE_INDEX=000300.SH  —— "同 W2 完全一致"（大盘 regime 代理仍用沪深300）
  · GATE_INDEX=000905.SH  —— 用被交易指数自身的年线（更贴合标的）
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
sys.path.insert(0, str(HERE))
from atr_csi500 import load_atr_csi500            # noqa: E402  ⚠ 独立缓存，勿用 shared 的

WAREHOUSE = ROOT / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
INDEX_CODE = "000905.SH"                    # 股票池成分 = 中证500
GATE_INDEX = os.environ.get("GATE_INDEX", "000300.SH")   # MA200 闸门指数
ATR_MULT = 4.0
VARIANT = "W2"                              # 本目录只跑 W2（无阀）

_ev = pd.read_parquet(HERE / "events_combo_csi500.parquet")
_ev["date"] = pd.to_datetime(_ev["date"])
_ev = _ev[(_ev["degree"] >= 1) & (_ev["degree"] <= 5)]
_ev = _ev[_ev["COMBO"].notna()]                       # burn-in 事件无 COMBO
EVENT = {(r.symbol, r.date): {"line": float(r.line), "close_sig": float(r.close_sig),
                              "COMBO": float(r.COMBO)} for r in _ev.itertuples()}
print(f"[CSI500/W2] 事件 {len(EVENT)}（池={INDEX_CODE}，闸门={GATE_INDEX}）", flush=True)

_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MD = sorted(MEMBERSHIP.keys())

# ── MA200 硬开关（信号日指数 close > MA200，≤t 无未来）──
_con2 = duckdb.connect(str(WAREHOUSE), read_only=True)
_idx = _con2.execute(f"SELECT date, close FROM index_bar1d WHERE instrument='{GATE_INDEX}' "
                     "ORDER BY date").fetchdf()
_con2.close()
_idx["date"] = pd.to_datetime(_idx["date"])
_is = _idx.set_index("date")["close"]
_GATE_DAYS = set(_is.index[_is > _is.rolling(200).mean()])
print(f"[CSI500/W2] MA200 开门日 {len(_GATE_DAYS)}（{GATE_INDEX}）", flush=True)

_ATR = load_atr_csi500(HERE)
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()

_TODAY = [None]


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
        return True
    if atr is not None and atr == atr and atr > 0 and c < peak - ATR_MULT * atr:
        return True
    if c > info["close_sig"] * 1.10:
        return True
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
    """COMBO 优先（W2 口径：score = COMBO − 突破至今自然日/45，降序）。"""
    def score(s):
        v = open_pool[s]
        age = (_TODAY[0] - pd.Timestamp(v.get("signal_date"))).days if _TODAY[0] else 0
        return float(v.get("COMBO", 0.0)) - age / 45.0
    return sorted(open_pool, key=score, reverse=True)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
