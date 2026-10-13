"""index_component **向前**补齐（默认 2010-01-01 ~ 2014-12-31）—— 给分钟数据管线当符号池。

为什么先补它：本地 `index_component` 只从 **2015-01-05** 起，而 PandaData 分钟线拉取
（`pull_min_year_group.py`）的 4 个指数组（沪深300/中证500/中证1000/中证2000）符号池
**全部来自它** ⇒ 不补它，pre-2015 只能拉出「全塞进 rest 组」的畸形分组
（数据能拉全，但分组优先级 / 断点语义全废）。

口径严格按 skill-bigquant-sdk（`references/warehouse-playbook.md` + SKILL.md Part 2）：
  · 列 = `data_tables.md` 的 **cn_stock_index_component 定义列（5 列，禁 SELECT *）**
  · 年分区 `part.parquet` + 主键 `(instrument, member_code, date)` 合并去重（keep=last）
  · 视图重建用**绝对路径 + `as_posix()`**（相对路径在非仓库根 cwd 会失效）
  · **拉前先估 cells**（配额铁律）；分批（按年）+ 断点续拉；失败重试 3 次
  · 采集日一律来自**本地日历缓存**，不额外调 `all_trading_days`

采样（省配额的关键）：
  `--sample month-end`（默认）= 每月**最后一个交易日**。对「当年成分并集」用途完全够，
     ≈ 12 日/年 × ~2,400 成员 × 5 列 ≈ **0.14M cells/年**（5 年 ≈ 0.7M）
  `--sample daily`            = 逐日。完整口径，但与 2015+ 的逐日密度一致，
     ≈ 244 日/年 × 2,400 × 5 ≈ **2.9M cells/年**（5 年 ≈ 14.7M，贵 20×）

用法：
  python pull_index_component_backward.py --dry-run                 # 只估算，不调 API
  python pull_index_component_backward.py                           # 真拉（默认 month-end）
  python pull_index_component_backward.py --sample daily --from-year 2014 --to-year 2010
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DB = ROOT / "bigquant_warehouse.duckdb"
TABLE = "index_component"
SOURCE = "cn_stock_index_component"
CKPT = ROOT / "_index_component_backward_ckpt.json"
CAL_PKL = ROOT.parent / "trading_calendar_cache.pkl"

# data_tables.md：cn_stock_index_component 定义列（5 列）
COLS = ["instrument", "name", "member_code", "member_name", "date"]
PK = ["instrument", "member_code", "date"]
# 与既有本地表一致（refresh_link_tables.py 的 IND_IDX，7 个）
IND_IDX = ["000300.SH", "000905.SH", "000852.SH", "932000.CSI", "399001.SZ", "399006.SZ", "000688.SH"]


def trading_calendar() -> pd.DatetimeIndex:
    """本地日历缓存（1990-12-19 ~ 2026-12-31），不调 API。"""
    d = pickle.load(open(CAL_PKL, "rb"))
    cal = d["calendar"] if isinstance(d, dict) else d
    return pd.DatetimeIndex(sorted(pd.to_datetime(cal)))


def dates_of_year(cal: pd.DatetimeIndex, year: int, sample: str) -> list[str]:
    y = cal[cal.year == year]
    if sample == "daily":
        return [d.strftime("%Y-%m-%d") for d in y]
    # month-end：每月最后一个交易日
    s = pd.Series(y, index=y)
    ends = s.groupby(y.to_period("M")).last()
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in ends.values]


def ingest(df: pd.DataFrame) -> int:
    """按年分区合并去重写入（仓库既有模式）。"""
    if df.empty:
        return 0
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    tdir = ROOT / TABLE
    for y, g in df.groupby("year"):
        out = tdir / f"year={int(y)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            old = pd.read_parquet(out)
            g = pd.concat([old, g.astype(old.dtypes.to_dict(), errors="ignore")],
                          ignore_index=True)
        g = g.drop_duplicates(subset=PK, keep="last")
        g.to_parquet(out, index=False)
    return len(df)


def rebuild_view():
    con = duckdb.connect(str(DB))
    tdir = (ROOT / TABLE).resolve().as_posix()
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{tdir}/**/*.parquet', hive_partitioning=True)")
    con.close()


def est_cells(rows_per_date: int, n_dates: int) -> int:
    return rows_per_date * n_dates * len(COLS)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-year", type=int, default=2014)
    ap.add_argument("--to-year", type=int, default=2010)
    ap.add_argument("--sample", choices=["month-end", "daily"], default="month-end")
    ap.add_argument("--dry-run", action="store_true", help="只估算 cells，不调 API")
    a = ap.parse_args()

    cal = trading_calendar()
    years = list(range(a.from_year, a.to_year - 1, -1))          # 2014 → 2010
    plan = {y: dates_of_year(cal, y, a.sample) for y in years}
    print("=" * 70)
    print(f"index_component 向前补齐  {a.from_year} → {a.to_year}  | 采样 {a.sample}")
    print(f"指数 {len(IND_IDX)} 个：{IND_IDX}")
    print("=" * 70)
    # 用本地**已有**行数估「每日成员数」（2015+ 逐日 ≈2,900；向前年份更少，粗估取 2,900 上界）
    n_member = 2900
    total = 0
    for y in years:
        c = est_cells(n_member, len(plan[y]))
        total += c
        print(f"  {y}: {len(plan[y]):>4} 个采集日 × ~{n_member} 成员 × {len(COLS)} 列 ≈ {c/1e6:6.2f}M cells")
    print(f"  ── 合计 ≈ {total/1e6:.1f}M cells（{a.sample}）")

    if a.dry_run:
        print("\n(--dry-run：未调 API)")
        return 0

    done = set(json.loads(CKPT.read_text())) if CKPT.exists() else set()
    from bigquant import dai                                        # 延后 import
    todo = [y for y in years if str(y) not in done]
    print(f"\n断点已完成 {sorted(done)} | 本轮待拉 {todo}")
    for y in todo:
        dates = plan[y]
        for lo in range(0, len(dates), 20):                         # 分批：20 个日期/批
            batch = dates[lo:lo + 20]
            din = ",".join(f"TIMESTAMP '{d}'" for d in batch)
            inl = ",".join(f"'{i}'" for i in IND_IDX)
            sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
                   f"WHERE instrument IN ({inl}) AND date IN ({din})")
            df = None
            for attempt in range(3):
                try:
                    df = dai.query(sql).df()[COLS]
                    break
                except Exception as e:
                    print(f"  重试 {attempt+1}/3: {str(e)[:120]}")
                    time.sleep(5)
            if df is None:
                print(f"  ✗ {y} 批 {batch[0]} 失败 → 存断点，重跑续传")
                CKPT.write_text(json.dumps(sorted(done)))
                return 1
            n = ingest(df)
            print(f"  {y} {batch[0]}~{batch[-1]}: {len(df):,} 行 → 入库 {n:,}", flush=True)
        done.add(str(y))
        CKPT.write_text(json.dumps(sorted(done)))

    rebuild_view()
    con = duckdb.connect(str(DB), read_only=True)
    r = con.execute(f"SELECT count(*), count(DISTINCT member_code), min(date), max(date), "
                    f"count(DISTINCT date) FROM {TABLE}").fetchone()
    byy = con.execute(f"SELECT year, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 1").fetchall()
    con.close()
    print(f"\n完成：{TABLE} 现 {r[0]:,} 行 / {r[1]:,} 成分股 / {str(r[2])[:10]} ~ {str(r[3])[:10]} "
          f"/ {r[4]:,} 个日期")
    for y, n in byy:
        print(f"  {y}: {n:>10,} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
