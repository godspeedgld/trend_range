"""共享 —— 把预计算的每周目标持仓表包装成组合引擎的 5 个策略接口。

技能要求：多迭代共用逻辑放 `shared/`，各迭代 `strategy.py` 只 import 不内联。
本模块被 `strategy_001/backtest_strategy/strategy.py`（迭代一）与
`backtest_strategy_baseline/strategy.py`（云端原版对照）共用，差异只在加载哪份 targets。

查表口径（与 `build_weekly_targets.py` 的产物对齐）：
  · `_SIGSET[dint]`  = 该信号日的目标持仓集合（**空仓周为空集** → 促使引擎清仓）
  · `_TGT_BY_SYM[symbol][dint]` = 该股当日目标权重

接口语义对齐策略规则：
  entry_signal   t 日 ∈ 目标持仓 → 入开仓池；引擎 t+1 开盘买入 ✓
  exit_check     t 日是信号日 且 ∉ 目标持仓 → 平仓池；t+1 开盘卖出 ✓（非信号日不平仓）
  pool_invalidate 开仓池中的股若已过信号日（t+1 停牌没买进）→ 剔除，不追 ✓
  select_order   权重降序（开仓池最多 6 只，通常全部可开）
  position_weight 查表返回目标权重（行业等权 1/3 × 行业内 vol 倒数）
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "_cache"


def _dint(d) -> int:
    """日期 → 整数（秒级），用于 dict 键（避免 Timestamp / datetime64 哈希不一致）。"""
    return np.datetime64(pd.Timestamp(d)).astype("datetime64[s]").astype(np.int64)


def make_interfaces(slug: str = "regime"):
    """slug: 'regime'（迭代一）| 'baseline'（恒反转 = 云端原版）"""
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    tgts = pd.read_parquet(CACHE / f"weekly_targets_{slug}.parquet")

    sigset: dict[int, set] = {_dint(d): set() for d in plan["signal_date"].unique()}
    by_sym: dict[str, dict[int, float]] = {}
    for r in tgts.itertuples():
        di = _dint(r.signal_date)
        sigset[di].add(r.symbol)
        by_sym.setdefault(r.symbol, {})[di] = float(r.weight)

    def _key(hist_df: pd.DataFrame):
        """从历史 df 取 (symbol, 该股最后一个日期整数)。空 df → None。"""
        if hist_df is None or len(hist_df) == 0:
            return None, None
        try:
            sym = hist_df["symbol"].values[-1]
            d = hist_df["date"].values[-1]
        except (KeyError, IndexError):
            return None, None
        return str(sym), int(np.datetime64(d).astype("datetime64[s]").astype(np.int64))

    # ── 接口① 入场信号 ──
    def entry_signal(hist_df: pd.DataFrame) -> bool:
        sym, di = _key(hist_df)
        if di is None:
            return False
        day = sigset.get(di)
        return day is not None and sym in day

    # ── 接口② 平仓检查 ──
    def exit_check(entry_info: dict, hist_df: pd.DataFrame) -> bool:
        sym, di = _key(hist_df)
        if di is None:
            return True                      # 无历史→平掉（引擎默认语义）
        day = sigset.get(di)
        if day is None:
            return False                     # 非信号日不动仓
        return sym not in day                # 信号日：不在目标 → 平

    # ── 接口③ 开仓池剔除 ──
    def pool_invalidate(hist_df: pd.DataFrame, signal_date) -> bool:
        if hist_df is None or len(hist_df) == 0:
            return True
        cur = np.datetime64(hist_df["date"].values[-1]).astype("datetime64[s]")
        return cur != np.datetime64(pd.Timestamp(signal_date)).astype("datetime64[s]")

    # ── 接口④ 开仓优先选择 ──
    def select_order(open_pool: dict) -> list:
        def rank(sym):
            sd = open_pool[sym].get("signal_date")
            if sd is None:
                return 0.0
            return by_sym.get(sym, {}).get(_dint(sd), 0.0)
        return sorted(open_pool, key=lambda s: -rank(s))

    # ── 接口⑤ 单股权重 ──
    def position_weight(sym: str, n: int, hist_df: pd.DataFrame) -> float:
        _, di = _key(hist_df)
        if di is None:
            return 1.0 / n
        return by_sym.get(sym, {}).get(di, 1.0 / n)

    return entry_signal, exit_check, pool_invalidate, select_order, position_weight
