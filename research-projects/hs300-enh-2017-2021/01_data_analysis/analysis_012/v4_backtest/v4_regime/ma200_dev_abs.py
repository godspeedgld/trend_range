"""MA200 偏离度【绝对区间】分桶（无前视，修正版）。

用户指出：全样本等频 rank 分位混入未来分布（前视）。偏离度是绝对量，直接用绝对区间分桶
（实盘同口径判断，零前视）。每区间报 fail/tail/期望 + 覆盖年份（查时段混杂）。

区间（单位 = (close-MA200)/MA200）：
  <-12%, -12~-6, -6~-3, -3~0, 0~+3, +3~+6, +6~+9, +9~+12, +12~+18, >+18%
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

con = duckdb.connect(r"C:\Quant\trend_range\data_cache\bigquant_warehouse\bigquant_warehouse.duckdb",
                     read_only=True)
idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                  "ORDER BY date").fetchdf()
con.close()
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date")["close"]
ma200 = idx.rolling(200).mean()
dev = ((idx - ma200) / ma200).rename("dev")
D = D.join(dev, on="date", how="left").dropna(subset=["dev"])

# 绝对区间
EDGES = [-1.0, -0.12, -0.06, -0.03, 0.0, 0.03, 0.06, 0.09, 0.12, 0.18, 1.0]
LABELS = [f"{EDGES[i]*100:+.0f}~{EDGES[i+1]*100:+.0f}%" for i in range(len(EDGES)-1)]
D["band"] = pd.cut(D["dev"], bins=EDGES, labels=LABELS, right=False)
print(f"样本 {len(D)} | 基线 失败 {D['fail'].mean()*100:.1f}% 肥尾 {D['tail'].mean()*100:.1f}%")

rows = []
for lab in LABELS:
    g = D[D["band"] == lab]
    if len(g) >= 20:
        yrs = sorted(g["date"].dt.year.unique())
        rows.append({"band": lab, "n": len(g),
                     "fail_rate": g["fail"].mean(), "tail_rate": g["tail"].mean(),
                     "exp_ret": g["ret"].mean() * 100,
                     "years": f"{yrs[0]}-{yrs[-1]}"})
res = pd.DataFrame(rows)
res.to_csv(HERE / "ma200_dev_abs.csv", index=False, encoding="utf-8-sig")
print(res.round(4).to_string(index=False))
