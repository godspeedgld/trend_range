"""analysis_001 更新六 预计算 —— **行业池**（周频，申万一级 31 行业）。

借用另一个策略的 L0/L1 框架，但**只用"强者恒强"那一支**（用户指定）：

  L0  变盘指数 T′ 的符号
        T′ < 0（收敛/格局稳定）→ 启用行业池
        T′ ≥ 0（发散/格局混乱）→ **行业池为空**（不选行业）
  L1  启用时，用 **240 日动量**给 31 个一级行业排名 → 取前 **TOP_IND=3**
  （不做 L2 信号稳定性过滤 —— 主档；`WITH_L2=1` 可加做对照）

频率：**周频**。每周最后一个交易日为信号日，**下一交易日开始生效**（无前视）。

产物：`../_precomputed/industry_pool.parquet`
  (date, p2, rank_in_pool) —— **日频展开**，每个交易日 → 生效的 3 个行业及其池内排名；
  行业池为空的日子不出现在表里（策略侧查不到即视为空池 → 全部剔除）。
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PRE = HERE.parent / "_precomputed"
ROOT = HERE.parents[4]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

START, END = "2015-01-05", "2026-08-21"
MOM_WINDOW = 240          # L1 因子：240 日动量
TOP_IND = int(os.environ.get("TOP_IND", "3"))
WITH_L2 = os.environ.get("WITH_L2", "0") == "1"   # 是否加信号稳定性过滤（对照用）


def main():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    pre = con.execute("""SELECT DISTINCT substr(industry_instrument,1,2) AS p2
                         FROM stock_industry_component WHERE industry='sw2021'""").df()
    plist = "','".join(sorted(pre["p2"]))
    ind = con.execute(f"""SELECT substr(instrument,1,2) AS p2, date, avg(change_ratio) AS chg
                          FROM stock_industry_bar1d
                          WHERE substr(instrument,1,2) IN ('{plist}')
                            AND date >= '2014-01-01' AND date <= '{END}'
                          GROUP BY 1, 2 ORDER BY 1, 2""").df()
    con.close()
    ind["date"] = pd.to_datetime(ind["date"])

    # 行业指数点位（等权成分收益累乘）→ 240 日动量
    piv = ind.pivot(index="date", columns="p2", values="chg").sort_index()
    level = np.exp(np.log1p(piv.fillna(0)).cumsum())
    mom240 = level / level.shift(MOM_WINDOW) - 1.0

    # 变盘指数 T′（复用 analysis_001 的一级版）
    rg = pd.read_parquet(PRE / "regime_index.parquet")[["date", "T_prime"]]
    rg["date"] = pd.to_datetime(rg["date"])
    rg = rg.set_index("date")["T_prime"]

    cal = piv.index[(piv.index >= pd.Timestamp(START)) & (piv.index <= pd.Timestamp(END))]
    # 周频信号日 = 每周最后一个交易日
    s = pd.Series(cal, index=cal)
    weekly = pd.DatetimeIndex(s.groupby(cal.to_period("W")).last().values)

    rows, prev_set, stats = [], None, {"weeks": 0, "active": 0, "empty": 0, "blocked_l2": 0}
    for k, d in enumerate(weekly):
        stats["weeks"] += 1
        td = rg.get(d, np.nan)
        picked = []
        if pd.notna(td) and td < 0:                       # L0：仅 T′<0 才选行业
            f = mom240.loc[d].dropna()
            if len(f) >= TOP_IND:
                picked = f.nlargest(TOP_IND).index.tolist()
        if WITH_L2 and picked:
            cur = set(picked)
            if prev_set is not None and cur != prev_set:
                stats["blocked_l2"] += 1
                picked = []                                # L2：有轮换 → 空仓
            prev_set = cur
        if picked:
            stats["active"] += 1
        else:
            stats["empty"] += 1
        # 生效区间 = 下一交易日起，到下一个信号日
        d_next = weekly[k + 1] if k + 1 < len(weekly) else cal[-1]
        eff = cal[(cal > d) & (cal <= d_next)]
        for dt in eff:
            for r, p2 in enumerate(picked, 1):
                rows.append({"date": dt, "p2": p2, "rank_in_pool": r})

    pool = pd.DataFrame(rows)
    pool.to_parquet(PRE / f"industry_pool{'_l2' if WITH_L2 else ''}.parquet", index=False)
    n_days = pool["date"].nunique() if len(pool) else 0
    print(f"行业池: {len(pool):,} 行 / 覆盖 {n_days:,} 个交易日（{len(cal):,} 个交易日中）")
    l2 = f" | L2 拦下 {stats['blocked_l2']} 周" if WITH_L2 else ""
    print(f"  周频信号 {stats['weeks']} 周 | 行业池有效 {stats['active']} 周 | "
          f"空池 {stats['empty']} 周（{stats['empty']/stats['weeks']*100:.1f}%）{l2}")


if __name__ == "__main__":
    main()
