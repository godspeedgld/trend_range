"""分年拉取 cn_stock_index_component（7 指数，2015~今）并入库 warehouse。

表名：index_component（本地）
分区：year（日级）
"""
from pathlib import Path
import pandas as pd
import duckdb
import json
from bigquant import dai

HERE = Path(__file__).resolve().parent      # data_cache/

ROOT = HERE / "bigquant_warehouse"
TABLE = 'index_component'
CODES = ['000300.SH', '000905.SH', '000852.SH', '932000.CSI', '399001.SZ', '399006.SZ', '000688.SH']
YEARS = range(2015, 2027)

table_dir = ROOT / TABLE
for year in YEARS:
    s, e = f'{year}-01-01', f'{year}-12-31'
    df = dai.query(
        "SELECT * FROM cn_stock_index_component",
        filters={'instrument': CODES, 'date': [s, e]}
    ).df()
    if df.empty:
        continue
    # 按年分区写
    part_dir = table_dir / f'year={year}'
    part_dir.mkdir(parents=True, exist_ok=True)
    out = part_dir / 'part.parquet'
    if out.exists():
        existing = pd.read_parquet(out)
        df = pd.concat([existing, df], ignore_index=True).drop_duplicates(
            subset=['instrument', 'member_code', 'date'], keep='last')
    df.to_parquet(out, index=False)
    print(f'{year}: {len(df)} rows')

# 重建视图
con = duckdb.connect(str(ROOT / 'bigquant_warehouse.duckdb'))
con.execute(f"""
    CREATE OR REPLACE VIEW {TABLE} AS
    SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)
""")
r = con.execute(f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
n_inst = con.execute(f"SELECT count(DISTINCT instrument) FROM {TABLE}").fetchone()[0]
n_member = con.execute(f"SELECT count(DISTINCT member_code) FROM {TABLE}").fetchone()[0]
con.close()
print(f'入库完成: {r[0]} rows, {r[1]} ~ {r[2]}, 指数{n_inst}个, 成分股{n_member}只')

# 更新 meta
mp = ROOT / '_meta.json'
m = json.loads(mp.read_text(encoding="utf-8"))
m.setdefault('tables', {})[TABLE] = {
    'instruments': CODES, 'start_date': '2015-01-05', 'end_date': '2026-08-19',
    'source': 'cn_stock_index_component', 'rows': int(r[0]), 'n_member': int(n_member)}
mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
print('_meta.json updated')
