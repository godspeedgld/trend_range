"""strategy_003 — 平台突破 + 量价信息增强 v2（26 变量含市值，数据延长至今）。

迭代三相对迭代二**只换数据与变量集**，规则/参数/预计算方式完全保留：
  - 数据：宽表面板 _market_hs300_panel.parquet（2015~今，stock_bar1d 锚 + stock_valuation 市值，
    按 warehouse-playbook 宽表模式查询导出）
  - 变量：22 → **26 个**（补全市值 4 个：LnCap/CapVol5d/20d/45d，本地已有 total_market_cap）
  - 过滤/节点/开平仓/仓位/入选：与 strategy_002 完全一致（shared/vol_enhance_v2.py 查表执行）

铁律：严禁未来数据。样本只取 ret45_date < t（排除 t-45~t-1 未实现）；
节点 t 当日用上期、t+1 生效；无有效节点期等同迭代一（不设过滤）。
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

from vol_enhance_v2 import load_precomp, active_node_for, predict_fit  # noqa: E402
from plateau_algo import PARAMS as BREAK_PARAMS  # noqa: E402
from exit_rules import exit_triggered  # noqa: E402

MARKET_CSV = PROJECT / "_market_hs300_panel.parquet"
EVENTS, NODES = load_precomp(MARKET_CSV, SHARED)
EVENT_MAP = {(r.symbol, pd.Timestamp(r.date)): r for r in EVENTS.itertuples()}

MAX_HOLD = 45                 # 45 日持有期
TRAILING_DD = 0.10            # 滚动回撤 10%


def entry_signal(hist_df: pd.DataFrame) -> bool:
    """① 开仓：平台突破（查预计算表）+ 量价增强 v2 过滤（26 变量固定系数拟合>0）。"""
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


def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
    """② 平仓：滚动回撤 10% 或持有超 45 天（离场规则见 shared/exit_rules.py 单一事实源）。"""
    if len(hist_df) == 0:
        return True
    c = hist_df["close"].iloc[-1]
    peak = entry_info.get("peak", entry_info["entry_price"])
    return exit_triggered(peak, c, entry_info["entry_date"], hist_df["date"].iloc[-1])


def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
    """③ 开仓池剔除（同 strategy_002）：5 日超时或回撤 10%。"""
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
    """④ 开仓优先级（同 strategy_002）：突破时间最近优先。"""
    return sorted(open_pool, key=lambda s: open_pool[s].get("signal_date"), reverse=True)


def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
    """⑤ 仓位：1/n。"""
    return 1.0 / n
