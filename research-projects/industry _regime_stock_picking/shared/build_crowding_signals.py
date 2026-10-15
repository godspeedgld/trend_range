"""行业拥挤度信号（周频）—— strategy_007（反向量能闸门）用的共享预计算件。

口径与 analysis_009 逐字一致（勿漂移）：
  · 行业周度量：stock_bar1d × stock_industry_component_daily 成分聚合（申万 L1·31 个·周频）
      vol = Σ 成分股周成交量；amt = Σ 周成交额；turn = 成分股日换手率(>0)中位数的周均值
  · 6 因子 = {vol, amt, turn, vol_bias, amt_bias, turn_bias} 各自过去 104 周(含当周)滚动百分位
      bias = 近 4 周均 / 近 52 周均 − 1
  · 触发 = 百分位 ≥ 60%；signal_count = 触发数(0..6)
  · 周归属 = 交易日归到「下一个信号日」（与 weekly_plan 对齐）

★ 本文件是 analysis_009 的工程化落盘：把 009 的 crowding_panel.csv 升级为
  shared/_cache/industry_crowding_weekly.parquet（week, ind, signal_count, 各因子百分位），
  供策略 5 接口 O(1) 查表。不改任何冻结件。

用法：python shared/build_crowding_signals.py   （或 import 后调 build_panel()）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                      # trend_range
CACHE = HERE / "_cache"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

W_MAIN = 104
PCT_THR = 0.60
BIAS_SHORT, BIAS_LONG = 4, 52
F6 = ["vol", "amt", "turn", "vol_bias", "amt_bias", "turn_bias"]
OUT = CACHE / "industry_crowding_weekly.parquet"


def build_industry_weekly() -> pd.DataFrame:
    """**全历史周网格**的行业面板（成分聚合）。

    ★ 2026-10-15 修正（重要）：原实现把交易日归到「**信号日列表**」上，导致
      首个信号日（2016-12-30）之前的全部交易日被 `min(sig.s) >= date` 塞进第一周
      （首行=两年巨量块），周序列只有 ~500 行 ⇒ 滚动 104 周窗要等到 ~2017-12 才有真值，
      之前 min_periods=52 不满足 → NaN 被当 0 → **sc=0** ⇒ 2017 年闸门在无信息下乱关。
      改为：**按自然周（周起始日 date_trunc('week')）取该周最后一个交易日为 week_end**，
      覆盖全部交易日历史 ⇒ 滚动窗口有真实历史，2017 起即为有效值。
    """
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mkt = con.execute("""
        WITH d AS (SELECT DISTINCT date FROM stock_industry_sw_bar1d),
        wkd AS (SELECT date, date_trunc('week', date) AS wk_start FROM d),
        wend AS (SELECT wk_start, MAX(date) AS week_end FROM wkd GROUP BY 1),
        dayind AS (
            SELECT wend.week_end AS week, cd.industry_level1_name AS ind, b.date,
                   SUM(b.volume) AS vol, SUM(b.amount) AS amt,
                   median(b.turn) FILTER (WHERE b.turn > 0) AS med_turn
            FROM stock_bar1d b
            JOIN stock_industry_component_daily cd USING (date, instrument)
            JOIN wkd ON wkd.date = b.date
            JOIN wend ON wend.wk_start = wkd.wk_start
            WHERE b.volume IS NOT NULL AND cd.industry_level1_name IS NOT NULL
            GROUP BY 1, 2, 3)
        SELECT week, ind, SUM(vol) AS vol, SUM(amt) AS amt, AVG(med_turn) AS turn
        FROM dayind GROUP BY 1, 2
    """).df()
    con.close()
    return mkt


def add_crowding(base: pd.DataFrame, w: int = W_MAIN) -> pd.DataFrame:
    """6 个拥挤因子（滚动百分位）+ signal_count。"""
    m = base.sort_values(["ind", "week"]).copy()
    g = m.groupby("ind")
    for c in ("vol", "amt", "turn"):
        m[f"{c}_bias"] = g[c].transform(lambda s: s.rolling(BIAS_SHORT).mean()
                                        / s.rolling(BIAS_LONG).mean() - 1)
    for c in F6:
        m[f"{c}_pct"] = g[c].transform(
            lambda s: s.rolling(w, min_periods=w // 2).apply(
                lambda a: (a[-1] >= a).mean(), raw=True))
    m["signal_count"] = (m[[f"{c}_pct" for c in F6]] >= PCT_THR).sum(axis=1)
    return m


def build_panel(write: bool = True) -> pd.DataFrame:
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    sig_dates = set(pd.to_datetime(plan["signal_date"]).unique())
    full = add_crowding(build_industry_weekly())          # ★ 全历史周网格上算滚动百分位
    print(f"[crowd] 全历史周网格 {len(full):,} 行 / {full['week'].nunique()} 周 "
          f"（{full['week'].min().date()} ~ {full['week'].max().date()}）；"
          f"首个非零 sc 周 = {full.loc[full['signal_count'] > 0, 'week'].min().date()}")
    panel = full[full["week"].isin(sig_dates)].copy()     # 只输出信号日（策略查表用）
    panel = panel[["week", "ind", "signal_count"] + [f"{c}_pct" for c in F6]]
    if write:
        panel.to_parquet(OUT, index=False)
        print(f"[crowd] 信号日面板 {len(panel):,} 行 / {panel['ind'].nunique()} 行业 / "
              f"{panel['week'].nunique()} 周 → {OUT.name}")
    return panel


if __name__ == "__main__":
    build_panel()
