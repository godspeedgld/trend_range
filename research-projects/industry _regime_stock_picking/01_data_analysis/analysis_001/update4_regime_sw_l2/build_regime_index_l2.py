"""analysis_001 更新四 —— 变盘指数改用**申万二级行业**（本地 117 个）计算。

与 analysis_001 的 L1 版（申万一级 31 个）**算法完全相同**，只是横截面从 31 个一级行业
换成 117 个二级行业（`stock_industry_component` 的 sw2021 二级，4 位前缀）。

 ① Rank_std_{i,t} = |Rank_{i,t} − Rank_{i,t−220}| / N      N=117；Rank=trailing-21日收益率截面排名
 ② R_t = (1/N) Σ Rank_std_{i,t}
 ③ I_t = std_220(R_t)
 ④ I'_t = Mov_20(I_t)     → T'_t = ΔI'_t  （T'<0 = 变盘指数下行）

⚠ 关于 N：① 里的 ÷N 只是缩放，`I_t` 线性缩放后 `T'` 的**符号不变** ——
   所以 N 的取值不影响"下行/上行"的分类。二级与一级的差异来自**横截面成分不同**
   （117 个行业的排名动态 vs 31 个），而不是归一化系数。

产物：`../_precomputed/regime_index_l2.parquet`（与 L1 版并列，供复用）
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PRE = HERE.parent / "_precomputed"           # analysis_001/_precomputed
ROOT = HERE.parents[4]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

START, END = "2015-01-05", "2026-08-21"
RET_WIN, LOOKBACK, VOL_WIN, SMOOTH = 21, 220, 220, 20   # 与 L1 版完全一致


def main():
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    # 二级 = 4 位前缀（sw2021）
    pre = con.execute("""SELECT DISTINCT substr(industry_instrument,1,4) AS p4
                         FROM stock_industry_component WHERE industry='sw2021'""").df()
    plist = "','".join(sorted(pre["p4"]))
    ind = con.execute(f"""SELECT substr(instrument,1,4) AS p4, date, avg(change_ratio) AS chg
                          FROM stock_industry_bar1d
                          WHERE substr(instrument,1,4) IN ('{plist}')
                            AND date >= '{START}' AND date <= '{END}'
                          GROUP BY 1, 2 ORDER BY 1, 2""").df()
    con.close()
    ind["date"] = pd.to_datetime(ind["date"])
    N = ind["p4"].nunique()

    piv = ind.pivot(index="date", columns="p4", values="chg").sort_index()
    cum = np.log1p(piv.fillna(0)).cumsum()
    ret = np.expm1(cum - cum.shift(RET_WIN))
    rk = ret.rank(axis=1, pct=False)
    rank_std = (rk - rk.shift(LOOKBACK)).abs() / N
    R = rank_std.mean(axis=1)
    I = R.rolling(VOL_WIN, min_periods=VOL_WIN).std()
    out = pd.DataFrame({"R": R, "I": I})
    out[f"I_smooth{SMOOTH}"] = I.rolling(SMOOTH, min_periods=SMOOTH).mean()
    out["T_prime"] = out[f"I_smooth{SMOOTH}"].diff()
    out["down"] = out["T_prime"] < 0
    out = out.dropna(subset=["T_prime"]).reset_index()

    # 与 L1 版对照
    l1 = pd.read_parquet(PRE / "regime_index.parquet")[["date", "down"]].rename(
        columns={"down": "down_l1"})
    m = out.merge(l1, on="date", how="inner")
    agree = (m["down"] == m["down_l1"]).mean()

    out.to_parquet(PRE / "regime_index_l2.parquet", index=False)
    print(f"二级变盘指数 {len(out):,} 行 / {N} 个二级行业 / "
          f"{out.date.min().date()} ~ {out.date.max().date()} | 下行日占比 {out.down.mean()*100:.1f}%")
    print(f"与一级版对照：重叠 {len(m):,} 日，下行/上行判定**一致率 {agree*100:.1f}%** "
          f"（不一致 {int((1-agree)*len(m)):,} 日）")


if __name__ == "__main__":
    main()
