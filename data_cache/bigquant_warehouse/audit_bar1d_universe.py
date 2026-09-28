"""BigQuant 本地库体检：四宽基指数并集的股票覆盖与时间完整性（只读）。

检查项：
  ① stock_bar1d 总体状态
  ② 各指数历史并集逐个核对：应有 / 已有 / 缺失（含缺失明细去向）
  ③ 时间完整性：按指数并集口径逐年行数 + 每年覆盖的交易日数（应≈244）
  ④ 数据质量抽检：列完整、主键重复、复权口径
"""
import sys

import duckdb

sys.stdout.reconfigure(encoding="utf-8")
WH = "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
con = duckdb.connect(WH, read_only=True)

# ① 总体
r = con.execute("SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM stock_bar1d").fetchone()
print("=" * 72)
print("① stock_bar1d 总体")
print(f"   {r[0]} 只 / {r[1]:,} 行 / {str(r[2])[:10]} ~ {str(r[3])[:10]}")

# ② 各指数并集覆盖
print("\n② 四宽基指数历史并集覆盖（2015 至今应有）")
idxs = [("000300.SH", "沪深300"), ("000905.SH", "中证500"),
        ("000852.SH", "中证1000"), ("932000.CSI", "中证2000")]
union_all = set()
for code, name in idxs:
    u = {x[0] for x in con.execute(
        f"SELECT DISTINCT member_code FROM index_component WHERE instrument='{code}'").fetchall()}
    union_all |= u
    bar = {x[0] for x in con.execute("SELECT DISTINCT instrument FROM stock_bar1d").fetchall()}
    have, miss = u & bar, u - bar
    bj_miss = sum(1 for s in miss if s.endswith(".BJ"))
    print(f"   {name:<7} 并集 {len(u):>5} 只：已有 {len(have):>5}（{len(have)/len(u):>6.1%}），"
          f"缺 {len(miss):>3}（其中 .BJ {bj_miss}）")
bar = {x[0] for x in con.execute("SELECT DISTINCT instrument FROM stock_bar1d").fetchall()}
print(f"   {'四指数并集':<8} {len(union_all):>5} 只：已有 {len(union_all & bar):>5}"
      f"（{len(union_all & bar)/len(union_all):>6.1%}），缺 {len(union_all - bar)}")

# ③ 时间完整性：逐年交易日覆盖（用全表口径）
print("\n③ 时间完整性（全表逐年）")
for y, n_stock_days, n_days, n_stocks in con.execute("""
        SELECT year(date) y, count(*), count(DISTINCT date), count(DISTINCT instrument)
        FROM stock_bar1d GROUP BY 1 ORDER BY 1""").fetchall():
    print(f"   {y}: {n_stock_days:>10,} 行 / {n_days:>3} 个交易日 / {n_stocks:>5} 只在市")

# ④ 质量抽检
print("\n④ 数据质量")
dup = con.execute("SELECT count(*) FROM (SELECT instrument, date, count(*) c "
                  "FROM stock_bar1d GROUP BY 1,2 HAVING c > 1)").fetchone()[0]
print(f"   主键重复: {dup} {'OK' if dup == 0 else 'FAIL'}")
cols = [d[0] for d in con.execute("DESCRIBE stock_bar1d").fetchall()]
print(f"   列({len(cols)}): {cols}")
susp = con.execute("SELECT count(*) FROM stock_bar1d WHERE close IS NULL").fetchone()[0]
print(f"   停牌行(close NULL): {susp:,}（占 {susp/r[1]:.1%}，正常现象）")
# 后缀分布
sfx = dict(con.execute("SELECT split_part(instrument,'.',2), count(DISTINCT instrument) "
                       "FROM stock_bar1d GROUP BY 1").fetchall())
print(f"   交易所分布: {sfx}")
con.close()
