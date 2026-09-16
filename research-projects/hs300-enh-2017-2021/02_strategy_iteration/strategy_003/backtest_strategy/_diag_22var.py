"""诊断对照：同面板(2015~今) + 22 变量（不含市值）+ 实际离场标签，隔离市值变量贡献。
与 strategy_003 同数据同标签口径（exit_sim），仅候选变量集 22 vs 26。非交付产物。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[3]
SHARED = PROJECT / "shared"
sys.path.insert(0, str(SHARED))

from vol_enhance_v2 import (load_precomp, build_node_plan, active_node_for,  # noqa: E402
                            predict_fit, VOL_VARS)
from plateau_algo import PARAMS as BREAK_PARAMS  # noqa: E402
from exit_rules import exit_triggered  # noqa: E402

CAP_VARS = ["LnCap", "CapVol5d", "CapVol20d", "CapVol45d"]
V22 = [v for v in VOL_VARS if v not in CAP_VARS]

PANEL = PROJECT / "_market_hs300_panel.parquet"
EVENTS, _ = load_precomp(PANEL, SHARED)
NODES = build_node_plan(EVENTS, sorted(EVENTS["date"].unique()), vol_vars=V22)
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): r for r in EVENTS.itertuples()}

MAX_HOLD = 45
TRAILING_DD = 0.10


def entry_signal(hist_df):
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    row = EVENT_MAP.get((sym, d))
    if row is None:
        return False
    node = active_node_for(NODES, d)
    if node is None or not node.get("active"):
        return True
    vars_d = {v: getattr(row, v) for v in node["selected_vars"]}
    fit = predict_fit(node, vars_d)
    if fit is None or np.isnan(fit):
        return False
    return bool(fit > 0)


def exit_check(entry_info, hist_df):
    if len(hist_df) == 0:
        return True
    c = hist_df["close"].iloc[-1]
    peak = entry_info.get("peak", entry_info["entry_price"])
    return exit_triggered(peak, c, entry_info["entry_date"], hist_df["date"].iloc[-1])


def pool_invalidate(hist_df, signal_date):
    if len(hist_df) == 0:
        return True
    if (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(signal_date)).days > BREAK_PARAMS["suppress_days"]:
        return True
    c = hist_df["close"].iloc[-1]
    sig = hist_df.loc[hist_df["date"] == signal_date, "close"]
    return bool(len(sig) and sig.iloc[0] > 0 and c / sig.iloc[0] - 1.0 < -TRAILING_DD)


def select_order(open_pool):
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym, n, hist_df):
    return 1.0 / n
