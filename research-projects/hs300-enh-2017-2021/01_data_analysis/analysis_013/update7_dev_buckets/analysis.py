"""更新七 — 更新五交易记录（8095 笔，无过滤）× 信号日指数偏离度分桶（找甜点带）。

方法对齐 analysis_012 补充5/6：
  偏离度 dev = (沪深300 close − MA200) / MA200，取**信号日**（入场日前一交易日，决策时点）
  双口径：① 等频十分位（分位用全样本 dev 分布——含前视，仅用于观察形状，注明）
         ② 绝对区间（零前视，实盘同口径）
每桶统计：n / 单笔均值 / 胜率 / 盈亏比 / 期望贡献合计(sum, pp) / 肥尾率(ret≥30%) / 均持仓。
"""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
U5 = HERE.parent / "update5_pattern_portfolio"
WAREHOUSE = HERE.parents[5] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"


def main():
    tr = pd.read_csv(U5 / "backtest_logs" / "trades.csv", parse_dates=["entry_date"])
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                      "ORDER BY date").fetchdf()
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    s = idx.set_index("date")["close"]
    dev = (s - s.rolling(200).mean()) / s.rolling(200).mean()

    dates = s.index
    pos = {d: i for i, d in enumerate(dates)}
    sig = [dates[pos[e] - 1] if e in pos and pos[e] > 0 else pd.NaT for e in tr["entry_date"]]
    tr["sig_date"] = pd.to_datetime(sig)
    tr["dev"] = tr["sig_date"].map(dev)
    n_drop = tr["dev"].isna().sum()
    d = tr.dropna(subset=["dev"]).copy()
    print(f"交易 {len(tr)} 笔，可配偏离 {len(d)}（缺 {n_drop}，信号日 dev 为 NaN——指数 MA200 未就绪）")

    def stat(g: pd.DataFrame) -> pd.Series:
        w, l = g[g.ret_pct > 0].ret_pct, g[g.ret_pct <= 0].ret_pct
        return pd.Series({"n": len(g),
                          "单笔均%": round(g.ret_pct.mean(), 3),
                          "胜率%": round(len(w) / len(g) * 100, 1),
                          "盈亏比": round(w.mean() / abs(l.mean()), 2) if len(w) and len(l) and l.mean() != 0 else np.nan,
                          "肥尾率%(≥30)": round((g.ret_pct >= 30).mean() * 100, 1),
                          "均持仓日": round(g.hold_days.mean(), 1)})

    base = stat(d)
    base["期望贡献pp"] = round(d.ret_pct.sum(), 0)
    print("\n== 全体基线 ==\n", base.to_string())

    # ① 等频十分位（前视口径，观察形状）
    d["decile"] = pd.qcut(d["dev"], 10, labels=False, duplicates="drop") + 1
    t1 = d.groupby("decile").apply(stat, include_groups=False)
    t1["dev区间"] = d.groupby("decile")["dev"].agg(["min", "max"]).apply(
        lambda r: f"[{r['min']:+.3f},{r['max']:+.3f}]", axis=1)
    t1["期望贡献pp"] = d.groupby("decile")["ret_pct"].sum().round(0)
    t1 = t1[["dev区间"] + [c for c in t1.columns if c != "dev区间"]]
    print("\n== 十分位（等频，前视口径）==\n", t1.to_string())

    # ② 绝对区间（零前视）
    bins = [-np.inf, -0.06, 0.0, 0.03, 0.06, 0.10, 0.15, np.inf]
    labels = ["<-6%", "[-6%,0)", "[0,3%)", "[3,6%)", "[6,10%)", "[10,15%)", "≥15%"]
    d["band"] = pd.cut(d["dev"], bins=bins, labels=labels, right=False)
    t2 = d.groupby("band", observed=True).apply(stat, include_groups=False)
    t2["期望贡献pp"] = d.groupby("band", observed=True)["ret_pct"].sum().round(0)
    print("\n== 绝对区间（零前视）==\n", t2.to_string())

    # 甜点带验证（更新六用的 [0,10%) 及子带）
    for lo, hi in [(0.0, 0.06), (0.0, 0.10), (0.03, 0.10)]:
        g = d[(d.dev >= lo) & (d.dev < hi)]
        print(f"带 [{lo:+.0%},{hi:+.0%}): n={len(g)}（{len(g)/len(d)*100:.0f}%） "
              f"单笔均 {g.ret_pct.mean():+.2f}% 期望合计 {g.ret_pct.sum():+.0f}pp "
              f"（占总期望 {g.ret_pct.sum()/d.ret_pct.sum()*100:.0f}%）")

    out = HERE / "buckets"
    out.mkdir(exist_ok=True)
    t1.to_csv(out / "decile.csv", encoding="utf-8-sig")
    t2.to_csv(out / "bands.csv", encoding="utf-8-sig")
    d[["symbol", "entry_date", "sig_date", "dev", "ret_pct", "reason"]].to_parquet(out / "trades_with_dev.parquet")
    (out / "baseline.json").write_text(json.dumps(base.to_dict(), ensure_ascii=False, indent=1), "utf-8")
    print("\n写出 buckets/")


if __name__ == "__main__":
    main()
