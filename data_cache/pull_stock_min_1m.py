"""拉取 HS300 历史并集成分股的 1 分钟线 → 本地 Parquet 仓库（PandaData）

用法：
    python data_cache/pull_stock_min_1m.py                 # 增量（已存在的分区跳过）
    python data_cache/pull_stock_min_1m.py --force 2026    # 强制重拉指定年份

设计（对齐 skill-pandadata-warehouse-main）：
  · **主循环按年份**，年内按月分批 —— 用户要求"按年份一批一批拉，不要按股票"；
    再按月切一刀纯粹是内存与断点考虑（单月 668 只 ≈ 340 万行 / 5 秒，一年 3900 万行
    一次性进内存要 ~3GB，且中断会白拉）
  · **每批立即落盘** + 写 _progress.json —— 断点续传，绝不重蹈 BigQuant 那次"拉完才
    落盘、中断全废"的覆辙
  · 落盘到 year=/month= hive 分区；行按 (symbol, date, minute) 排序 + 小 row group，
    这样按标的或按日期查都能靠 Parquet 行组统计跳过绝大多数数据
  · **完整保留接口返回的 11 列**（含 `datetime`）—— 不裁剪字段，与源接口契约一致
  · 完成后重建 DuckDB 视图 + _meta.json 清单

数据事实（2026-09-18 实测，见 memory pandadata-minute-estimate）：
  · 接口最早 2005-01-04；每天 240 根；**返回是倒序的（最新在前）→ 落盘前必须 sort**
  · 实测吞吐 ~63.8 万行/秒；668 只 × 2025-01 至今 ≈ 6700 万行 / 1.4GB Parquet
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
SKILL = REPO / ".claude/skills/skill-pandadata-api-main/scripts"
sys.path.insert(0, str(SKILL))

WAREHOUSE = HERE / "pandadata_warehouse"
TABLE = "stock_min_1m"
OUT = WAREHOUSE / TABLE
CKPT = OUT / "_progress.json"
META = OUT / "_meta.json"
DDB = WAREHOUSE / "warehouse.duckdb"
MEMBERS = HERE / "_hs300_members.json"

DEFAULT_START_YEAR, DEFAULT_END_YEAR = 2025, 2026
# 接口返回的全部 11 列，一列不裁（21.9 字节/行的体积实测就是按这 11 列测的）
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def load_symbols() -> list[str]:
    syms = json.loads(MEMBERS.read_text(encoding="utf-8"))
    if not isinstance(syms, list) or not syms:
        raise SystemExit(f"成分股缓存无效：{MEMBERS}")
    return sorted(set(syms))


def month_ranges(year: int, today: date) -> list[tuple[str, str]]:
    """(start, end) 列表，YYYYMMDD；最后一个月截到今天

    ⚠ 月末必须用 calendar.monthrange 取真实天数 —— 曾经把 2 月写死成 28 号，
    结果**闰年 2/29 整天被吃掉**（2024-02-29 就这样丢过一次，接口其实有数据）
    """
    out = []
    for m in range(1, 13):
        a = date(year, m, 1)
        b = date(year, m, calendar.monthrange(year, m)[1])
        if a > today:
            break
        out.append((a.strftime("%Y%m%d"), min(b, today).strftime("%Y%m%d")))
    return out


def part_path(year: int, month: int) -> Path:
    return OUT / f"year={year}" / f"month={month:02d}" / "part.parquet"


def build_view():
    """重建 DuckDB 视图（hive 分区：year / month 直接可用）"""
    con = duckdb.connect(str(DDB))
    glob = str(OUT / "year=*" / "month=*" / "*.parquet").replace("\\", "/")
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def write_meta(rows: int, t0: float):
    parts = sorted(OUT.glob("year=*/month=*/part.parquet"))
    META.write_text(json.dumps({
        "table": TABLE,
        "source": "panda_data.get_stock_min",
        "frequency": "1m",
        "universe": {"name": "HS300 历史并集", "cache": str(MEMBERS), "n_symbols": len(load_symbols())},
        "fields_requested": FIELDS,
        "note": "接口 11 列完整落盘，未裁剪字段；行按 (symbol,date,minute) 升序",
        "partition": "year / month",
        "coverage": {
            "first": min(p.parent.parent.name.split("=")[1] + "-" + p.parent.name.split("=")[1]
                         for p in parts) if parts else None,
            "last": max(p.parent.parent.name.split("=")[1] + "-" + p.parent.name.split("=")[1]
                        for p in parts) if parts else None,
        },
        "partitions": [str(p.relative_to(OUT)).replace("\\", "/") for p in parts],
        "total_rows": rows,
        "duckdb": str(DDB),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_sec": round(time.time() - t0, 1),
    }, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=DEFAULT_START_YEAR, help="起始年")
    ap.add_argument("--end", type=int, default=DEFAULT_END_YEAR, help="结束年")
    ap.add_argument("--force", type=int, nargs="*", default=[], help="强制重拉的年份")
    args = ap.parse_args()

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    syms = load_symbols()
    today = date.today()
    OUT.mkdir(parents=True, exist_ok=True)
    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else {}
    t0 = time.time()
    print(f"HS300 历史并集 {len(syms)} 只 · {args.start}~{args.end} · "
          f"已落盘 {len(done)} 批\n" + "=" * 68)

    for year in range(args.start, args.end + 1):
        force = year in args.force
        for a, b in month_ranges(year, today):
            key = f"{a[:6]}"
            f = part_path(year, int(a[4:6]))
            if f.exists() and not force:
                print(f"  {key}  跳过（已存在 {f.stat().st_size/1e6:.0f} MB）")
                continue
            t = time.time()
            try:
                df = pd_.get_stock_min(symbol=syms, start_date=a, end_date=b,
                                       fields=FIELDS, frequency="1m")
            except Exception as e:
                print(f"  {key}  ✗ 失败：{type(e).__name__} {str(e)[:90]}")
                print(f"     已拉部分保留在盘上，修好后重跑本脚本即可续传")
                return 1
            if df is None or not len(df):
                print(f"  {key}  — 无数据（非交易日区间）")
                continue
            # ★ 接口返回是倒序的 → 必须排序；按 symbol 聚簇也让行组统计能按标的下推
            df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
            f.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
            done[key] = len(df)
            CKPT.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  {key}  {len(df):>9,} 行  {f.stat().st_size/1e6:6.1f} MB  "
                  f"{time.time()-t:4.1f}s  ({df['symbol'].nunique()} 只 / {df['date'].nunique()} 天)")

    rows = build_view()
    write_meta(rows, t0)
    size = sum(p.stat().st_size for p in OUT.glob("year=*/month=*/part.parquet"))
    print("=" * 68)
    print(f"落盘 {size/1e9:.2f} GB / {rows:,} 行 · 总用时 {(time.time()-t0)/60:.1f} 分钟")
    print(f"DuckDB 视图已建：{DDB}  →  SELECT * FROM {TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
