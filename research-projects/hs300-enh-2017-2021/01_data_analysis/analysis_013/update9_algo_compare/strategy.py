"""更新九 · 统一 A_v2（006更新三）脚手架策略 — 信号源按 env VARIANT 切换，比较两种阻力算法。

脚手架（006 更新三 硬要求，两算法完全一致）：
  开仓：信号日 t 当日成分 + 突破事件 + 沪深300 MA200 硬开关(close>MA200, ≤t) → 次日开盘执行
  池  ：信号 5 自然日超时 / 自信号日回撤>10% 失效（同 009）
  平仓：① 收盘 < 信号线（破线止损=结构证伪）；② 收盘 < 信号日起最高 − 4×ATR14（吊灯）
        ——均 t 收盘触发 → t+1 开盘执行（引擎语义）
  仓位：固定名义 10万 × 10 坑（100 万），最近信号优先，15bps 双边
VARIANT（env）：
  plateau_v4 : 事件=v4_events.parquet（活带水平带突破），degree 1..5，信号线=带 line
  q_pat5     : 事件=quantreg v2 signals 缓存 breakout 行，5 形态过滤，信号线=R
  q_all      : 事件=同上但不过滤形态（全部 close>R 突破）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[6]         # trend_range
PROJ = Path(__file__).resolve().parents[3]         # hs300-enh-2017-2021 项目根
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))
from atr14_precompute import load_atr14          # noqa: E402  (Wilder ATR，006/009 同款口径)

WAREHOUSE = ROOT / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"
_PANEL = PROJ / "_market_hs300_panel.parquet"     # 2015 全史，供 ATR 成熟
INDEX_CODE = "000300.SH"
VARIANT = os.environ.get("VARIANT", "plateau_v4")
MAX_DEGREE = 5
ATR_MULT = 4.0
POOL_TIMEOUT_DAYS = 5
POOL_DD = 0.10


# ── 信号源事件表：symbol -> date -> (line) ──
def _load_events():
    if VARIANT == "plateau_v4":
        p = PROJ / "01_data_analysis/analysis_012/v4_backtest/v4_events.parquet"
        ev = pd.read_parquet(p)
        ev["date"] = pd.to_datetime(ev["date"])
        ev = ev[ev["degree"] <= MAX_DEGREE]
        return {(r.symbol, r.date): float(r.line) for r in ev.itertuples()}
    else:
        p = PROJ / "01_data_analysis/analysis_013/update5_pattern_portfolio/signals_v2_members.parquet"
        s = pd.read_parquet(p)
        s["date"] = pd.to_datetime(s["date"])
        s = s[s["breakout"]].copy()
        if VARIANT == "q_pat5":
            PAT5 = {"旗形", "上升通道收敛", "上升通道发散", "下降通道收敛", "上升三角形"}
            s = s[s["dur_pattern"].isin(PAT5) | s["chan_pattern"].isin(PAT5)]
        return {(r.symbol, r.date): float(r.R) for r in s.itertuples()}


EVENT_MAP = _load_events()
print(f"[{VARIANT}] 事件 {len(EVENT_MAP)} 条", flush=True)

# ── 沪深300 当日成分 + MA200 硬开关（≤t）──
_con = duckdb.connect(str(WAREHOUSE), read_only=True)
_comp = _con.execute("SELECT date, member_code FROM index_component "
                     f"WHERE instrument='{INDEX_CODE}'").fetchdf()
_idx = _con.execute("SELECT date, close FROM index_bar1d "
                    f"WHERE instrument='{INDEX_CODE}' ORDER BY date").fetchdf()
_con.close()
_comp["date"] = pd.to_datetime(_comp["date"])
_idx["date"] = pd.to_datetime(_idx["date"])
MEMBERSHIP = {d: set(g["member_code"]) for d, g in _comp.groupby("date")}
_ALL_MEMBER_DATES = sorted(MEMBERSHIP.keys())
_is = _idx.set_index("date")["close"]
_ma200 = _is.rolling(200).mean()
_GATE_DAYS = set(_is.index[_is > _ma200])      # MA200 硬开关：close > MA200
print(f"[{VARIANT}] MA200 开门日 {len(_GATE_DAYS)}", flush=True)


def members_asof(d) -> set:
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    earlier = [x for x in _ALL_MEMBER_DATES if x <= d]
    return MEMBERSHIP[earlier[-1]] if earlier else set()


def entry_signal(hist_df: pd.DataFrame) -> bool:
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    if sym not in members_asof(d):
        return False
    if (sym, d) not in EVENT_MAP:
        return False
    if d not in _GATE_DAYS:                    # MA200 硬开关（006 更新三同款）
        return False
    return True


def entry_payload(hist_df: pd.DataFrame) -> dict:
    if len(hist_df) == 0:
        return {}
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    return {"line": EVENT_MAP.get((sym, d))}


# ── Wilder ATR(14) 透视（2015 全史预计算 → 2017 已成熟；006/009 同款）──
_ATR = load_atr14(_PANEL, SHARED)
ATR_PIV = _ATR.pivot_table(index="date", columns="symbol", values="atr14").sort_index()


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """破线止损（收盘<信号线）或吊灯（收盘<信号日起最高−4×ATR14）——t 收盘→t+1 执行。"""
    if len(hist_df) == 0:
        return True
    dates = pd.to_datetime(hist_df["date"])
    entry_d = pd.Timestamp(entry_info["entry_date"])
    sig_idx = dates[dates < entry_d].index[-1] if (dates < entry_d).any() else hist_df.index[0]
    sym = hist_df["symbol"].iloc[-1]
    line = (entry_info.get("signal_info") or {}).get("line")
    if line is None:
        line = EVENT_MAP.get((sym, dates.loc[sig_idx]))
    c = float(hist_df["close"].iloc[-1])
    post_high = float(hist_df.loc[sig_idx:, "high"].max())
    d = dates.iloc[-1]
    try:
        a = float(ATR_PIV.at[d, sym])
    except KeyError:
        a = None
    if line is not None and c < line:
        return True
    if a is not None and a == a and a > 0 and c < post_high - ATR_MULT * a:
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
    if len(sig) and sig.iloc[0] > 0 and c / sig.iloc[0] - 1.0 < -POOL_DD:
        return True
    return False


def select_order(open_pool: dict) -> list:
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym, n, hist_df) -> float:
    return 1.0 / n
