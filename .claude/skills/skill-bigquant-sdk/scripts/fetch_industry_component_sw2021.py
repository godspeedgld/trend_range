"""拉取 cn_stock_industry_component（沪深300 成分 668 只 × sw2021 × 月末抽样）→ 本地仓库。

- 月末抽样：只在 140 个月末交易日拉快照（行业归属低频变化，省 97% 配额）
- 本地补全：落盘后建逐日 ffill 视图 stock_industry_component_daily（asof 前向填充）
- 估算：93,520 行 × 12 列 ≈ 112 万单元格（1.12% 周配额）
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
from bigquant import dai

ROOT = Path("data_cache/bigquant_warehouse")
TABLE = "stock_industry_component"
SOURCE = "cn_stock_industry_component"
START, END = "2015-01-01", "2026-08-21"

COLS = ["instrument", "industry", "industry_name", "industry_instrument",
        "industry_level1_code", "industry_level1_name",
        "industry_level2_code", "industry_level2_name",
        "industry_level3_code", "industry_level3_name", "date"]


def month_end_days() -> list:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    days = [r[0] for r in con.execute("""
        SELECT date FROM (
          SELECT date, row_number() OVER (PARTITION BY date_trunc('month', date)
                                          ORDER BY date DESC) rn
          FROM trading_days WHERE date>=? AND date<=?)
        WHERE rn=1 ORDER BY date
    """, [START, END]).fetchall()]
    con.close()
    return days


def main():
    syms_con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    syms = [r[0] for r in syms_con.execute(
        "SELECT DISTINCT member_code FROM index_component WHERE instrument='000300.SH'").fetchall()]
    syms_con.close()

    med = month_end_days()
    print(f"月末交易日 {len(med)} 个 | 股票 {len(syms)} 只 | 标准仅 sw2021")
    inlist = ",".join(f"'{s}'" for s in syms)
    date_in = ",".join(f"'{d}'" for d in med)
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE industry='sw2021' AND instrument IN ({inlist}) AND date IN ({date_in})")
    df = dai.query(sql, filters={"date": [START, END]}).df()[COLS]
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["instrument", "date"]).drop_duplicates(["instrument", "date"], keep="last")
    print(f"拉取 {len(df):,} 行 | {df['date'].min().date()}~{df['date'].max().date()} | "
          f"{df['instrument'].nunique()} 只 | 一级行业 {df['industry_level1_code'].nunique()} 个")

    table_dir = ROOT / TABLE
    table_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(table_dir / "part.parquet", index=False)

    db = ROOT / "bigquant_warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(table_dir / 'part.parquet').resolve().as_posix()}')
    """)
    # ── 本地补全：逐日 asof 视图（股票×全交易日日历，前向填充最近月末归属）──
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE}_daily AS
        WITH cal AS (SELECT DISTINCT date FROM trading_days
                     WHERE date>=('{START}'::DATE - INTERVAL 1 DAY) AND date<='{END}'),
             grid AS (SELECT s.date, c.instrument FROM cal s CROSS JOIN (SELECT DISTINCT instrument FROM {TABLE}) c),
             filled AS (
               SELECT g.date, g.instrument, t.industry, t.industry_name, t.industry_instrument,
                      t.industry_level1_code, t.industry_level1_name,
                      t.industry_level2_code, t.industry_level2_name,
                      t.industry_level3_code, t.industry_level3_name
               FROM grid g
               ASOF JOIN {TABLE} t
                 ON g.instrument = t.instrument AND g.date >= t.date)
        SELECT * FROM filled ORDER BY instrument, date
    """)
    meta_p = ROOT / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {"tables": {}}
    meta["tables"][TABLE] = {"source": SOURCE, "filter": "sw2021×月末×300成分",
                             "start_date": START, "end_date": str(df["date"].max().date()),
                             "rows": len(df)}
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    n = con.execute(f"SELECT count(*) FROM {TABLE}_daily").fetchone()[0]
    con.close()
    print(f"入库完成：{TABLE}（月末快照 {len(df):,} 行）+ 逐日视图 {TABLE}_daily（{n:,} 行 asof 填充）")


if __name__ == "__main__":
    main()
