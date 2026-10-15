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


def build_industry_weekly(sig_dates: list) -> pd.DataFrame:
    """信号周行业面板（成分聚合）。周归属：交易日归到下一个信号日。"""
    import duckdb
    sig_list = ",".join(f"DATE '{pd.Timestamp(d).date()}'" for d in sig_dates)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mkt = con.execute(f"""
        WITH sig AS (SELECT unnest([{sig_list}]) AS s),
        d AS (SELECT DISTINCT date FROM stock_industry_sw_bar1d),
        wk AS (SELECT d.date, (SELECT min(sig.s) FROM sig WHERE sig.s >= d.date) AS week_end
               FROM d WHERE d.date <= (SELECT max(s) FROM sig)),
        daily AS (
            SELECT b.date, cd.industry_level1_name AS ind,
                   SUM(b.volume) AS vol, SUM(b.amount) AS amt,
                   median(b.turn) FILTER (WHERE b.turn > 0) AS med_turn
            FROM stock_bar1d b
            JOIN stock_industry_component_daily cd USING (date, instrument)
            JOIN wk ON wk.date = b.date
            WHERE b.volume IS NOT NULL AND cd.industry_level1_name IS NOT NULL
            GROUP BY 1, 2)
        SELECT wk.week_end AS week, daily.ind,
               SUM(daily.vol) AS vol, SUM(daily.amt) AS amt, AVG(daily.med_turn) AS turn
        FROM daily JOIN wk ON wk.date = daily.date
        GROUP BY 1, 2
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
    sig_dates = sorted(pd.to_datetime(plan["signal_date"]).unique())
    panel = add_crowding(build_industry_weekly(sig_dates))
    panel = panel[["week", "ind", "signal_count"] + [f"{c}_pct" for c in F6]]
    if write:
        panel.to_parquet(OUT, index=False)
        print(f"[crowd] {len(panel):,} 行 / {panel['ind'].nunique()} 行业 / "
              f"{panel['week'].nunique()} 周 → {OUT.name}")
    return panel


if __name__ == "__main__":
    build_panel()
