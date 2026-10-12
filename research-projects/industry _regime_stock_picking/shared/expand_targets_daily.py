"""策略侧 expand_to_daily —— 把周频目标持仓铺到**每个交易日**（对标云端同名函数）。

云端 `expand_to_daily`（cloud_code.ipynb L216-236）：
  每个信号日 d0 的 (instrument, weight) 复制到 [d0, d1] 的每个交易日（d1=下一信号日，
  末期用回测末日）；边界日 d1 取**新信号**的权重（keep="last"）。
本脚本同款，产物喂给 `local_weight_backtest.py --targets`。

★ 为什么必须铺到每天：权重引擎的 handle_data_weight_based 语义是
  「今天 context.data 没有该持仓 → 卖掉」；若只在信号日给权重，次日会全部清仓。

用法：PYTHONIOENCODING=utf-8 python expand_targets_daily.py [--targets <parquet>] [--out <parquet>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
CACHE = HERE / "_cache"


def expand_to_daily(hold: pd.DataFrame, cal: pd.DatetimeIndex) -> pd.DataFrame:
    """(date, symbol, weight) 周频 → 逐日。完全对标云端实现（含边界 keep='last'）。"""
    hold = hold.copy()
    hold["date"] = pd.to_datetime(hold["date"])
    sig = sorted(hold["date"].unique())
    frames = []
    for k, d0 in enumerate(sig):
        d1 = sig[k + 1] if k + 1 < len(sig) else cal[-1]
        w = hold.loc[hold["date"] == d0, ["instrument", "weight"]]
        for dt in cal[(cal >= d0) & (cal <= d1)]:
            f = w.copy()
            f["date"] = dt
            frames.append(f)
    out = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["date", "instrument"], keep="last")          # 边界日保留新信号
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    return out[["date", "instrument", "weight"]].sort_values(["date", "instrument"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(CACHE / "weekly_targets_baseline_weekly_indpre_rawpx.parquet"))
    ap.add_argument("--market", default=str(CACHE / "engine_market_weekly_indpre_rawpx.parquet"))
    ap.add_argument("--out", default=str(CACHE / "targets_daily_indpre.parquet"))
    a = ap.parse_args()

    hold = pd.read_parquet(a.targets)
    # 周频目标表列名 → 本脚本口径（signal_date→date, symbol→instrument）
    hold = hold.rename(columns={"signal_date": "date", "symbol": "instrument"})
    mk = pd.read_parquet(a.market, columns=["date"])
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(mk["date"]).unique()))
    # 与云端一致：回测区间内铺满（含首日与末日）
    out = expand_to_daily(hold, cal)
    out.to_parquet(a.out, index=False)
    print(f"周频 {len(hold):,} 行 / {hold['date'].nunique()} 信号日 → 逐日 {len(out):,} 行 / {out['date'].nunique()} 交易日")
    print(f"  → {a.out}")
    # 校验：每个信号周期内权重和应≈1（满仓周）
    ws = out.groupby("date")["weight"].sum()
    print(f"  逐日权重和: 均值 {ws.mean():.4f} | 满仓日(和>0.5) {int((ws>0.5).sum())}/{len(ws)}")


if __name__ == "__main__":
    main()
