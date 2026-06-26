"""建沪深300后复权日线本地仓库（Parquet + DuckDB）。

数据源：pandadata get_stock_daily_post(indicator='000300')
分区：按 year（Hive 风格 year=YYYY/）
仓库根：data_cache/pandadata_warehouse/
"""

import os
import sys
import json
import sqlite3  # noqa
from pathlib import Path
from datetime import datetime

import pandas as pd

# 加载凭证
env_file = Path.home() / ".pandadata" / "pandadata.env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if line.startswith("export "):
            k, _, v = line[7:].partition("=")
            os.environ.setdefault(k.strip(), v.strip())

import panda_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE = PROJECT_ROOT / "data_cache" / "pandadata_warehouse"
PARQUET_DIR = WAREHOUSE / "hs300_post_daily"
DUCKDB_PATH = WAREHOUSE / "warehouse.duckdb"
INDICATOR = "000300"          # 沪深300成分股池
YEARS = [2020, 2021, 2022, 2023, 2024, 2025]  # 最近 ~5 年


def login():
    panda_data.init_token(
        username=os.getenv("DEFAULT_USERNAME"),
        password=os.getenv("DEFAULT_PASSWORD"),
        base_url=os.getenv("JAVA_SERVICE_BASE_URL", "http://pandadata.pandaaiquant.com"),
    )
    print("[warehouse] 登录成功")


def fetch_year(year):
    """拉某一年的沪深300后复权日线。"""
    start = f"{year}0101"
    end = f"{year}1231" if year < 2025 else "20250626"
    print(f"  拉 {year} ({start}~{end})...", end=" ", flush=True)
    r = panda_data.get_stock_daily_post(
        symbol=[], start_date=start, end_date=end,
        fields=[], indicator=INDICATOR, st=True,
    )
    print(f"{len(r)} 行, {r['symbol'].nunique()} 只")
    return r


def write_parquet(df, year):
    """按 Hive 分区写 Parquet。"""
    d = PARQUET_DIR / f"year={year}"
    d.mkdir(parents=True, exist_ok=True)
    out = d / "part.parquet"
    df.to_parquet(out, index=False)
    return out


def build_duckdb():
    """建 DuckDB 视图层（读所有 Parquet 分区）。"""
    import duckdb
    con = duckdb.connect(str(DUCKDB_PATH))
    # 删除旧视图（如存在）
    con.execute("DROP VIEW IF EXISTS hs300_post_daily")
    # Hive 分区读：year 列自动从路径解析
    con.execute(f"""
        CREATE VIEW hs300_post_daily AS
        SELECT * FROM read_parquet(
            '{PARQUET_DIR}/**/*.parquet',
            hive_partitioning = true
        )
    """)
    # 验证
    n = con.execute("SELECT COUNT(*) FROM hs300_post_daily").fetchone()[0]
    syms = con.execute("SELECT COUNT(DISTINCT symbol) FROM hs300_post_daily").fetchone()[0]
    dr = con.execute("SELECT MIN(date), MAX(date) FROM hs300_post_daily").fetchone()
    print(f"[warehouse] DuckDB 视图 hs300_post_daily: {n} 行, {syms} 只, {dr[0]}~{dr[1]}")
    con.close()


def main():
    WAREHOUSE.mkdir(parents=True, exist_ok=True)
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    login()

    total_rows = 0
    for y in YEARS:
        df = fetch_year(y)
        if df.empty:
            print(f"  {y} 无数据，跳过")
            continue
        write_parquet(df, y)
        total_rows += len(df)

    build_duckdb()

    # 写元数据
    meta = {
        "table": "hs300_post_daily",
        "source": "panda_data.get_stock_daily_post",
        "indicator": INDICATOR,
        "adjust": "post",
        "years": YEARS,
        "total_rows": total_rows,
        "parquet_dir": str(PARQUET_DIR),
        "duckdb": str(DUCKDB_PATH),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "columns": ["symbol", "date", "open", "high", "low", "close", "volume",
                     "pre_close", "limit_up", "limit_down", "name", "trade_status"],
    }
    (WAREHOUSE / "_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[warehouse] 元数据: {WAREHOUSE/'_meta.json'}")
    print(f"[warehouse] 完成！总 {total_rows} 行，DuckDB: {DUCKDB_PATH}")


if __name__ == "__main__":
    main()
