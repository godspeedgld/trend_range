"""拉取【申万一级行业指数官方量能】到本地仓库（与云端同源）。

背景：本地仓库的行业指数表 `stock_industry_sw_bar1d` **只有 close**，没有量能；
`stock_industry_bar1d` 有量能但只有 L3 层。因此拥挤度因子原先只能用**成分股聚合**近似，
与云端（cn_stock_prefactors 的 sw_level1_*）口径不同 ⇒ sc 在阈值附近翻转。

本脚本把官方 L1 量能拉下来，供 `build_crowding_signals.py` 改读，实现本地=云端同源。

字段：sw_level_index_code / sw_level1_name / sw_level1_volume / sw_level1_amount / sw_level1_turn
（同一 (date, 行业) 下所有个股行值相同 → GROUP BY 去重；AVG 与云端 SQL 一致）

用法：python shared/fetch_industry_l1_volume.py [--start 2015-01-01] [--end 2026-10-15]
产物：shared/_cache/industry_l1_volume_daily.parquet（date, ind_code, ind_name, volume, amount, turn）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
OUT = HERE / "_cache" / "industry_l1_volume_daily.parquet"

SQL = """
SELECT date, sw_level_index_code AS ind_code, sw_level1_name AS ind_name,
       AVG(sw_level1_volume) AS volume, AVG(sw_level1_amount) AS amount,
       AVG(sw_level1_turn)   AS turn
FROM cn_stock_prefactors
WHERE sw_level_index_code IS NOT NULL
  AND sw_level1_volume IS NOT NULL AND sw_level1_amount IS NOT NULL
  AND sw_level1_turn IS NOT NULL
GROUP BY date, sw_level_index_code, sw_level1_name
"""


def fetch(start: str, end: str) -> pd.DataFrame:
    from bigquant import dai
    frames = []
    for y0, y1 in _year_chunks(start, end):
        for attempt in range(3):
            try:
                df = dai.query(SQL, filters={"date": [y0, y1]}).df()
                break
            except Exception as e:                      # 配额/网络 → 退避重试
                print(f"  [{y0}~{y1}] 第 {attempt+1} 次失败: {type(e).__name__} {str(e)[:120]}")
                if attempt == 2:
                    raise
                time.sleep(20 * (attempt + 1))
        print(f"  [{y0}~{y1}] {len(df):,} 行 / {df['ind_code'].nunique()} 行业")
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values(["ind_code", "date"]).reset_index(drop=True)


def _year_chunks(start: str, end: str):
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    for y in range(s.year, e.year + 1):
        y0 = max(pd.Timestamp(f"{y}-01-01"), s)
        y1 = min(pd.Timestamp(f"{y}-12-31"), e)
        yield y0.strftime("%Y-%m-%d"), y1.strftime("%Y-%m-%d")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-10-15")
    ap.add_argument("--windows", default="", help='指定窗口，逗号分隔 "YYYY-MM-DD:YYYY-MM-DD,..."')
    a = ap.parse_args()

    wins = ([w.split(":") for w in a.windows.split(",") if w] if a.windows
            else [[a.start, a.end]])
    got = []
    for w0, w1 in wins:
        df = fetch(w0, w1)
        got.append(df)
        if OUT.exists():                                # 增量合并（配额有限，拉到哪算哪）
            old = pd.read_parquet(OUT)
            df = pd.concat([old, df], ignore_index=True).drop_duplicates(
                subset=["date", "ind_code"], keep="last")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(OUT, index=False)
        print(f"  → 已保存 {len(df):,} 行")
    all_ = pd.concat(got, ignore_index=True).drop_duplicates(subset=["date", "ind_code"])
    print(f"\n✅ 本次 {len(all_):,} 行 / {all_['ind_code'].nunique()} 行业 / "
          f"{all_['date'].min().date()} ~ {all_['date'].max().date()} → {OUT}")

