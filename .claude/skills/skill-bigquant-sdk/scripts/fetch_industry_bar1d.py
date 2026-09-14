"""拉取 cn_stock_industry_bar1d（method=1 算术平均，2015 至今）→ 本地仓库。

- 列拉取铁律：显式 SELECT 13 列（data_tables.md 定义），禁 SELECT *
- 分区表须带 filters；按年分区写 Parquet + DuckDB 视图（仓库 playbook）
- 估算：~146 万行 × 13 列 ≈ 1,900 万单元格（19% 周配额）
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
from bigquant import dai

ROOT = Path("data_cache/bigquant_warehouse")
TABLE = "stock_industry_bar1d"
SOURCE = "cn_stock_industry_bar1d"
START, END = "2015-01-01", "2026-09-11"

COLS = ["instrument", "method", "pre_close", "open", "close", "high", "low",
        "volume", "deal_number", "amount", "change_ratio", "turn", "date"]


def main():
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE method=1 AND date >= '{START}' AND date <= '{END}'")
    df = dai.query(sql, filters={"date": [START, END]}).df()[COLS]
    print(f"拉取 {len(df):,} 行 × {len(COLS)} 列 | "
          f"{df['date'].min().date()}~{df['date'].max().date()} | "
          f"{df['instrument'].nunique()} 行业")

    df["year"] = pd.to_datetime(df["date"]).dt.year
    table_dir = ROOT / TABLE
    n_parts = 0
    for year, grp in df.groupby("year"):
        part_dir = table_dir / f"year={year}"
        part_dir.mkdir(parents=True, exist_ok=True)
        grp.to_parquet(part_dir / "part.parquet", index=False)
        n_parts += 1

    db = ROOT / "bigquant_warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * EXCLUDE (year) FROM read_parquet(
            '{table_dir.resolve().as_posix()}/**/*.parquet', hive_partitioning=true)
    """)
    # 元数据 watermark
    meta_p = ROOT / "_meta.json"
    import json
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {"tables": {}}
    meta["tables"][TABLE] = {
        "source": SOURCE, "start_date": START, "end_date": END,
        "filter": "method=1", "rows": len(df), "partitions": n_parts,
    }
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    con.close()
    print(f"入库完成：{table_dir}（{n_parts} 年分区）+ 视图 {TABLE}")


if __name__ == "__main__":
    main()
