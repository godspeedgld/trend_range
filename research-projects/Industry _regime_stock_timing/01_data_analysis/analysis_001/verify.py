"""analysis_001 对账 —— 本目录**独立重算**的产物 vs hs300-enh-2017-2021 的旧产物。

用户要求 11：突破/ATR/COMBO 全部重新计算，算完比较一下是否正确。

对账口径（逐值）：
  L1 panel        vs _market_hs300_panel.parquet
  L2 atr14        vs shared/atr14_panel.parquet
  L3 v4_events    vs analysis_012/v4_backtest/v4_events.parquet
  L4 events_combo vs analysis_014/volume/update6_combo_asof/events_combo_v2.parquet
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
HS = ROOT / "research-projects/hs300-enh-2017-2021"
PRE = HERE / "_precomputed"

OK, BAD = "✓", "✗"


def _rep(name, n_new, n_old, n_int, note=""):
    flag = OK if note == "" else BAD
    print(f"  {flag} {name:<16} 新 {n_new:>9,} | 旧 {n_old:>9,} | 交集 {n_int:>9,}  {note}")


def main():
    print("=" * 78)
    print("analysis_001 重算对账（vs hs300-enh-2017-2021）")
    print("=" * 78)

    # ── L1 panel ──
    a = pd.read_parquet(PRE / "panel.parquet")
    b = pd.read_parquet(HS / "_market_hs300_panel.parquet")
    for d in (a, b):
        d["date"] = pd.to_datetime(d["date"])
    m = a.merge(b, on=["date", "symbol"], suffixes=("_n", "_o"))
    print("\nL1 panel")
    _rep("行数", len(a), len(b), len(m))
    for c in ["open", "high", "low", "close", "volume", "amount", "turn", "total_market_cap"]:
        d = (m[f"{c}_n"] - m[f"{c}_o"]).abs().max()
        print(f"     {c:<18} max|Δ| = {d:.3e}  {OK if (d == 0 or d < 1e-9) else BAD}")

    # ── L2 atr14 ──
    a = pd.read_parquet(PRE / "atr14.parquet")
    b = pd.read_parquet(HS / "shared/atr14_panel.parquet")
    for d in (a, b):
        d["date"] = pd.to_datetime(d["date"])
    m = a.merge(b, on=["date", "symbol"], suffixes=("_n", "_o"))
    d = (m["atr14_n"] - m["atr14_o"]).abs().max()
    print("\nL2 atr14")
    _rep("行数", len(a), len(b), len(m))
    print(f"     atr14              max|Δ| = {d:.3e}  {OK if (d == 0 or d < 1e-9) else BAD}")

    # ── L3 v4_events ──
    # ⚠ 同日同股可有多条事件（不同 degree = 不同阻力带）→ 必须先按
    #   (symbol, date, degree desc) 规范化去重，否则 merge 是多对多、差异是假象。
    def _dd(d):
        return (d.sort_values(["symbol", "date", "degree"], ascending=[True, True, False])
                 .drop_duplicates(["symbol", "date"], keep="first").reset_index(drop=True))

    a = _dd(pd.read_parquet(PRE / "v4_events.parquet"))
    b = _dd(pd.read_parquet(HS / "01_data_analysis/analysis_012/v4_backtest/v4_events.parquet"))
    for d in (a, b):
        d["date"] = pd.to_datetime(d["date"])
    ka = set(zip(a.symbol, a.date))
    kb = set(zip(b.symbol, b.date))
    print("\nL3 v4_events（规范化去重后）")
    _rep("行数", len(a), len(b), len(ka & kb),
         "" if ka == kb else f"仅本 {len(ka-kb)} / 仅旧 {len(kb-ka)}")
    m = a.merge(b, on=["symbol", "date"], suffixes=("_n", "_o"))
    for c in ["close_sig", "line", "lo", "hi"]:
        d = (m[f"{c}_n"] - m[f"{c}_o"]).abs().max()
        print(f"     {c:<18} max|Δ| = {d:.3e}  {OK if (d == 0 or d < 1e-9) else BAD}")
    print(f"     degree 完全一致      {OK if (m.degree_n == m.degree_o).all() else BAD}")
    print(f"     sig_i  最大差        {(m.sig_i_n - m.sig_i_o).abs().max():.0f}")

    # ── L4 events_combo ──
    a = pd.read_parquet(PRE / "events_combo.parquet")
    b = pd.read_parquet(HS / "01_data_analysis/analysis_014/volume/update6_combo_asof/events_combo_v2.parquet")
    for d in (a, b):
        d["date"] = pd.to_datetime(d["date"])
    ka = set(zip(a.symbol, a.date))
    kb = set(zip(b.symbol, b.date))
    print("\nL4 events_combo（deg1~5 标定后）")
    _rep("行数", len(a), len(b), len(ka & kb),
         "" if ka == kb else f"仅本 {len(ka-kb)} / 仅旧 {len(kb-ka)}")
    m = a.merge(b, on=["symbol", "date"], suffixes=("_n", "_o"))
    for c in ["COMBO", "RV", "UDVR"]:
        d = (m[f"{c}_n"] - m[f"{c}_o"]).abs().max()
        print(f"     {c:<18} max|Δ| = {d:.3e}  {OK if (d == 0 or d < 1e-9) else BAD}")
    na, nb = a.COMBO.notna().sum(), b.COMBO.notna().sum()
    print(f"     COMBO 有效数        {na:,} vs {nb:,}  {OK if na == nb else BAD}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
