"""strategy_002 — 平台突破 + 量价信息增强（预计算查表式执行）。

迭代二相对迭代一只加开仓过滤；开仓/平仓/仓位/入选规则与 strategy_001 完全一致。
量价增强（长江研报§1.4）：
  - 预计算（shared/vol_enhance.py，缓存 parquet/json）：突破事件表（22变量+45日收益+实现日）、
    半年节点计划（逐步回归选变量 + 过去500交易日回归固定系数）
  - 铁律：严禁未来数据。节点样本只取 ret45_date < t（排除 t-45~t-1 未实现突破）；
    节点 t 当日仍用上期节点，新节点 t+1 生效
  - 运行时只查表：突破日查 EVENT_MAP、拟合收益查 NODE 固定系数
  - 无有效节点期间（样本不足）不设过滤，突破直接入池（等同迭代一行为）

本文件只 import 共享模块，不内联算法。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[3]
SHARED = PROJECT / "shared"
sys.path.insert(0, str(SHARED))

from vol_enhance import (load_precomp, active_node_for, predict_fit,  # noqa: E402
                         RESELECT_INTERVAL, COEF_WINDOW, MIN_SAMPLES)
from plateau_algo import PARAMS as BREAK_PARAMS  # noqa: E402

MARKET_CSV = PROJECT / "_market_hs300_full.csv"
EVENTS, NODES = load_precomp(MARKET_CSV, SHARED)
# 突破日查表：{(symbol, date) -> 事件行}（预计算变量/45日收益）
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): r for r in EVENTS.itertuples()}

MAX_HOLD = 45                 # 45 日持有期
TRAILING_DD = 0.10            # 滚动回撤 10%


def entry_signal(hist_df: pd.DataFrame) -> bool:
    """① 开仓：平台突破（同日成分 + 转折点 + HSAR + 突破3%，查预计算表）+ 量价增强过滤。"""
    if len(hist_df) == 0:
        return False
    sym = hist_df["symbol"].iloc[-1]
    d = pd.Timestamp(hist_df["date"].iloc[-1])
    row = EVENT_MAP.get((sym, d))
    if row is None:
        return False                      # 非突破日（含非当日成分/未达突破阈值）
    node = active_node_for(NODES, d)
    if node is None or not node.get("active"):
        return True                       # 无过滤器（样本不足期）→ 等同迭代一
    vars_d = {v: getattr(row, v) for v in node["selected_vars"]}
    fit = predict_fit(node, vars_d)
    if fit is None or np.isnan(fit):
        return False                      # 变量缺失/NaN → 保守判无效
    return bool(fit > 0)                  # 拟合 45 日收益 ≤0 → 假突破，不入开仓池


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓：滚动回撤 10% 或持有超 45 天（与 strategy_001 一致）。"""
    if len(hist_df) == 0:
        return True
    c = hist_df["close"].iloc[-1]
    peak = entry_info.get("peak", entry_info["entry_price"])
    if peak and peak > 0 and c / peak - 1.0 < -TRAILING_DD:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(entry_info["entry_date"])).days
    return days > MAX_HOLD


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """③ 开仓池剔除（与 strategy_001 一致）：5 日超时或回撤 10%。"""
    if len(hist_df) == 0:
        return True
    days = (pd.Timestamp(hist_df["date"].iloc[-1]) - pd.Timestamp(signal_date)).days
    if days > BREAK_PARAMS["suppress_days"]:
        return True
    c = hist_df["close"].iloc[-1]
    sig = hist_df.loc[hist_df["date"] == signal_date, "close"]
    if len(sig) and sig.iloc[0] > 0 and c / sig.iloc[0] - 1.0 < -TRAILING_DD:
        return True
    return False


def select_order(open_pool: dict) -> list:
    """④ 开仓优先级（与 strategy_001 一致）：突破时间最近优先。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：1/n。"""
    return 1.0 / n
