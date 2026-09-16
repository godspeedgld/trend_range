"""沪深300指数增强·平台突破 — 引擎 5 接口（算法内联，迭代一原始版本）。

铁律：严禁未来数据。
  - entry_signal 只用 ≤t 日历史；股票池用**当日**沪深300成分（index_component 当日记录）
  - 引擎在 t+1 开盘执行
"""
import numpy as np
import pandas as pd
import duckdb
from pathlib import Path

PARAMS = {"bb_window": 20, "bb_k": 1.0, "p_clear": 4,   # 转折点（表1）
          "m_bins": 10, "q_density": 2,                    # HSAR（表2）
          "break_pct": 0.03, "suppress_days": 5}           # 突破3%/防闪烁5天
LOOKBACK = 252          # 阻力位回溯一年
INDEX_CODE = "000300.SH"
WAREHOUSE = Path(__file__).resolve().parents[5] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"


def load_index_membership() -> dict:
    """返回 {date: set(member_code)}——沪深300 每日成分。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute(
        f"SELECT date, member_code FROM index_component WHERE instrument='{INDEX_CODE}'"
    ).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return {d: set(g["member_code"]) for d, g in df.groupby("date")}


MEMBERSHIP = load_index_membership()
_ALL_MEMBER_DATES = sorted(MEMBERSHIP.keys())


def members_asof(d) -> set:
    """≤d 的最近一次成分记录（当日无记录时取最近历史成分，无未来）。"""
    d = pd.Timestamp(d)
    if d in MEMBERSHIP:
        return MEMBERSHIP[d]
    earlier = [x for x in _ALL_MEMBER_DATES if x <= d]
    return MEMBERSHIP[earlier[-1]] if earlier else set()


def turning_points(df, p=PARAMS):
    ma = df["close"].rolling(p["bb_window"]).mean()
    sd = df["close"].rolling(p["bb_window"]).std()
    ub, lb = ma + p["bb_k"] * sd, ma - p["bb_k"] * sd
    highs, lows = [], []
    direction, hp_i, hp_p, lp_i, lp_p = 0, None, None, None, None
    for i in range(len(df)):
        hi, lo = df["high"].iloc[i], df["low"].iloc[i]
        if direction == 0:
            if not np.isnan(ub.iloc[i]) and hi > ub.iloc[i]:
                direction, hp_i, hp_p = 1, i, hi
            elif not np.isnan(lb.iloc[i]) and lo < lb.iloc[i]:
                direction, lp_i, lp_p = -1, i, lo
        elif direction == 1:
            if hi > hp_p:
                hp_i, hp_p = i, hi
            if not np.isnan(lb.iloc[i]) and lo < lb.iloc[i]:
                if hp_i is not None:
                    highs.append((hp_i, hp_p))
                direction, lp_i, lp_p = -1, i, lo
        else:
            if lo < lp_p:
                lp_i, lp_p = i, lo
            if not np.isnan(ub.iloc[i]) and hi > ub.iloc[i]:
                if lp_i is not None:
                    lows.append((lp_i, lp_p))
                direction, hp_i, hp_p = 1, i, hi
    pts = sorted([(i, pr, "H") for i, pr in highs] + [(i, pr, "L") for i, pr in lows])
    keep = []
    for i, (idx, price, kind) in enumerate(pts):
        if 0 < i and idx - pts[i-1][0] < p["p_clear"]:
            continue
        if i < len(pts)-1 and pts[i+1][0] - idx < p["p_clear"]:
            continue
        keep.append((idx, price, kind))
    return [(i, pr) for i, pr, k in keep if k == "H"], [(i, pr) for i, pr, k in keep if k == "L"]


def resistance_level(highs, p=PARAMS):
    if len(highs) < p["q_density"]:
        return None
    prices = np.array([pr for _, pr in highs])
    lo, hi = prices.min(), prices.max()
    if hi - lo < 1e-12:
        return None
    width = (hi - lo) / p["m_bins"]
    counts = np.zeros(p["m_bins"])
    for pr in prices:
        counts[min(int((pr - lo) / width), p["m_bins"] - 1)] += 1
    cand = np.where(counts >= p["q_density"])[0]
    top = np.where(lo + np.arange(p["m_bins"]) * width >= lo + 2 * (hi - lo) / 3)[0]
    valid = [b for b in cand if b in set(top)]
    if not valid:
        return None
    best = max(valid, key=lambda b: (counts[b], b))
    return lo + (best + 1) * width


def entry_signal(hist_df):
    """① 开仓：转折点+HSAR+收盘>阻力位3% + 当日成分过滤（无未来）。"""
    if len(hist_df) < LOOKBACK:
        return False
    sym, d = hist_df["symbol"].iloc[-1], hist_df["date"].iloc[-1]
    if sym not in members_asof(d):
        return False
    win = hist_df.iloc[-LOOKBACK:]
    highs, _ = turning_points(win, PARAMS)
    res = resistance_level(highs, PARAMS)
    if res is None:
        return False
    return bool(hist_df["close"].iloc[-1] > res * (1 + PARAMS["break_pct"]))


def exit_check(entry_info, hist_df):
    """② 平仓：滚动回撤 10% 或持有超 45 天。"""
    if len(hist_df) == 0:
        return True
    c = hist_df["close"].iloc[-1]
    peak = entry_info.get("peak", entry_info["entry_price"])
    if peak and peak > 0 and c / peak - 1.0 < -0.10:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(entry_info["entry_date"])).days
    return days > 45


def pool_invalidate(hist_df, signal_date):
    """③ 开仓池剔除：信号后 5 日超时或回撤 10%。"""
    if len(hist_df) == 0:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(signal_date)).days
    if days > PARAMS["suppress_days"]:
        return True
    c = hist_df["close"].iloc[-1]
    sig = hist_df.loc[hist_df["date"] == signal_date, "close"]
    if len(sig) and sig.iloc[0] > 0 and c / sig.iloc[0] - 1.0 < -0.10:
        return True
    return False


def select_order(open_pool):
    """④ 开仓优先级：突破时间最近优先。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym, n, hist_df):
    """⑤ 仓位：1/n。"""
    return 1.0 / n
