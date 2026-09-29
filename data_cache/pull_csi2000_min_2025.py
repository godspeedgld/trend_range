"""拉取中证2000（2025 年当期成分并集）1 分钟线 → 并入 stock_min_1m（2025-01-01~2025-12-31）。

用户 2026-09-29 指定（skill-pandadata-warehouse-main 流程）：
  · 池 = 中证2000 **2025 年内**成分并集（index_component 932000.CSI，point-in-time）
    − **表内 2025 年已有数据的股票**（HS300 全期 + 中证500/1000 2025 已覆盖，重叠不重拉）
  · 区间 = 2025 全年（12 个月）
  · 入库 = 同一张 stock_min_1m（year=2025/month=MM 分区**合并去重**后重写）

2025-09-29 实测规模：并集 2,401 只 − 已有 144 − .BJ 53（接口仅收 SH/SZ，**永久缺口，
记录在案**）= **待拉 2,151 只 ≈ 1.25 亿行 ≈ 1.92 GB**（PandaData 5GB/天配额内一天可完）。

playbook 对齐：月粒度分批 + 每批落盘 + checkpoint 断点；主键 (symbol,date,minute) 去重；
完成后重建视图。与 pull_csi500_min_2025.py 同构，仅换指数与年份。
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date
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
CKPT = OUT / "_pull_csi2000_2025_ckpt.json"
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"   # 借成分表

INDEX = "932000.CSI"                            # 中证2000
YEAR = 2025
START, END = "20250101", "20251231"
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def load_todo() -> tuple[list[str], int, int]:
    """中证2000 2025 并集 − 表内 2025 已有股票。返回 (待拉, 重叠数, BJ缺口数)。"""
    con = duckdb.connect(str(BQ), read_only=True)
    rows = [r[0] for r in con.execute(f"""
        SELECT DISTINCT member_code FROM index_component
        WHERE instrument = '{INDEX}' AND date >= '{YEAR}-01-01' AND date <= '{YEAR}-12-31'
        ORDER BY 1""").fetchall()]
    con.close()
    con = duckdb.connect(str(DDB), read_only=True)
    have = {r[0] for r in con.execute(
        f"SELECT DISTINCT symbol FROM {TABLE} WHERE date LIKE '{YEAR}%'").fetchall()}
    con.close()
    bj = [s for s in rows if s.endswith(".BJ")]
    overlap = len([s for s in rows if s in have])
    todo = [s for s in rows if s not in have and s.endswith((".SH", ".SZ"))]
    return todo, overlap, len(bj) - len([s for s in bj if s in have])


def month_ranges() -> list[tuple[str, str]]:
    out = []
    for m in range(1, 13):
        b = date(YEAR, m, calendar.monthrange(YEAR, m)[1])
        out.append((date(YEAR, m, 1).strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def part_path(m: int) -> Path:
    return OUT / f"year={YEAR}" / f"month={m:02d}" / "part.parquet"


def build_view() -> int:
    con = duckdb.connect(str(DDB))
    glob = str(OUT / "year=*" / "month=*" / "*.parquet").replace("\\", "/")
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    syms, overlap, n_bj = load_todo()
    est = int(len(syms) * 243 * 240)
    print(f"中证2000 {YEAR} 并集 − 表内已有 = {len(syms)} 只"
          f"（重叠跳过 {overlap}，.BJ 缺口 {n_bj} 接口不支持）· {START}~{END}")
    print(f"估算 ≈ {est:,} 行 / ~{est * 15.3 / 1e9:.2f} GB")
    if a.dry_run:
        return

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []
    done_set = set(done)
    t0 = time.time()
    for s, e in month_ranges():
        key = s[:6]
        f = part_path(int(key[4:6]))
        if key in done_set and f.exists():
            print(f"  {key}  跳过（checkpoint 已完成）")
            continue
        t = time.time()
        try:
            df = pd_.get_stock_min(symbol=syms, start_date=s, end_date=e,
                                   fields=FIELDS, frequency="1m")
        except Exception as ex:
            print(f"  {key}  ✗ {type(ex).__name__} {str(ex)[:90]}")
            print("     断点已存，重跑续传")
            return 1
        if df is None or not len(df):
            print(f"  {key}  — 无数据")
            continue
        df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            old = pd.read_parquet(f)
            df = pd.concat([old, df], ignore_index=True)
            df = df.drop_duplicates(subset=["symbol", "date", "minute"], keep="last")
            df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
        done.append(key)
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {key}  {len(df):>10,} 行（合并后 {df['symbol'].nunique()} 只）"
              f" {f.stat().st_size / 1e6:6.1f} MB  {time.time() - t:4.1f}s")

    rows = build_view()
    print("=" * 68)
    print(f"完成：stock_min_1m 现共 {rows:,} 行 · 用时 {(time.time() - t0) / 60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
