"""拉取中证1000 并集缺口成分股估值（cn_stock_valuation，2015-01-01 至今）→ 入库 stock_valuation

与 pull_csi1000_bar1d.py 同构：待拉清单 = stock_bar1d 已有 − stock_valuation 已有
（即刚扩容的 1897 只中证1000 成分）；列 = data_tables.md cn_stock_valuation 定义列
（与本地表 16 数据列一致，显式 SELECT 不用 SELECT *）。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
TABLE = "stock_valuation"
SOURCE = "cn_stock_valuation"
BATCH = 100
CKPT = ROOT / "_pull_csi1000_val_ckpt.json"
START, END = "2015-01-01", "2026-08-24"

COLS = ["date", "instrument", "total_market_cap", "float_market_cap", "dividend_yield_ratio",
        "pe_ttm", "pe_leading", "pe_trailing", "pb", "ps_ttm", "ps_leading", "ps_trailing",
        "pcf_net_ttm", "pcf_net_leading", "pcf_op_ttm", "pcf_op_leading"]


def load_todo() -> list[str]:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    rows = con.execute("""
        SELECT DISTINCT instrument FROM stock_bar1d s
        WHERE NOT EXISTS (SELECT 1 FROM stock_valuation v WHERE v.instrument = s.instrument)
        ORDER BY 1""").fetchall()
    con.close()
    return [r[0] for r in rows]


def pull_batch(syms: list[str]) -> pd.DataFrame | None:
    from bigquant import dai
    in_list = ",".join(f"'{s}'" for s in syms)
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE instrument IN ({in_list}) AND date >= '{START}' AND date <= '{END}'")
    for attempt in range(3):
        try:
            return dai.query(sql).df()[COLS]
        except Exception as e:
            print(f"    重试 {attempt+1}/3: {str(e)[:100]}")
            time.sleep(5)
    return None


def write_partitions(df: pd.DataFrame):
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    table_dir = ROOT / TABLE
    for year, grp in df.groupby("year"):
        out = table_dir / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            old = pd.read_parquet(out)
            grp = pd.concat([old, grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def rebuild_view():
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n, rows, d0, d1 = con.execute(
        f"SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM {TABLE}").fetchone()
    con.close()
    return n, rows, str(d0)[:10], str(d1)[:10]


def main():
    todo = load_todo()
    done = json.loads(CKPT.read_text()) if CKPT.exists() else []
    done_set = set(done)
    todo = [s for s in todo if s not in done_set]
    print(f"估值待拉: {len(todo)} 只（已完成 {len(done_set)}）· {START}~{END} · 批 {BATCH}")
    total = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        t0 = time.time()
        df = pull_batch(batch)
        if df is None:
            print(f"  批 {i//BATCH+1} 失败，断点已存，配额恢复后重跑续传")
            break
        if len(df):
            write_partitions(df)
            total += len(df)
        done.extend(batch)
        CKPT.write_text(json.dumps(done, ensure_ascii=False))
        print(f"  批 {i//BATCH+1:>2}: {len(batch)} 只 → {len(df):>7,} 行  累计 {total:>9,}  ({time.time()-t0:.0f}s)")
    n, rows, d0, d1 = rebuild_view()
    print(f"\n完成：{TABLE} 现有 {n} 只 / {rows:,} 行 / {d0}~{d1}（本次 +{total:,} 行）")
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    miss = con.execute(f"""SELECT count(*) FROM (SELECT DISTINCT instrument FROM stock_bar1d) t
        WHERE NOT EXISTS (SELECT 1 FROM {TABLE} v WHERE v.instrument = t.instrument)""").fetchone()[0]
    dup = con.execute(f"SELECT count(*) FROM (SELECT instrument, date, count(*) c FROM {TABLE} "
                      f"GROUP BY 1,2 HAVING c > 1)").fetchone()[0]
    con.close()
    print(f"校验：行情有估值无 = {miss}；主键重复 = {dup} {'OK' if dup == 0 else 'FAIL'}")


if __name__ == "__main__":
    main()
