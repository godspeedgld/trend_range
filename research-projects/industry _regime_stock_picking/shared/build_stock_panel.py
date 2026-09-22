"""strategy_001 预计算 —— 个股因子面板（信号日 × 候选股）。

个股池（用户 2026-09-22 定）：**当期三指数成分**（HS300 ∪ CSI500 ∪ CSI1000，每日快照），
严格 point-in-time、零前视。本地 `index_component` 三指数逐日成分自 2015-01-05 起齐备。

口径铁律（2026-09-22 数据核查）：
  ① `close` 已是**后复权价** → 日收益用 `close/pre_close − 1`（含分红再投资），
     **绝不再乘 `adjust_factor`**（双重复权），**不用 `change_ratio`**（未复权，除权日偏差达 9.9%）。
  ② 停牌 = close 与 amount 均 NULL → 直接剔除该行（当日不可交易）。
  ③ `name` 是历史快照（单股最多 8 个曾用名）→ 可做 ST 历史判定。
  ④ `amount` 单位 = 元（实测茅台 42.8 亿/日）。

因子（用户 2026-09-22 指定，四因子，方向由 regime 决定）：
  turn_ratio  5日均换手 / 60日均换手
  px_ma20     close / MA20 − 1
  mom_20      20 日收益率
  liq_amount  20 日均成交额
  vol_20      20 日波动率（仓位加权用）

产物：`_cache/signal_panel.parquet` —— 已过全部过滤的候选股，仅信号日。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
OUT = HERE / "_cache"

START, END = "2015-01-01", "2026-08-21"     # END 对齐 component_daily / index_component
INDEXES = ["000300.SH", "000905.SH", "000852.SH"]   # HS300 ∪ CSI500 ∪ CSI1000

MIN_LISTED_BARS = 252       # 上市 > 252 个交易日
MIN_LIQ_AMOUNT = 2e7        # 20 日均成交额 > 2000 万
TURN_WIN_FAST, TURN_WIN_SLOW = 5, 60
MA_WIN, MOM_WIN, LIQ_WIN, VOL_WIN = 20, 20, 20, 20


def load_calendar() -> pd.DatetimeIndex:
    """A 股真实交易日历。

    ★ 陷阱（2026-09-22 实测）：`trading_days` 表含 **167 个实际休市日**
      （2015-02-18 春节、2015-05-01、2015-09-03、2017-04-03 清明 …），**不能当 A 股
      交易日历用**。若拿它算"下一交易日"，凡是「信号日后紧跟长假」的整周候选股都会被
      `次日可成交` 误剔（2017 年实测丢 6 周：03-31/04-28/05-26/09-29 …）。
      改用 `stock_bar1d` 的实际出现日期 = 2,828 天 = 真实交易日。
    """
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    td = con.execute(f"SELECT DISTINCT date FROM stock_bar1d "
                     f"WHERE date >= '{START}' AND date <= '{END}' ORDER BY date").fetchdf()
    con.close()
    return pd.DatetimeIndex(pd.to_datetime(td["date"]))


def load_stock_bars() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """个股日线（仅成分股；停牌行剔除）。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    codes = [r[0] for r in con.execute(
        f"SELECT DISTINCT member_code FROM index_component "
        f"WHERE instrument IN ({','.join(repr(c) for c in INDEXES)})").fetchall()]
    inlist = ",".join(repr(c) for c in codes)
    print(f"三指数历史并集 {len(codes):,} 只（当期成分池）")
    df = con.execute(f"""
        SELECT date, instrument AS symbol, close, open, pre_close, turn, amount, name
        FROM stock_bar1d
        WHERE instrument IN ({inlist}) AND date >= '{START}' AND date <= '{END}'
    """).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    n_all = len(df)
    df = df[df["close"].notna() & df["amount"].notna()].copy()      # 剔停牌
    print(f"日线 {n_all:,} 行 → 剔停牌后 {len(df):,} 行")
    return df.sort_values(["symbol", "date"]).reset_index(drop=True), load_calendar()


