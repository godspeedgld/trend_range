"""拉取中证2000（2026 年当期成分并集）1 分钟线 → 并入 stock_min_1m（2026-01-01~2026-09-24）。

用户 2026-09-28 指定（skill-pandadata-warehouse-main 流程）：
  · 池 = 中证2000 **2026 年内**成分并集（index_component 932000.CSI，point-in-time）
    − **表内 2026 年已有数据的股票**（HS300 全期 + 中证500 2026 已在，重叠不重拉）
  · 区间 = 2026-01-01 ~ 2026-09-24（与此前口径一致，避开当日盘中快照）
  · 入库 = 同一张 stock_min_1m（year/month 分区**合并去重**后重写该月文件）

playbook 对齐：月粒度分批 + 每批落盘 + checkpoint 断点；主键 (symbol,date,minute) 去重；
完成后重建视图 + _meta.json + 校验 + fresh API 抽样。
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
CKPT = OUT / "_pull_csi2000_2026_ckpt.json"
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"   # 借成分表

INDEX = "932000.CSI"                            # 中证2000
START, END = "20260101", "20260924"
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def load_todo() -> list[str]:
    """中证2000 2026 并集 − 表内 2026 已有股票。

    ★ 必须 filter 掉 .BJ：PandaData get_stock_min 只收 SH/SZ 后缀（实测传 920001.BJ
      直接报「请求参数值格式错误: 后缀必须为SH或SZ」）——中证2000 池含不少北交所股。
    """
    con = duckdb.connect(str(BQ), read_only=True)
    rows = con.execute(f"""
        SELECT DISTINCT member_code FROM index_component
        WHERE instrument = '{INDEX}' AND date >= '2026-01-01' AND date <= '2026-09-24'
        ORDER BY 1""").fetchall()
    con.close()
    con = duckdb.connect(str(DDB), read_only=True)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM stock_min_1m WHERE date LIKE '2026%'").fetchall()}
    con.close()
    return [r[0] for r in rows if r[0] not in have and r[0].endswith((".SH", ".SZ"))]


def month_ranges() -> list[tuple[str, str]]:
    out = []
    for m in range(1, 10):
        b = min(date(2026, m, calendar.monthrange(2026, m)[1]), date(2026, 9, 24))
        out.append((date(2026, m, 1).strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def part_path(m: int) -> Path:
    return OUT / "year=2026" / f"month={m:02d}" / "part.parquet"


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

    syms = load_todo()
    print(f"中证2000 2026 并集 − 表内已有 = {len(syms)} 只 · {START}~{END}")
    if a.dry_run:
        return

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    done = json.loads(CKPT.read_text(encoding="utf-8")) if CKPT.exists() else []
    done_set = set(done)
    t0 = time.time()
    total = 0
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
        # ★ 合并既有分区，主键去重后重写
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            old = pd.read_parquet(f)
            df = pd.concat([old, df], ignore_index=True)
            df = df.drop_duplicates(subset=["symbol", "date", "minute"], keep="last")
            df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
        total += len(df)
        done.append(key)
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {key}  {len(df):>10,} 行（合并后 {df['symbol'].nunique()} 只）"
              f" {f.stat().st_size/1e6:6.1f} MB  {time.time()-t:4.1f}s")

    rows = build_view()
    print("=" * 68)
    print(f"完成：stock_min_1m 现共 {rows:,} 行 · 用时 {(time.time()-t0)/60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
