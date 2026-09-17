"""拉取 cn_stock_industry_component（**指定指数成分股** × sw2021 × 月末抽样）→ 本地仓库。

用法：INDEX_CODE=000852.SH python fetch_industry_component_csi500.py   # 中证1000

背景：本地 `stock_industry_component` 原有 667 只（沪深300 池），而 `stock_bar1d` 已扩到
1,578 只（沪深300 ∪ 中证500）。中证500 的 1,356 只里只有 446 只有行业归属（= 与沪深300 重叠的），
**缺 910 只** → 那 910 只 join 不上行业，行业维度分析（如 analysis_015 那套）会全部落空。

策略（与 fetch_industry_component_sw2021.py 同款，**追加进同一张表**）：
  - 月末抽样：只拉 134 个月末交易日的快照（行业归属低频变化，省 ~97% 配额）
  - 断点续传：跳过 `stock_industry_component` 里已有的 instrument
  - 每批立即落盘（合并进 part.parquet），配额耗尽/断网可续跑
  - 全部完成后重建 `stock_industry_component_daily`（逐日 asof 前向填充视图）
  - 列严格按 `references/data_tables.md` 的 11 列，禁 SELECT *

估算：910 只 × 134 月末 ≈ 12.2 万行 × 11 列 ≈ **134 万单元格（1.34% 周配额）**

用法（配额可用时直接跑）：
  python fetch_industry_component_csi500.py
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range\data_cache\bigquant_warehouse")
TABLE = "stock_industry_component"
SOURCE = "cn_stock_industry_component"
import os
INDEX_CODE = os.environ.get("INDEX_CODE", "000905.SH")   # 中证500 / 000852.SH=中证1000
START, END = "2015-01-01", "2026-08-21"
BATCH = 200

# 严格按 references/data_tables.md 的 11 列
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


def done_symbols() -> set:
    p = ROOT / TABLE / "part.parquet"
    if not p.exists():
        return set()
    return set(pd.read_parquet(p, columns=["instrument"])["instrument"].unique())


def write_batch(df: pd.DataFrame):
    if df.empty:
        return
    out = ROOT / TABLE / "part.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        df = pd.concat([pd.read_parquet(out), df], ignore_index=True)
    df = df.drop_duplicates(subset=["instrument", "date", "industry"], keep="last")
    df.to_parquet(out, index=False)


def rebuild_views():
    db = ROOT / "bigquant_warehouse.duckdb"
    part = (ROOT / TABLE / "part.parquet").resolve().as_posix()
    con = duckdb.connect(str(db))
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{part}')""")
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE}_daily AS
        WITH cal AS (SELECT DISTINCT date FROM trading_days
                     WHERE date>='{START}'::DATE - INTERVAL 1 DAY AND date<='{END}'),
             grid AS (SELECT s.date, c.instrument FROM cal s
                      CROSS JOIN (SELECT DISTINCT instrument FROM {TABLE}) c),
             filled AS (
               SELECT g.date, g.instrument, t.industry, t.industry_name, t.industry_instrument,
                      t.industry_level1_code, t.industry_level1_name,
                      t.industry_level2_code, t.industry_level2_name,
                      t.industry_level3_code, t.industry_level3_name
               FROM grid g ASOF JOIN {TABLE} t
                 ON g.instrument = t.instrument AND g.date >= t.date)
        SELECT * FROM filled ORDER BY instrument, date""")
    n1, i1, s1, e1 = con.execute(
        f"SELECT count(*), count(DISTINCT instrument), min(date), max(date) FROM {TABLE}").fetchone()
    n2 = con.execute(f"SELECT count(*) FROM {TABLE}_daily").fetchone()[0]
    con.close()
    print(f"  月末快照 {n1:,} 行 / {i1:,} 只 / {s1} ~ {e1}")
    print(f"  逐日视图 {n2:,} 行")
    mp = ROOT / "_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["tables"][TABLE] = {
        "source": SOURCE, "filter": "sw2021 × 月末 × (沪深300 ∪ 中证500) 成分",
        "start_date": str(s1), "end_date": str(e1), "rows": int(n1), "instruments": int(i1),
        "note": "个股行业归属（sw2021 31/131/337 级）；_daily 为本地逐日 asof 前向填充视图"}
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    from bigquant import dai
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    members = [r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument='{INDEX_CODE}'").fetchall()]
    con.close()

    med = month_end_days()
    done = done_symbols()
    todo = sorted(s for s in members if s not in done)
    print(f"中证500 成分 {len(members)} 只 | 已有行业归属 {len(done & set(members))} 只 | "
          f"**本次待拉 {len(todo)} 只**")
    print(f"月末交易日 {len(med)} 个（{med[0]} ~ {med[-1]}）")

    date_in = ",".join(f"'{d}'" for d in med)
    n_done, quota_hit = 0, False
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        inlist = ",".join(f"'{s}'" for s in batch)
        sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
               f"WHERE industry='sw2021' AND date IN ({date_in}) AND instrument IN ({inlist})")
        try:
            df = dai.query(sql, filters={"date": [START, END]}).df()[COLS]
            df["date"] = pd.to_datetime(df["date"])
            write_batch(df)
            n_done += len(df)
            print(f"  [{i//BATCH+1}/{(len(todo)+BATCH-1)//BATCH}] {len(batch)} 只 -> "
                  f"{len(df):,} 行（累计 {n_done:,}）", flush=True)
        except Exception as e:                        # noqa: BLE001 配额/网络
            msg = str(e)[:160]
            print(f"  [{i//BATCH+1}] 失败: {msg}", flush=True)
            if "配额" in msg or "quota" in msg.lower():
                quota_hit = True
                break
    print(f"[小结] 新增 {n_done:,} 行 | 配额{'耗尽' if quota_hit else '正常'}")
    rebuild_views()


if __name__ == "__main__":
    main()
