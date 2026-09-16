"""analysis_013 — quantreg_sr_algo 分位回归阻力线（Lang2012/渤海证券路线）三标的可视化。

标的（用户指定）：中芯国际 688981.SH / 招商蛇口 001979.SZ / 贵州茅台 600519.SH
时间：2015 至今（以各自数据起点为准：茅台 2015-01 / 蛇口 2015-12 重组上市 / 中芯 2020-07 上市）
算法：shared/quantreg_sr_algo.py 默认参数（N=120, w=5, τ=0.9/0.1, 首日归一100）
口径：忠实（中心极值，研报同款视觉）为主；因果（末端极值确认）并算对照（前视差异记录）

产物：{sym}_lines.csv（逐日 p1/p2/R/S/breakout/形态，两口径）、summary.csv、
      由 build_view.py 生成 result_view.html（每标的独立一张图）
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "shared"))
from quantreg_sr_algo import breakout_signals, rolling_lines  # noqa: E402

HERE = Path(__file__).resolve().parent
TARGETS = {"688981.SH": ("中芯国际", "smic"), "001979.SZ": ("招商蛇口", "shekou"),
           "600519.SH": ("贵州茅台", "gzmt")}
warnings.filterwarnings("ignore")  # statsmodels IterationLimitWarning 刷屏（不影响拟合使用）

def main():
    panel = pd.read_parquet(PROJECT / "_market_hs300_panel.parquet",
                            columns=["date", "symbol", "close"])
    rows = []
    for sym, (name, short) in TARGETS.items():
        g = (panel[panel.symbol == sym]
             .assign(date=lambda d: pd.to_datetime(d["date"]))
             .set_index("date").sort_index())
        # 忠实口径（研报同款）
        sig_f = breakout_signals(rolling_lines(g, causal=False), g["close"])
        # 因果口径（可交易对照）
        sig_c = breakout_signals(rolling_lines(g, causal=True), g["close"])

        out = sig_f[["close", "R", "S", "p1", "p2", "dur_pattern", "chan_pattern"]].copy()
        out.columns = ["close", "R", "S", "p1", "p2", "dur", "chan"]
        out["breakout_f"] = sig_f["breakout"]
        out["breakout_c"] = sig_c.reindex(out.index)["breakout"].fillna(False)
        out.to_csv(HERE / f"{short}_lines.csv",
                   encoding="utf-8-sig")

        bf, bc = out["breakout_f"].sum(), out["breakout_c"].sum()
        rows.append({"symbol": sym, "name": name,
                     "start": out.index.min().date(), "end": out.index.max().date(),
                     "bars": len(out), "valid_line_days": int(out["R"].notna().sum()),
                     "breakout_faithful": int(bf), "breakout_causal": int(bc),
                     "dur_top": out.loc[out["breakout_f"], "dur"].value_counts().head(3).to_dict(),
                     "chan_top": out.loc[out["breakout_f"], "chan"].value_counts().head(3).to_dict()})
        print(f"{name} {sym}: {out.index.min().date()}~{out.index.max().date()} "
              f"有效线{out['R'].notna().sum()}日 | 突破 忠实{bf} 因果{bc}")

    pd.DataFrame(rows).to_csv(HERE / "summary.csv", index=False, encoding="utf-8-sig")
    print("summary.csv 写出")


if __name__ == "__main__":
    main()
