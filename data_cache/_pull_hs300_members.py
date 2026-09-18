"""拉取沪深300成分股（668只）2015至今日线 → 入库 stock_bar1d。

分年拉取避免超时；按年分区 + 主键去重 + DuckDB 视图。
"""
from pathlib import Path
import json
import pandas as pd
import duckdb
from bigquant import dai

HERE = Path(__file__).resolve().parent      # data_cache/

ROOT = HERE / "bigquant_warehouse"
TABLE = 'stock_bar1d'
CODES = json.loads((HERE / "_hs300_members.json").read_text(encoding="utf-8"))
YEARS = range(2015, 2027)

table_dir = ROOT / TABLE
total = 0
for year in YEARS:
    s, e = f'{year}-01-01', f'{year}-12-31'
    df = dai.query(
        "SELECT * FROM cn_stock_bar1d",
        filters={'instrument': CODES, 'date': [s, e]}
    ).df()
    if df.empty:
        continue
    part_dir = table_dir / f'year={year}'
    part_dir.mkdir(parents=True, exist_ok=True)
    out = part_dir / 'part.parquet'
    if out.exists():
        existing = pd.read_parquet(out)
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(
            subset=['instrument', 'date'], keep='last')
    df.to_parquet(out, index=False)
    total += len(df)
    print(f'{year}: {len(df)} rows')

# 重建视图
con = duckdb.connect(str(ROOT / 'bigquant_warehouse.duckdb'))
con.execute(f"""
    CREATE OR REPLACE VIEW {TABLE} AS
    SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)
""")
r = con.execute(f"SELECT count(*), count(DISTINCT instrument), min(date), max(date) FROM {TABLE}").fetchone()
con.close()
print(f'stock_bar1d 入库: {r[0]} rows, {r[1]} 只, {r[2]} ~ {r[3]}')

# 更新 meta
mp = ROOT / '_meta.json'
m = json.loads(mp.read_text(encoding="utf-8"))
m.setdefault('tables', {})[TABLE] = {
    'instruments': CODES, 'start_date': str(r[2])[:10], 'end_date': str(r[3])[:10],
    'source': 'cn_stock_bar1d', 'rows': int(r[0]), 'note': '沪深300历史成分股668只'}
mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
print('_meta.json updated')
