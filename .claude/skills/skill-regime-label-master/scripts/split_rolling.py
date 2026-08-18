#!/usr/bin/env python
"""滚动训练数据划分（HMM / 机器学习类算法用）。

规范：2 年训练 + 半年验证 + 半年测试，步长 = 测试窗（半年），滚动推进。

用法：
  python split_rolling.py --market-data <csv>                 # 打印窗口
  python split_rolling.py --market-data <csv> --output out.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

TRAIN_DAYS = 504    # 2 年（约 252×2 交易日）
VAL_DAYS = 126      # 半年（约 252/2 交易日）
TEST_DAYS = 126     # 半年


def split_rolling(dates: pd.Series, train_days: int = TRAIN_DAYS,
                  val_days: int = VAL_DAYS, test_days: int = TEST_DAYS) -> list[dict]:
    """按交易日数量切滚动窗口。返回 [{train/val/test 的 start/end 日期字符串}]。"""
    dates = pd.to_datetime(dates).reset_index(drop=True)
    n = len(dates)
    block = train_days + val_days + test_days
    windows = []
    start = 0
    while start + block <= n:
        tr0, tr1 = start, start + train_days - 1
        va0, va1 = tr1 + 1, tr1 + val_days
        te0, te1 = va1 + 1, va1 + test_days
        windows.append({
            "train": [str(dates.iloc[tr0].date()), str(dates.iloc[tr1].date())],
            "val": [str(dates.iloc[va0].date()), str(dates.iloc[va1].date())],
            "test": [str(dates.iloc[te0].date()), str(dates.iloc[te1].date())],
            "n_train": tr1 - tr0 + 1, "n_val": va1 - va0 + 1, "n_test": te1 - te0 + 1,
        })
        start += test_days  # 步长 = 测试窗
    return windows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-data", required=True)
    p.add_argument("--train-days", type=int, default=TRAIN_DAYS)
    p.add_argument("--val-days", type=int, default=VAL_DAYS)
    p.add_argument("--test-days", type=int, default=TEST_DAYS)
    p.add_argument("--output", help="输出 JSON 路径（省略则打印）")
    args = p.parse_args()

    df = pd.read_csv(args.market_data)
    windows = split_rolling(df["date"], args.train_days, args.val_days, args.test_days)
    payload = {"n_windows": len(windows),
               "config": {"train_days": args.train_days, "val_days": args.val_days,
                          "test_days": args.test_days},
               "windows": windows}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"{len(windows)} windows → {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
