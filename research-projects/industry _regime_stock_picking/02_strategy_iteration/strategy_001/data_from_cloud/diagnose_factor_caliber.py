"""定位云端因子为何与本地不同 —— 逐个假设用云端真值验证。

段2 显示五个因子**全部**对不上，且中位相对差 34%~180%，远超「窗口内含停牌行」
（仅占 0.4~2.2% 行）所能解释。量级指向：**云端 WHERE 写在 CTE 内，标准 SQL 下
WHERE 先于窗口函数求值 ⇒ 被筛掉的行不进窗口**。

于是 `m_avg(close, 20)` 不是「最近 20 个交易日的均线」，而是
「最近 20 个**通过了筛选的**交易日的均线」；`m_lag(close, 20)` 是回退 20 **个存活行**，
可能跨了几个月。`amount > 2e7` 这一条尤其狠 —— 它会把低量日整片剔掉。

本脚本用**本地日线**按各种口径重算，看哪一种能对上云端导出的真值：
  V0 base      剔停牌 → rolling/shift（本地现行口径；已知对不上，作对照）
  V1 filt      剔停牌 + `amount > 2e7` → rolling/shift **只在存活行上**（= 云端 WHERE 模型）
  V2 filt_ddof0  同 V1，但 std 用 ddof=0（numpy 系 m_nanstd 很可能是 ddof=0）

用法：`python diagnose_factor_caliber.py`（纯本地，不消耗配额）
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
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

MIN_AMOUNT = 2e7
WARM = "2024-06-01"          # 预热：m_avg(turn,60) 在存活行上可能跨很久，多取些
END = "2026-08-14"
FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_stock"]
ATOL, RTOL = 1e-12, 1e-9


def load_cloud() -> pd.DataFrame:
    f = HERE / "panel_2026.parquet"
    if not f.exists():
        f = HERE / "panel_2026.csv.gz"
        df = pd.read_csv(f, compression="gzip")
    else:
        df = pd.read_parquet(f)
    df["date"] = pd.to_datetime(df["date"])
    df["ind_code"] = df["ind_code"].astype(str).str.replace(r"\.SWI$", "", regex=True)
    return df


def load_bars(symbols: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    inlist = ",".join(repr(s) for s in symbols)
    df = con.execute(f"""
        SELECT date, instrument, close, pre_close, amount, turn
        FROM stock_bar1d
        WHERE date >= '{WARM}' AND date <= '{END}' AND instrument IN ({inlist})
    """).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["instrument", "date"]).reset_index(drop=True)


def compute(df: pd.DataFrame, filt_amount: bool, ddof: int) -> pd.DataFrame:
    """按给定口径重算 5 个因子。filt_amount=True 时先筛 amount>2e7，再在存活行上 rolling。"""
    d = df[df["close"].notna() & df["amount"].notna()].copy()      # 剔停牌（云端 suspended=0）
    if filt_amount:
        d = d[d["amount"] > MIN_AMOUNT].copy()                     # 云端 WHERE 里的 amount>2e7
    g = d.groupby("instrument", sort=False)
    o = d[["date", "instrument"]].copy()
    o["turn_ratio"] = (g["turn"].transform(lambda s: s.rolling(5).mean())
                       / g["turn"].transform(lambda s: s.rolling(60).mean()))
    o["px_ma20"] = d["close"] / g["close"].transform(lambda s: s.rolling(20).mean()) - 1
    o["mom_20"] = d["close"] / g["close"].transform(lambda s: s.shift(20)) - 1
    o["liq_amount"] = g["amount"].transform(lambda s: s.rolling(20).mean())
    r = g["close"].transform(lambda s: s / s.shift(1) - 1)
    o["vol_stock"] = r.groupby(d["instrument"], sort=False).transform(
        lambda s: s.rolling(20).std(ddof=ddof))
    return o


def stats(a: pd.Series, b: pd.Series) -> dict | None:
    both = a.notna() & b.notna()
    if not both.any():
        return None
    x, y = a[both].astype(float), b[both].astype(float)
    dd = (x - y).abs()
    tol = ATOL + RTOL * y.abs()
    return {"n": int(both.sum()), "ok": float((dd <= tol).mean()),
            "med_rel": float((dd / y.abs().clip(lower=1e-12)).median())}


def main():
    cl = load_cloud()
    syms = sorted(cl["instrument"].unique())
    print(f"云端 panel: {len(cl):,} 行 / {cl.date.nunique()} 调仓日 / {len(syms):,} 只")
    bars = load_bars(syms)
    print(f"本地日线（{WARM}~{END}，限云端股票）: {len(bars):,} 行 / "
          f"{bars.instrument.nunique():,} 只\n")

    variants = {
        "V0 base (剔停牌, 全交易日)": dict(filt_amount=False, ddof=1),
        "V1 filt (剔停牌+额>2e7, 存活行上)": dict(filt_amount=True, ddof=1),
        "V2 filt + ddof=0": dict(filt_amount=True, ddof=0),
    }
    results = {}
    for name, kw in variants.items():
        o = compute(bars, **kw)
        # 只看云端那 31 个调仓日
        o = o[o["date"].isin(set(cl["date"]))]
        m = cl.merge(o, on=["date", "instrument"], how="inner", suffixes=("_c", "_v"))
        results[name] = {f: stats(m[f"{f}_c"], m[f"{f}_v"]) for f in FACTORS}
        results[name]["_n"] = len(m)

    for name, res in results.items():
        print("=" * 92)
        print(f"{name}   可比行 {res['_n']:,}")
        print("=" * 92)
        print(f"  {'因子':<13}{'可比行':>9}{'容差内%':>11}{'中位相对差':>13}  判定")
        for f in FACTORS:
            st = res[f]
            if st is None:
                print(f"  {f:<13}{'—':>9}  （无可比行）")
                continue
            verdict = "**匹配**" if st["ok"] > 0.99 else ("部分" if st["ok"] > 0.5 else "不匹配")
            print(f"  {f:<13}{st['n']:>9,}{st['ok']:>11.2%}{st['med_rel']:>13.3g}  {verdict}")
        print()

    print("=" * 92)
    print("结论：哪个变体全部『匹配』，就是云端 m_* 的真实语义；若都不匹配，说明还有别的因素")
    print("=" * 92)


if __name__ == "__main__":
    main()
