"""分年拉取 cn_stock_shares（沪深300历史668只成分股，2015-2021）入库 warehouse。

表名：stock_shares（本地，year 分区）
断点续传：已入库年份跳过；配额断掉时已入库年份保留。
"""
import json
from pathlib import Path
import pandas as pd
import duckdb
from bigquant import dai

HERE = Path(__file__).resolve().parent      # data_cache/

ROOT = HERE / "bigquant_warehouse"
TABLE = 'stock_shares'
CODES = json.loads((HERE / "_hs300_members.json").read_text(encoding="utf-8"))
YEARS = range(2015, 2022)   # 行情覆盖 2015-2021；2022+ 待行情补齐后再拉

table_dir = ROOT / TABLE
ingested = {}
for year in YEARS:
    part = table_dir / f'year={year}' / 'part.parquet'
    if part.exists():
        ingested[year] = len(pd.read_parquet(part))
        print(f'{year}: 已入库 {ingested[year]} rows，跳过')
        continue
    try:
        df = dai.query("SELECT * FROM cn_stock_shares",
                       filters={'instrument': CODES,
                                'date': [f'{year}-01-01', f'{year}-12-31']}).df()
    except Exception as e:
        print(f'{year}: 拉取失败（可能配额不足）——{str(e)[:80]}')
        break
    if df.empty:
        print(f'{year}: 无数据')
        continue
    part.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(part, index=False)
    ingested[year] = len(df)
    print(f'{year}: {len(df)} rows 入库')

# 重建视图
con = duckdb.connect(str(ROOT / 'bigquant_warehouse.duckdb'))
con.execute(f"""
    CREATE OR REPLACE VIEW {TABLE} AS
    SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)
""")
r = con.execute(f"SELECT count(*), count(DISTINCT instrument), min(date), max(date) FROM {TABLE}").fetchone()
con.close()
print(f'\nstock_shares: {r[0]} rows, {r[1]} 只, {r[2]} ~ {r[3]}')

# 更新 meta
mp = ROOT / '_meta.json'
m = json.loads(mp.read_text(encoding="utf-8"))
m.setdefault('tables', {})[TABLE] = {
    'instruments': CODES, 'start_date': str(r[2])[:10], 'end_date': str(r[3])[:10],
    'source': 'cn_stock_shares', 'rows': int(r[0]),
    'note': '沪深300历史成分股668只；2022+待行情补齐后追加'}
mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
print('_meta.json updated')
