"""v4 交易按 指数 MA200 regime 分层：看 失败率/肥尾率 是否天然分开。

假设：v3/v4 成败有强市场 beta——失败大量在指数熊市段、肥尾在牛市段。
若成立 → 指数 MA200(≤t) 是"降失败不伤肥尾"的天然第一层条件。

口径：
  - 交易 = detail_v4 已判定 11048 笔；信号日 t = entry 前一日（用事件日 date 前移? 用 date 当日?）
  - 用**突破日 date** 的指数 MA200 regime（≤t 已知，无未来）：指数收盘 > MA200 = 牛
  - 统计牛/熊两段：n / fail率(ret≤0) / tail率(ret≥30%) / 期望
  - 分段 2017-20 vs 2021-26 看稳定性
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
print(f"已判定 {len(D)}：失败 {D['fail'].sum()} ({D['fail'].mean()*100:.1f}%) | "
      f"肥尾 {D['tail'].sum()} ({D['tail'].mean()*100:.1f}%)")

# 指数 MA200（warehouse）
con = duckdb.connect(r"C:\Quant\trend_range\data_cache\bigquant_warehouse\bigquant_warehouse.duckdb",
                     read_only=True)
idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                  "ORDER BY date").fetchdf()
con.close()
idx["date"] = pd.to_datetime(idx["date"])
idx = idx.set_index("date")["close"]
ma200 = idx.rolling(200).mean()
regime = (idx > ma200)          # True=牛
regime.name = "bull"

# 突破日用 regime（无未来：t 日收盘已知，t+1 买入）
D = D.join(regime, on="date", how="left")
D["bull"] = D["bull"].fillna(False)

print("\n═══ 总体按指数 MA200 分层 ═══")
for b, nm in [(True, "牛(收盘>MA200)"), (False, "熊(收盘≤MA200)")]:
    s = D[D["bull"] == b]
    if len(s):
        print(f"{nm}: n={len(s):6d} | 失败率 {s['fail'].mean()*100:5.1f}% | "
              f"肥尾率 {s['tail'].mean()*100:4.1f}% | 期望 {s['ret'].mean()*100:+5.1f}% | "
              f"肥/败 {s['tail'].mean()/s['fail'].mean():.2f}")

print("\n═══ 分段时间稳定性 ═══")
D["y"] = D["date"].dt.year
for lo, hi, nm in [(2017, 2020, "2017-20"), (2021, 2026, "2021-26")]:
    seg = D[(D["y"] >= lo) & (D["y"] <= hi)]
    print(f"\n[{nm}] 样本 {len(seg)}")
    for b, nm2 in [(True, "牛"), (False, "熊")]:
        s = seg[seg["bull"] == b]
        if len(s):
            print(f"  {nm2}: n={len(s):5d} | 失败率 {s['fail'].mean()*100:5.1f}% | "
                  f"肥尾率 {s['tail'].mean()*100:4.1f}% | 期望 {s['ret'].mean()*100:+5.1f}%")

# 牛段 vs 熊段的收益分布（肥尾贡献分解）
bull, bear = D[D["bull"]], D[~D["bull"]]
print("\n═══ 收益贡献分解 ═══")
print(f"牛段 {len(bull)} 笔: 期望合计 {bull['ret'].sum()*100:+.0f}pp")
print(f"熊段 {len(bear)} 笔: 期望合计 {bear['ret'].sum()*100:+.0f}pp")
print(f"肥尾合计: 牛段 {(bull['tail']).sum()} 笔 / 熊段 {(bear['tail']).sum()} 笔")
D.to_parquet(HERE / "trades_ma200.parquet", index=False)
print("写出 trades_ma200.parquet")
