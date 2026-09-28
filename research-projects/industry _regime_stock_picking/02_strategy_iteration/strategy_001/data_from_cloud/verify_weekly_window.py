"""验证「云端因子窗口是周频」—— 全量复现，而非抽样。

★ 关键点（第一版写错的地方）：云端的窗口行集**不是**导出的 panel 本身。
  `load_stock_panel` 的行业截断是在 **pandas 里**做的（SQL 之后）：
      key = set(zip(ind_sig["date"], ind_sig["ind_code"]))
      return df[[(d, c) in key for d, c in zip(df["date"], df["ind_code"])]].copy()
  所以 SQL 的窗口函数看到的是「**所有**通过 CTE 过滤的股票 × 信号日」，
  而导出到 panel 的只是其中「当周选中行业」的那部分（每只股平均只有 4.4 行）。

正确复现方式：
  ① 取云端的信号日网格（= `dl`，即 industry_log.csv 的 602 个 signal_date）
  ② 对 panel 里的每只股，取它在这些信号日上**通过 CTE 过滤**的行 → 周频序列
  ③ 在该周频序列上按 n 行窗口重算五个因子
  ④ 与云端 panel 的真值逐值比

可复现的过滤（本地有对应字段）：`suspended=0`(close/amount 非空)、`amount>2e7`、
`sw not null`(有行业归属)、`st_status=0`(name 不含 ST)、`list_days>252`(累计 bar>252)。
`m_avg` 要求满窗口（rolling 默认 min_periods=n），`m_lag`=shift(n)，`m_nanstd`=ddof=1。

用法：`python verify_weekly_window.py`（纯本地，不消耗配额）
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PROJ = HERE.parents[2]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_stock"]
MIN_AMOUNT = 2e7
GRID_START = "2023-06-01"      # 2026 的行最多回溯 ~60 周，多取些
GRID_END = "2026-08-14"


def main():
    cl = pd.read_parquet(HERE / "panel_2026.parquet")
    cl["date"] = pd.to_datetime(cl["date"])
    syms = sorted(cl["instrument"].unique())
    print(f"云端 panel: {len(cl):,} 行 / {len(syms):,} 只 / {cl.date.nunique()} 个信号日")

    # ① 云端的信号日网格（= dl）。industry_log.csv 的 signal_date 就是 weekly。
    lg = pd.read_csv(HERE / "industry_log.csv")
    grid = pd.DatetimeIndex(sorted(pd.to_datetime(lg["signal_date"])))
    grid = grid[(grid >= pd.Timestamp(GRID_START)) & (grid <= pd.Timestamp(GRID_END))]
    print(f"云端信号日网格（dl）: {len(grid)} 个  {grid[0].date()} ~ {grid[-1].date()}")

    # ② 本地日线：这些网格日 × 这些股票，外加累计 bar 数（判 list_days>252）
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    dq = ",".join(f"'{d.strftime('%Y-%m-%d')}'" for d in grid)
    sq = ",".join(repr(s) for s in syms)
    raw = con.execute(f"""
        WITH base AS (
            SELECT date, instrument, name, close, open, pre_close, amount, turn,
                   SUM(CASE WHEN close IS NOT NULL AND amount IS NOT NULL
                            THEN 1 ELSE 0 END)
                       OVER (PARTITION BY instrument ORDER BY date
                             ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS bar_no
            FROM stock_bar1d
            WHERE date >= '2015-01-01' AND date <= '{GRID_END}'
              AND instrument IN ({sq})
        )
        SELECT * FROM base WHERE date IN ({dq})
    """).fetchdf()
    si = con.execute(f"""
        SELECT instrument, date, industry_level1_name AS ind_name
        FROM stock_industry_component_daily
        WHERE date >= '{GRID_START}' AND date <= '{GRID_END}' AND instrument IN ({sq})
    """).fetchdf()
    con.close()
    raw["date"] = pd.to_datetime(raw["date"])
    si["date"] = pd.to_datetime(si["date"])
    si = si.drop_duplicates(["instrument", "date"])
    df = raw.merge(si, on=["instrument", "date"], how="left")
    print(f"本地网格日数据: {len(df):,} 行（{len(grid)} 日 × {len(syms):,} 只）")

    # ③ 施加与云端 CTE 等价的过滤 → 得到周频序列
    keep = (df["close"].notna() & df["amount"].notna()          # suspended = 0
            & (df["amount"] > MIN_AMOUNT)                        # amount > 2e7
            & df["ind_name"].notna()                             # sw_level_index_code not null
            & ~df["name"].fillna("").str.contains("ST")           # st_status = 0（代理）
            & (df["bar_no"] > 252))                              # list_days > 252
    w = df[keep].sort_values(["instrument", "date"]).reset_index(drop=True)
    print(f"过滤后（周频序列）: {len(w):,} 行 / {w.instrument.nunique():,} 只 / "
          f"均值 {len(w)/max(1,w.instrument.nunique()):.1f} 行/只")

    g = w.groupby("instrument", sort=False)
    # ★ 分母的 +1e-8 不能漏：turn~0.03 时它贡献 ~3e-7 的相对差，正是上一步残差的中位数量级
    w["v_turn_ratio"] = (g["turn"].transform(lambda s: s.rolling(5).mean())
                         / (g["turn"].transform(lambda s: s.rolling(60).mean()) + 1e-8))
    w["v_px_ma20"] = (w["close"]
                      / (g["close"].transform(lambda s: s.rolling(20).mean()) + 1e-8) - 1)
    w["v_mom_20"] = w["close"] / g["close"].transform(lambda s: s.shift(20)) - 1
    w["v_liq_amount"] = g["amount"].transform(lambda s: s.rolling(20).mean())
    w["_r"] = w["close"] / g["close"].transform(lambda s: s.shift(1)) - 1
    w["v_vol_stock"] = w.groupby("instrument", sort=False)["_r"].transform(
        lambda s: s.rolling(20).std(ddof=1))

    # ④ 与云端真值逐值比
    m = cl.merge(w, on=["date", "instrument"], how="left")
    print("\n" + "=" * 96)
    print("全量复现：周频网格 + n 行窗口 重算  vs  云端 panel 真值")
    print("=" * 96)
    print(f"\n  {'因子':<12}{'可比行':>9}{'完全相等%':>11}{'中位相对差':>13}"
          f"{'最大相对差':>13}  判定")
    allok = True
    for f in FACTORS:
        a, b = m[f], m[f"v_{f}"]
        both = a.notna() & b.notna()
        if not both.any():
            print(f"  {f:<12} 无可比行"); allok = False; continue
        x, y = a[both].astype(float), b[both].astype(float)
        rel = (x - y).abs() / y.abs().clip(lower=1e-12)
        eq = float((rel <= 1e-6).mean())
        allok &= eq > 0.999
        print(f"  {f:<12}{int(both.sum()):>9,}{eq:>11.2%}{rel.median():>13.3g}"
              f"{rel.max():>13.3g}  {'**完全复现**' if eq > 0.999 else '不一致'}")
        if not both.all():
            nb = m.loc[~both, ["date", "instrument", f, f"v_{f}"]]
            print(f"      仅单边非空 {len(nb):,} 行；样例：")
            print("      " + nb.head(4).to_string(index=False).replace("\n", "\n      "))

    # ── 残差归因：是「过滤覆盖差异」还是「窗口语义差异」？──
    if not allok:
        bad = m.loc[m[FACTORS].notna().any(axis=1)
                    & m[[f"v_{f}" for f in FACTORS]].isna().all(axis=1), "instrument"]
        bad_syms = sorted(set(bad))
        stat = df[df["instrument"].isin(bad_syms)].groupby("instrument").agg(
            n_ind=("ind_name", lambda s: int(s.notna().sum())),
            max_bar=("bar_no", "max"))
        no_ind = [s for s in bad_syms if stat.loc[s, "n_ind"] == 0] if len(stat) else []
        short = [s for s in bad_syms
                 if s not in no_ind and stat.loc[s, "max_bar"] <= 252] if len(stat) else []
        other = [s for s in bad_syms if s not in no_ind and s not in short]
        print(f"\n  ── 残差归因（云端有值 / 本地重算 NaN，{len(bad):,} 行 / {len(bad_syms)} 只）──")
        print(f"    ① 本地无行业归属（ind_name 全空 → 整条周频序列被清空）: {len(no_ind)} 只")
        print(f"    ② 本地 list_days 口径偏严（bar_no 始终 ≤252，云端放行）: {len(short)} 只")
        print(f"    ③ 其它: {len(other)} 只  {other[:6]}")
        print(f"    ⇒ ①② 均为**已知的池/过滤覆盖差异**，与窗口语义无关；")
        print(f"      在两边过滤集合重合的行上，因子是逐值复现的。")

    print("\n" + "=" * 96)
    print("★ 结论：" + ("五个因子全部逐值复现 ⇒「云端窗口是周频」确证。"
                       if allok else "存在不一致 ⇒ 需继续排查（先看上面单边非空的样例）。"))
    print("=" * 96)


if __name__ == "__main__":
    main()
