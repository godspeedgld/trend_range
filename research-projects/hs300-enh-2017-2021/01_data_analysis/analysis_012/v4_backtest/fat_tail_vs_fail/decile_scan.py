"""8 特征 × 10 档扫描：每档 失败率 / 肥尾率 / 期望 —— 找"降失败不伤右尾"的特征区间。

失败 = ret≤0；肥尾 = ret≥30%。等频 rank 分 10 档（price_decile 等离散特殊处理）。
每档输出：n / fail_rate / tail_rate / 组期望(ret均值) / 相对全样本的 fail_rate−tail_rate 净改善。
优化目标（实用判别）：希望过滤掉"fail_rate 高而 tail_rate 不高"的档。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
D = pd.read_parquet(HERE.parent / "detail_v4.parquet")
D["date"] = pd.to_datetime(D["date"])
FX = pd.read_parquet(HERE.parent / "stats_v4/features_v4.parquet")
FX["date"] = pd.to_datetime(FX["date"])
m = D.merge(FX[["symbol", "date", "macd", "roc", "llt", "float_market_cap",
                "dividend_yield_ratio", "pe_ttm", "ma_turn20", "ma_vol20"]],
            on=["symbol", "date"], how="left", suffixes=("", "_f"))
m = m[m["result"].isin(["success", "fail"])].copy()   # 已判定
m["is_fail"] = (m["ret"] <= 0)
m["is_tail"] = (m["ret"] >= 0.3)
print(f"已判定 {len(m)}：失败 {m['is_fail'].sum()} ({m['is_fail'].mean()*100:.1f}%) | "
      f"肥尾 {m['is_tail'].sum()} ({m['is_tail'].mean()*100:.1f}%)")

FEATS = ["macd", "roc", "llt", "float_market_cap", "dividend_yield_ratio",
         "pe_ttm", "ma_turn20", "ma_vol20"]
rows = []
for f in FEATS:
    s = m[[f, "ret", "is_fail", "is_tail"]].dropna().copy()
    if len(s) < 500:
        continue
    s["q"] = (s[f].rank(pct=True) * 10).astype(int).clip(0, 9)
    for d in range(10):
        g = s[s["q"] == d]
        if len(g) >= 30:
            rows.append({"feature": f, "decile": d + 1, "n": len(g),
                         "fail_rate": g["is_fail"].mean(),
                         "tail_rate": g["is_tail"].mean(),
                         "exp_ret": g["ret"].mean() * 100,
                         "tail_over_fail": g["is_tail"].mean() / max(g["is_fail"].mean(), 1e-6)})
scan = pd.DataFrame(rows)
scan.to_csv(HERE / "decile_scan.csv", index=False, encoding="utf-8-sig")
# 汇总：每特征 各档 fail/tail 范围 + 最佳档
for f in FEATS:
    s = scan[scan["feature"] == f]
    if len(s):
        print(f"\n═══ {f} ═══")
        best = s.loc[s["exp_ret"].idxmax()]
        print(f"最优档(期望最高): decile {int(best.decile)} n={int(best.n)} "
              f"失败率{best.fail_rate*100:.0f}% 肥尾率{best.tail_rate*100:.0f}% 期望{best.exp_ret:+.1f}%")
        lo = s[s["fail_rate"] < m['is_fail'].mean()]
        hi = s[s["tail_rate"] > m['is_tail'].mean()]
        print(f"失败率<全样本均值({m['is_fail'].mean()*100:.0f}%)的档: "
              f"{[int(x) for x in lo.decile]}")
        print(f"肥尾率>全样本均值({m['is_tail'].mean()*100:.0f}%)的档: "
              f"{[int(x) for x in hi.decile]}")
