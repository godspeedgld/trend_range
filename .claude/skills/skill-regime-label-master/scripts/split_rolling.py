#!/usr/bin/env python
"""递增窗口（expanding + 上限）数据划分——HMM / 机器学习类算法用。

模式（初始 3 年递增，训练集最大 3 年，之后滑动）：
  2015-2017 训练 → 测试 2018   （初始 3 年）
  2016-2018 训练 → 测试 2019   （达 3 年上限后滑动）
  2017-2019 训练 → 测试 2020
  2018-2020 训练 → 测试 2021
  2019-2021 训练 → 测试 2022
  ... 直到数据结束

设计理由：
- 3 年上限：近期市场状态与远期差异大，用最近 3 年训练最贴近当前市场
  （比 5 年更侧重时效性；过老数据作为训练不合适）
- 窗口滑动，始终用最近的 3 年

用法：
  python split_rolling.py --market-data <csv>                 # 打印窗口
  python split_rolling.py --market-data <csv> --output out.json
  python split_rolling.py --market-data <csv> --initial-years 3 --max-years 3
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

INITIAL_TRAIN_YEARS = 3   # 初始训练年数
MAX_TRAIN_YEARS = 3       # 训练集最大年数（上限后滑动）


def split_expanding(dates: pd.Series, initial_train_years: int = INITIAL_TRAIN_YEARS,
                    max_train_years: int = MAX_TRAIN_YEARS) -> list[dict]:
    """按自然年切窗口：初始递增至 max 上限，之后滑动。"""
    dates = pd.to_datetime(dates).reset_index(drop=True)
    years = dates.dt.year
    y0, y1 = int(years.min()), int(years.max())

    windows = []
    for test_year in range(y0 + initial_train_years, y1 + 1):
        tr_start = max(y0, test_year - max_train_years)   # 训练起点（不早于数据起点）
        tr = (years >= tr_start) & (years <= test_year - 1)
        te = years == test_year
        if not tr.any() or not te.any():
            continue
        windows.append({
            "train": [str(dates[tr].iloc[0].date()), str(dates[tr].iloc[-1].date())],
            "test": [str(dates[te].iloc[0].date()), str(dates[te].iloc[-1].date())],
            "n_train": int(tr.sum()), "n_test": int(te.sum()),
            "n_train_years": test_year - tr_start,
        })
    return windows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--market-data", required=True)
    p.add_argument("--initial-years", type=int, default=INITIAL_TRAIN_YEARS)
    p.add_argument("--max-years", type=int, default=MAX_TRAIN_YEARS,
                   help="训练集最大年数（默认 5）")
    p.add_argument("--output", help="输出 JSON 路径（省略则打印）")
    args = p.parse_args()

    df = pd.read_csv(args.market_data)
    windows = split_expanding(df["date"], args.initial_years, args.max_years)
    payload = {"mode": "expanding_capped",
               "n_windows": len(windows),
               "config": {"initial_train_years": args.initial_years,
                          "max_train_years": args.max_years},
               "windows": windows}
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"{len(windows)} windows (expand→cap {args.max_years}y) → {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
