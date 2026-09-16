"""指数 (close-MA200)/MA200 偏离度 分 10 档 → 肥尾率/失败率 观察。

猜想：正/负极端偏离 → 失败率高；正偏离上半段 → 肥尾率高；中间 → 差不多。
用偏离度等频 rank 分 10 档（decile），看每档 fail/tail/期望 + 偏离度实际值。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

HERE = Path(__file__).resolve().parent
D = pd.read_parquet(HERE.parent / "detail_v4.parquet")
D["date"] = pd.to_datetime(D["date"])
D = D[D["result"].isin(["success", "fail"])].copy()
D["fail"] = D["ret"] <= 0
D["tail"] = D["ret"] >= 0.3

# 指数 (close-MA200)/MA200
con = duckdb.connect(r"C:\Quant\trend_range\data_cache\bigquant_warehouse\bigquant_warehouse.duckdb",
                     read_only=True)
idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                  "ORDER BY date").fetchdf()
con.close()
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date")["close"]
ma200 = idx.rolling(200).mean()
dev = (idx - ma200) / ma200          # 偏离度
dev.name = "dev"
D = D.join(dev, on="date", how="left")

# 等频 rank 分 10 档
s = D[D["dev"].notna()].copy()
s["dec"] = (s["dev"].rank(pct=True) * 10).astype(int).clip(0, 9)
print(f"样本 {len(s)} | 全样本 失败率 {s['fail'].mean()*100:.1f}% 肥尾率 {s['tail'].mean()*100:.1f}%")

rows = []
for d in range(10):
    g = s[s["dec"] == d]
    rows.append({"decile": d + 1, "n": len(g), "dev_min": g["dev"].min(),
                 "dev_max": g["dev"].max(), "fail_rate": g["fail"].mean(),
                 "tail_rate": g["tail"].mean(), "exp_ret": g["ret"].mean() * 100})
res = pd.DataFrame(rows)
res.to_csv(HERE / "ma200_dev_decile.csv", index=False, encoding="utf-8-sig")
print(res.round(4).to_string(index=False))

# 分段时间稳定性
print("\n═══ 分时段 ═══")
s["y"] = s["date"].dt.year
for lo, hi, nm in [(2017, 2020, "2017-20"), (2021, 2026, "2021-26")]:
    seg = s[(s["y"] >= lo) & (s["y"] <= hi)]
    print(f"\n[{nm}] 样本 {len(seg)}")
    for d in range(10):
        g = seg[seg["dec"] == d]
        if len(g):
            print(f"  D{d+1}: n={len(g):4d} dev[{g['dev'].min():+.2f},{g['dev'].max():+.2f}] "
                  f"失败 {g['fail'].mean()*100:4.1f}% 肥尾 {g['tail'].mean()*100:4.1f}%")