def add_factors(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("symbol", sort=False)
    print("  算因子 …", flush=True)
    df["ret"] = df["close"] / df["pre_close"] - 1          # 后复权口径（含分红）
    df["turn_ratio"] = g["turn"].transform(
        lambda s: s.rolling(TURN_WIN_FAST).mean() / s.rolling(TURN_WIN_SLOW).mean())
    df["px_ma20"] = g["close"].transform(lambda s: s / s.rolling(MA_WIN).mean() - 1)
    df["mom_20"] = g["close"].transform(lambda s: s / s.shift(MOM_WIN) - 1)
    df["liq_amount"] = g["amount"].transform(lambda s: s.rolling(LIQ_WIN).mean())
    df["vol_20"] = g["ret"].transform(lambda s: s.rolling(VOL_WIN).std())
    # 上市以来有效交易日数。★ 池子起点截断修正：首个交易日就在的股必是老股（上市日不可知），
    #   若按 cumcount 从 0 起算会被误判为次新股 —— 2015 年整年会被 MIN_LISTED_BARS 剔光。
    first_seen = g["date"].transform("min")
    df["listed_bars"] = g.cumcount() + np.where(first_seen == df["date"].min(), MIN_LISTED_BARS, 0)
    # 执行价：下一交易日开盘（t 日决策 → t+1 开盘成交）
    df["exec_open"] = g["open"].shift(-1)
    df["exec_date"] = g["date"].shift(-1)
    return df


def attach_industry(df: pd.DataFrame) -> pd.DataFrame:
    """个股 asof 一级行业归属（component_daily 已前向填充，日频）。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    si = con.execute(f"""
        SELECT instrument AS symbol, date, industry_level1_name AS ind_name
        FROM stock_industry_component_daily
        WHERE date >= '{START}' AND date <= '{END}'
    """).fetchdf()
    con.close()
    si["date"] = pd.to_datetime(si["date"])
    return df.merge(si, on=["symbol", "date"], how="left")


def attach_membership(df: pd.DataFrame) -> pd.DataFrame:
    """当日是否属于三指数之一（严格 point-in-time）。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mc = con.execute(f"""
        SELECT DISTINCT instrument AS idx, date, member_code AS symbol
        FROM index_component
        WHERE instrument IN ({','.join(repr(c) for c in INDEXES)})
          AND date >= '{START}' AND date <= '{END}'
    """).fetchdf()
    con.close()
    mc["date"] = pd.to_datetime(mc["date"])
    mc = mc.drop_duplicates(["symbol", "date"])
    return df.merge(mc[["symbol", "date"]].assign(in_index=True), on=["symbol", "date"], how="left")


def signal_dates(dates: pd.Series) -> list:
    """每周最后一个交易日。"""
    d = pd.DatetimeIndex(sorted(dates.unique()))
    key = pd.Series(d, index=d).groupby([d.isocalendar().year.values, d.isocalendar().week.values])
    return sorted(pd.DatetimeIndex(key.max().values))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, cal = load_stock_bars()
    df = add_factors(df)
    df = attach_industry(df)
    df = attach_membership(df)

    sd = signal_dates(pd.Series(cal))
    print(f"信号日（周最后交易日）{len(sd)} 个：{sd[0].date()} ~ {sd[-1].date()}")

    panel = df[df["date"].isin(set(sd))].copy()
    n0 = len(panel)

    # t+1 执行必须是**紧邻的下一个交易日**：若中间有停牌，`shift(-1)` 会滑到复牌后那天，
    # 等于假设「停牌期间也能按复牌开盘价成交」→ 剔除这类行。
    next_td = pd.Series(cal[1:].values, index=cal[:-1].values)

    # ── 过滤（信号日口径）──
    flt = {
        "在成分内": panel["in_index"].notna(),
        "有行业归属": panel["ind_name"].notna(),
        "上市>252": panel["listed_bars"] >= MIN_LISTED_BARS,
        "非ST": ~panel["name"].fillna("").str.contains("ST"),
        "额>2000万": panel["liq_amount"] > MIN_LIQ_AMOUNT,
        "四因子非空": panel[["turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_20"]].notna().all(axis=1),
        "次日可成交": panel["exec_open"].notna() & (panel["exec_date"] == panel["date"].map(next_td)),
    }
    mask = pd.Series(True, index=panel.index)
    print("\n逐条过滤（信号日快照）:")
    for k, v in flt.items():
        nxt = mask & v
        print(f"  {k:<10} 剔除 {(mask.sum()-nxt.sum()):>7,} → 剩 {nxt.sum():>8,}")
        mask = nxt
    panel = panel[mask].copy()
    print(f"总计 {n0:,} → {len(panel):,} 行（保留 {len(panel)/n0:.1%}）")

    cols = ["date", "symbol", "name", "ind_name", "close", "exec_date", "exec_open",
            "turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_20", "listed_bars"]
    panel = panel[cols].reset_index(drop=True)
    panel.to_parquet(OUT / "signal_panel.parquet", index=False)
    print(f"\n→ {OUT}/signal_panel.parquet  ({len(panel):,} 行 × {len(cols)} 列)")

    # ── 抽查 ──
    print("\n每年信号日数与候选股数:")
    for y, g in panel.groupby(panel["date"].dt.year):
        print(f"  {y}: {g['date'].nunique():>2} 个信号日 / 候选 {len(g):>7,} 行 "
              f"/ 均值 {len(g)/g['date'].nunique():.0f} 只")
    print(f"\n行业数 {panel['ind_name'].nunique()}；单信号日行业覆盖抽查（最后一个信号日）:")
    last = panel[panel["date"] == panel["date"].max()]
    print("  " + ", ".join(f"{k}:{v}" for k, v in last["ind_name"].value_counts().sort_index().items()))


if __name__ == "__main__":
    main()
