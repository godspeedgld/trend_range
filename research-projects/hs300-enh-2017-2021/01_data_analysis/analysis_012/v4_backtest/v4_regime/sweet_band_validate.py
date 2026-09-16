"""甜点带 (0~+6% 偏离) 过滤验证：看保留段是否降失败、保肥尾、提升期望。

对比 3 组：
  全样本 / 甜点带(0~+6%) / 反带(<0 或 >+6%)
每组分 2017-20 与 2021-26 看稳定性；并输出"过滤掉的反带里肥尾损失"评估
（关键：甜点带虽期望高，若滤掉大量肥尾则净损）。另测窄带灵敏度 ±3% 边界。
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
dev = ((idx - idx.rolling(200).mean()) / idx.rolling(200).mean()).rename("dev")
D = D.join(dev, on="date", how="left").dropna(subset=["dev"])


def summ(sub):
    if len(sub) == 0:
        return None
    return {"n": len(sub), "fail": sub["fail"].mean(), "tail": sub["tail"].mean(),
            "exp": sub["ret"].mean() * 100, "tail_n": sub["tail"].sum(),
            "exp_sum": sub["ret"].sum() * 100}


print("═══ 甜点带过滤（全样本基线）═══")
base = summ(D)
print(f"全样本: n={base['n']} 失败{base['fail']*100:.1f}% 肥尾{base['tail']*100:.1f}% "
      f"期望{base['exp']:+.1f}% 肥尾{base['tail_n']}笔 期望合计{base['exp_sum']:+.0f}pp")

for lo, hi, nm in [(0.0, 0.06, "甜点 0~+6%"),
                   (-1.0, 0.0, "反带 <0"),
                   (0.06, 1.0, "反带 >+6%")]:
    s = D[(D["dev"] >= lo) & (D["dev"] < hi)]
    r = summ(s)
    if r:
        print(f"{nm}: n={r['n']:5d} 失败{r['fail']*100:5.1f}% 肥尾{r['tail']*100:4.1f}% "
              f"期望{r['exp']:+5.1f}% | 肥尾{r['tail_n']}笔 期望合计{r['exp_sum']:+6.0f}pp")

sweet = D[(D["dev"] >= 0) & (D["dev"] < 0.06)]
anti = D[~((D["dev"] >= 0) & (D["dev"] < 0.06))]
# 甜点带相对全样本的肥尾保留率
print(f"\n甜点带保留全样本: 肥尾 {sweet['tail'].sum()}/{base['tail_n']} "
      f"= {sweet['tail'].sum()/base['tail_n']*100:.0f}%；失败笔数比 "
      f"{sweet['fail'].sum()/base['fail'].sum()*100:.0f}%")

print("\n═══ 分时段稳定性 ═══")
D["y"] = D["date"].dt.year
for lo, hi, nm in [(2017, 2020, "2017-20"), (2021, 2026, "2021-26")]:
    seg = D[(D["y"] >= lo) & (D["y"] <= hi)]
    r_full = summ(seg)
    sw = seg[(seg["dev"] >= 0) & (seg["dev"] < 0.06)]
    r_sw = summ(sw)
    print(f"[{nm}] 全样本 n={r_full['n']} 失败{r_full['fail']*100:.0f}% 肥尾{r_full['tail']*100:.0f}% "
          f"期望{r_full['exp']:+.1f}% | 甜点带 n={r_sw['n']} 失败{r_sw['fail']*100:.0f}% "
          f"肥尾{r_sw['tail']*100:.0f}% 期望{r_sw['exp']:+.1f}%")

print("\n═══ 窄带灵敏度（甜点±3% 边界平移）═══")
for lo, hi, nm in [(0.0, 0.03, "0~+3%"), (0.03, 0.06, "+3~+6%"), (0.0, 0.09, "0~+9%")]:
    s = D[(D["dev"] >= lo) & (D["dev"] < hi)]
    r = summ(s)
    if r:
        print(f"{nm}: n={r['n']:5d} 失败{r['fail']*100:5.1f}% 肥尾{r['tail']*100:4.1f}% "
              f"期望{r['exp']:+5.1f}%")

# 落盘供复用
D.to_parquet(HERE / "sweet_band_trades.parquet", index=False)
