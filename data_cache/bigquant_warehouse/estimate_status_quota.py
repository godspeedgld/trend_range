"""cn_stock_status 拉取额度评估（只读 + 一次极小云端探测）。

估算逻辑：status 表主键 (instrument, date) 与 bar1d 同基数 → 用本地 stock_bar1d
**真实行数**（而非 只数×满交易日，短命/次新股会高估）× 7 列。
云端探测：取最近一个交易日 count(*)（~5800 行 × 1 列 ≈ 6K 配额）验证当日密度。
"""
import sys

import duckdb

sys.stdout.reconfigure(encoding="utf-8")
con = duckdb.connect("data_cache/bigquant_warehouse/bigquant_warehouse.duckdb", read_only=True)

# 本地真实行数（截至 2026-08-24）
r = con.execute("SELECT count(*), count(DISTINCT instrument) FROM stock_bar1d").fetchone()
rows_local, n_stk = r
print(f"本地 stock_bar1d：{n_stk} 只 / {rows_local:,} 行（至 2026-08-24）")

# 分年行数 → 拆批依据
print("\n分年行数（拆批用）：")
cum = 0
by_year = {}
for y, n in con.execute("SELECT year(date), count(*) FROM stock_bar1d GROUP BY 1 ORDER BY 1").fetchall():
    cum += n
    by_year[y] = (n, cum)
    print(f"  {y}: {n:>10,}  累计 {cum:>10,}  ×7列={cum*7/1e6:>6.1f}M")

# 外推到"至今"（2026-09-26 前最后交易日）：8/25 起约 +21 个交易日 × ~5800 只
ext = 21 * 5800
rows_total = rows_local + ext
print(f"\n外推至今（+~{ext:,} 行）≈ {rows_total:,} 行")
cells = rows_total * 7
print(f"全量 2015~今 × 7 列 ≈ {cells/1e6:.1f}M 单元格")
con.close()

# 云端探测：最近一日行密度
from bigquant import dai
q0 = dai.get_data_quota()
df = dai.query("SELECT count(*) n FROM cn_stock_status WHERE date >= '2026-09-25' AND date <= '2026-09-26'").df()
q1 = dai.get_data_quota()
print(f"\n云端探测 2026-09-25~26：{int(df.iloc[0,0]):,} 行（配额消耗 {q1['used_quota']-q0['used_quota']:,}）")
print(f"当前周配额：已用 {q1['used_quota']:,}（{q1['used_quota']/q1['weekly_quota']:.1%}），"
      f"剩 {q1['weekly_quota']-q1['used_quota']:,}")
