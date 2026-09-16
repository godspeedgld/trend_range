"""更新二前置检查 — shared/quantreg_sr_algo.py 与渤海复现包 reference_implementation.py
严格一致性验证（用户要求：用之前必须检查，不一致修改）。

比对项（沪深300 指数全史，忠实+因果两口径）：
  rolling_lines 逐值（p1/p2/R/S）| breakout 事件 | dur/chan 形态标签
参数化改造（patterns/chan_bounds 可调阈值，默认研报表1/表2）后必须与原实现零差异。
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # hs300-enh-2017-2021
REPL = PROJ.parents[1] / "渤海证券-指数技术择时之一-压力线与支撑线的识别算法及应用" / "03_backtest_strategy"
sys.path.insert(0, str(PROJ / "shared"))
sys.path.insert(0, str(REPL))
warnings.filterwarnings("ignore")

import quantreg_sr_algo as q          # noqa: E402
import reference_implementation as ri  # noqa: E402


def main():
    mkt = pd.read_parquet(REPL.parent / "market_broad5.parquet")
    g = mkt[mkt.symbol == "000300.SH"].set_index("date").sort_index()
    ok_all = True
    for causal in (False, True):
        a = q.breakout_signals(q.rolling_lines(g, causal=causal), g["close"])
        b = ri.breakout_signals(ri.rolling_lines(g, causal=causal), g["close"])
        for col in ("p1", "p2", "R", "S"):
            same = np.allclose(a[col].fillna(-9), b[col].fillna(-9), atol=0, rtol=0)
            ok_all &= same
            assert same, f"{col} 不一致 (causal={causal})"
        for col in ("breakout", "dur_pattern", "chan_pattern"):
            same = (a[col].fillna(False) == b[col].fillna(False)).all() if col == "breakout" \
                else (a[col].fillna("X") == b[col].fillna("X")).all()
            ok_all &= bool(same)
            assert same, f"{col} 不一致 (causal={causal})"
        print(f"causal={causal}: p1/p2/R/S 逐值相等 | 突破事件相等(n={int(a['breakout'].sum())}) | "
              f"dur/chan 标签全等 ✔")

    # 参数化回归测试：显式传默认 patterns/bounds 必须与不传一致
    a1 = q.breakout_signals(q.rolling_lines(g.iloc[-500:], causal=True), g["close"].iloc[-500:])
    a2 = q.breakout_signals(q.rolling_lines(g.iloc[-500:], causal=True), g["close"].iloc[-500:],
                            patterns=q.DURATION_PATTERNS, chan_bounds=q.DEFAULT_CHAN_BOUNDS)
    same = (a1["dur_pattern"] == a2["dur_pattern"]).all() and (a1["chan_pattern"] == a2["chan_pattern"]).all()
    assert bool(same), "参数化显式传默认值与省略不一致"
    print("参数化（显式传默认阈值）与省略等价 ✔")
    print("\n【结论】shared/quantreg_sr_algo.py 与复现包实现完全一致，参数化改造向后兼容。")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
