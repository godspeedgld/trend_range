"""验证：云端对账时本地缺失的 222 只股，补中证2000 后覆盖情况（只读，零配额）。"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
WH = Path(r"c:/Quant/trend_range/data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")

tr = pd.read_csv(HERE / "csv.csv", encoding="utf-8-sig")
tr.columns = ["date", "time", "symbol", "name", "side", "qty", "price", "amount", "pnl", "fee", "type"]
tr["date"] = pd.to_datetime(tr["date"])

con = duckdb.connect(str(WH), read_only=True)
bar = {x[0] for x in con.execute("SELECT DISTINCT instrument FROM stock_bar1d").fetchall()}
con.close()

cloud = set(tr["symbol"].unique())
miss_now = cloud - bar
print(f"云端交易 {len(cloud)} 只")
print(f"  本地已覆盖 {len(cloud & bar)}（此前 340）")
print(f"  ★ 仍缺 {len(miss_now)}（此前 222）")
if miss_now:
    sfx = pd.Series(sorted(miss_now)).str.split(".").str[1].value_counts().to_dict()
    print(f"  仍缺的后缀分布: {sfx}")
    # 按云端成交额量化剩余影响
    tr["miss"] = tr["symbol"].isin(miss_now)
    amt_share = tr.loc[tr["miss"], "amount"].sum() / tr["amount"].sum()
    print(f"  仍缺股占云端成交额: {amt_share:.1%}（此前 43.3%）")
    # 平仓盈亏影响
    def parse_pnl(s):
        if not isinstance(s, str) or "/" not in s:
            return None
        try:
            return float(s.split("/")[0].strip())
        except ValueError:
            return None
    tr["pnl_amt"] = tr["pnl"].apply(parse_pnl)
    sells = tr[tr["pnl_amt"].notna()]
    miss_pnl = sells.loc[sells["miss"], "pnl_amt"].sum()
    tot_pnl = sells["pnl_amt"].sum()
    print(f"  仍缺股占云端平仓盈亏: {miss_pnl:,.0f} / {tot_pnl:,.0f} = {miss_pnl/tot_pnl:.1%}（此前 60.0%）")
    print("\n仍缺样本（前 12）:", sorted(miss_now)[:12])
