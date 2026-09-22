"""拉取申万一级行业指数日线（cn_stock_industry_sw_bar1d，2015 至今）→ 入库 stock_industry_sw_bar1d

为 industry _regime_stock_picking / strategy_001（变盘指数行业轮动）提供行业层官方口径。
量很小：31 个一级行业 × ~2,360 交易日 × 11 列 ≈ 8.8M 单元格，单批拉完。
断点续传：已存在分区跳过；配额断时重跑本脚本即可。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
TABLE = "stock_industry_sw_bar1d"
SOURCE = "cn_stock_industry_sw_bar1d"
START, END = "2015-01-01", "2026-09-21"   # 与 stock_bar1d watermark 对齐
# data_tables.md 定义列（列拉取铁律：显式 SELECT，无 name 列——名称从 component 映射）
# ★ 砍列省配额：变盘指数/行业动量只用 close（排名链全程只需收盘价）。
#   11 列 8.8M → 3 列 2.4M；行业层其他列（volume/amount/turn）以后要了再补一批
COLS = ["date", "instrument", "close"]


def pull() -> pd.DataFrame | None:
    from bigquant import dai
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE date >= '{START}' AND date <= '{END}'")
    for attempt in range(3):
        try:
            return dai.query(sql).df()[COLS]
        except Exception as e:
            print(f"  重试 {attempt+1}/3: {str(e)[:110]}")
            time.sleep(5)
    return None


def main():
    table_dir = ROOT / TABLE
    done_marker = table_dir / "_done.json"
    if done_marker.exists():
        print("已拉取完成（_done.json 存在），跳过。如需重拉请删该文件。")
        return
    print(f"拉取 {SOURCE} {START}~{END} …")
    df = pull()
    if df is None:
        print("三次失败（多半是周配额未释放够，需 ~8.8M）。配额恢复后重跑本脚本。")
        return
    df = df.drop_duplicates(subset=["instrument", "date"], keep="last")
    df["year"] = pd.to_datetime(df["date"]).dt.year
    table_dir.mkdir(parents=True, exist_ok=True)
    for year, grp in df.groupby("year"):
        out = table_dir / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        grp.to_parquet(out, index=False)
    # 视图 + 名称映射（component 的一级代码/名称）
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{table_dir.resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n, rows, d0, d1 = con.execute(
        f"SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM {TABLE}").fetchone()
    con.close()
    done_marker.write_text(json.dumps(
        {"instruments": n, "rows": rows, "first": str(d0)[:10], "last": str(d1)[:10]}, ensure_ascii=False))
    print(f"完成：{n} 个一级行业 / {rows:,} 行 / {str(d0)[:10]} ~ {str(d1)[:10]} → 视图 {TABLE}")
    # 校验：31 个行业？逐年行数分布
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    byy = con.execute(f"""SELECT year, count(DISTINCT instrument), count(*) FROM {TABLE}
        GROUP BY 1 ORDER BY 1""").fetchall()
    for r in byy: print(f"  {r[0]}: {r[1]:>2} 个行业 {r[2]:>7,} 行")
    con.close()


if __name__ == "__main__":
    main()
