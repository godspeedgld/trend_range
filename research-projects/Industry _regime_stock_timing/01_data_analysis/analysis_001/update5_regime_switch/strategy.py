"""analysis_001 更新五 —— **按研报原意做风格切换**（T′ 符号决定动量 / 反转）。

前四个变体都把变盘指数当「开仓闸门」用，本更新改用**研报原本主张的用法**：

| 项 | 更新一（当闸门） | **更新五（风格开关）** |
|---|---|---|
| **闸门** | MA200 **∩** 变盘指数下行 | **MA200**（保持 W2 原样，不加变盘过滤） |
| **优先级** | 行业收益率排名升序（恒定动量方向） | **T′<0 → 动量（排名升序）；T′>0 → 反转（排名降序）** |
| 同排名 | COMBO（score = COMBO − age/45） | 同左（规则 3 不变） |

其余完全相同：全局参数 · 信号源（v4活带 deg1~5 无阀）· 池失效 · 持仓离场 · 仓位与执行 · ATR14。

**对照设计**（同一脚手架内切换 `PRIORITY_MODE`）：
  · `regime_switch`（主档）—— T′ 符号择时切换 动量/反转
  · `industry`      —— 恒定动量方向（= analysis_001 的 ③ MA200 + 行业优先）
  · `combo`         —— 纯 COMBO（= ① W2 基准）

⚠ 研报用的是**周频/月频调仓**；本工程是**事件驱动**（持仓可达数月），
   T′ 按**日频**符号取值，切换会比研报频繁得多 —— 这是本次要验证的点之一。

预计算：全部复用 `../_precomputed/`（零重算）。
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
PRIORITY_MODE = os.environ.get("PRIORITY_MODE", "regime_switch")   # regime_switch | industry | combo
REGIME_FILE = os.environ.get("REGIME_FILE", "regime_index.parquet")  # 一级版（研报主口径）
SMOOTH_T = int(os.environ.get("SMOOTH_T", "0"))   # >0 时对 T′ 做 N 日均值再取符号（降抖动）

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

# ── 闸门：MA200（★ 保持 W2 原样，不加变盘过滤）──
_idx["date"] = pd.to_datetime(_idx["date"])
_s = _idx.set_index("date")["close"]
_GATE_DAYS = set(_s.index[_s > _s.rolling(200).mean()])

# ── 变盘指数：取 T′ 的符号（风格开关）──
_rg = pd.read_parquet(PRE / REGIME_FILE)[["date", "T_prime"]].copy()
_rg["date"] = pd.to_datetime(_rg["date"])
if SMOOTH_T > 0:
    _rg["T_prime"] = _rg["T_prime"].rolling(SMOOTH_T, min_periods=SMOOTH_T).mean()
_MOMENTUM_DAYS = set(_rg.loc[_rg["T_prime"] < 0, "date"])     # T'<0 → 动量
_REVERSAL_DAYS = set(_rg.loc[_rg["T_prime"] > 0, "date"])     # T'>0 → 反转
print(f"[u5] 闸门=MA200 开门 {len(_GATE_DAYS)} 日 | 变盘指数={REGIME_FILE}"
      f"{f'（T′ {SMOOTH_T}日均值）' if SMOOTH_T else ''} | "
      f"动量日 {len(_MOMENTUM_DAYS)} / 反转日 {len(_REVERSAL_DAYS)} | MODE={PRIORITY_MODE}", flush=True)

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
    if d not in _GATE_DAYS:                    # ★ 只看 MA200
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
    """★ 更新五核心：T′ 符号决定**动量还是反转**方向，再按 COMBO（规则 3）。

      T′ < 0（扰动收敛）→ 动量：行业收益率排名**升序**（最强优先）
      T′ > 0（扰动放大）→ 反转：行业收益率排名**降序**（最弱优先）
    """
    d = _TODAY[0]
    if PRIORITY_MODE == "combo":
        return sorted(open_pool, key=lambda s: _combo_score(open_pool[s]), reverse=True)

    if PRIORITY_MODE == "industry":
        sign = 1.0                                    # 恒定动量方向（= analysis_001 的 ③）
    else:                                             # regime_switch
        sign = 1.0 if d in _MOMENTUM_DAYS else -1.0   # T′<0 → 动量；T′>0 → 反转

    def key(s):
        ir = industry_rank(s, d)
        miss = 1 if ir is None else 0
        irv = 999.0 if ir is None else ir
        return (miss, sign * irv, -_combo_score(open_pool[s]))

    return sorted(open_pool, key=key)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
