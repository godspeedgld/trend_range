"""平台突破共享算法（工程 shared/）——转折点识别 + HSAR + 当日成分。

铁律：严禁未来数据——所有函数只用 ≤t 历史；members_asof 返回 ≤d 最近成分。
供 strategy_001/002/... 复用，各迭代 strategy.py 只 import，不内联。
"""
import numpy as np
import pandas as pd
import duckdb
from pathlib import Path

PARAMS = {"bb_window": 20, "bb_k": 1.0, "p_clear": 4,   # 转折点（长江表1）
          "m_bins": 10, "q_density": 2,                    # HSAR（长江表2）
          "break_pct": 0.03, "suppress_days": 5}           # 突破3%/防闪烁5天
LOOKBACK = 252
INDEX_CODE = "000300.SH"
# shared/plateau_algo.py → 工程 → research-projects → replication → trend_range
# parents[4]=trend_range（含 data_cache）；parents[5] 会跑到 C:\Quant 错一级
WAREHOUSE = Path(__file__).resolve().parents[4] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"


def load_index_membership() -> dict:
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
