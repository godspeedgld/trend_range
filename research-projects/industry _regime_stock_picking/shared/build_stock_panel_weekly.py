"""strategy_001 预计算 —— 个股因子面板【**周频窗口口径** = 复现云端的真实行为】。

## 为什么有这个文件（2026-09-28）

云端 `cloud_code_with_industry_log.py::load_stock_panel` 的五个因子，**实际是在
「信号日（周频）序列」上滚动的**，不是日频。已在本地全量复现验证：
五个因子各 11,124~11,300 可比行 **100.00% 逐值相等**（见
`strategy_001/data_from_cloud/verify_weekly_window.py`）。

成因：外层 `SELECT * FROM ts WHERE date IN ({dl})` 被 DAI **下推进 CTE**，
而 `dl` 只含周频信号日 ⇒ 窗口只在「过了 CTE 过滤 ∧ 日期 ∈ 信号日列表」的行上滚动。
对照实验最直观：同一列 `m_lag(close,1)`，`date IN` 放连续交易日 → 前一**交易**日收盘；
放周频信号日 → 上一个**信号日**收盘（7 个交易日前）。

于是云端所谓的：
    「5 日 / 60 日换手比」→ 实为 5 **周** / 60 **周**
    「20 日均线乖离」    → 20 **周**均线乖离
    「20 日动量」        → 20 **周**动量
    「20 日均额」        → 20 **周**均额
    「20 日波动率」      → 20 个**周收益**的标准差

本文件用**本地 BigQuant 仓库**的日频数据、按**同一套周频窗口语义**重算，
使本地回测与云端口径一致（`shared/build_stock_panel.py` 是日频口径，**不动它**）。

## 窗口语义（已实测确定，逐字对齐云端）

    m_avg(x, n)   = 最近 n 行（**含当前行**）的均值；**要求满窗口**（不足 n 行 → NULL）
    m_lag(x, n)   = 向前偏移 n 行的值
    m_nanstd(x,n) = 最近 n 行（含当前行）的**样本**标准差（ddof=1，忽略 NaN）

## 与日频版（build_stock_panel.py）的差异

| 项 | 日频版 | 本版（周频） |
|---|---|---|
| 窗口行集 | 全部交易日 | **仅信号日**（周频），且先过 CTE 过滤 |
| 成交量门槛 | 20 日**均**额 > 2e7 | **当日**额 > 2e7（对齐云端 WHERE） |
| 次日可成交过滤 | 有 | **无**（云端没有这条） |
| 因子 | 日频 rolling/shift | **周频** n 行窗口 |

产物：`_cache/signal_panel_weekly.parquet`（列与日频版完全相同，供
`build_weekly_targets.py` 以 `UNIVERSE=weekly` 直接读取）。

用法：`python shared/build_stock_panel_weekly.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

import os

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "_cache"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

sys.path.insert(0, str(HERE.parent))
from shared.build_stock_panel import MIN_LISTED_BARS, signal_dates   # noqa: E402 只 import 不改

START, END = "2015-01-01", "2026-08-21"
# ★ 2026-10-12：窗口行集**起点对齐云端**。云端 SQL 的 `date IN ({dl})` 被 DAI 下推进 CTE，
#   而 dl 只含「BT_START 前最后一个信号日」起的周频信号日 ⇒ 云端窗口只能在这些行上数。
#   turn_ratio(60 周) 因此到 2018-03-02 才非 NaN、px/mom/liq(20 周) 到 2017-05-12。
#   本地原从 2015 起数 ⇒ 2017~2018 年本地 4 个因子齐全而云端只有 1~3 个，
#   复合分 mean(axis=1) 跳过 NaN ⇒ 分数不同 ⇒ 选股分叉。
#
#   ★★ 起点取值由**云端真实成交**反标定（不是猜）：云端 2017 年首笔成交 = 2017-05-15，
#      ⇒ 首个「满 20 周窗口」的信号日 = 2017-05-12 ⇒ dl 首日 = 2016-12-30（往前数第 20 个
#      信号日）。用 2016-12-30 起数时，2017-05-12 恰好只有 20 个信号日、三因子(px/mom/liq)
#      有效，复现出云端当天 6 只票**逐只一致**；用 2017-01-06 起数则 2017-05-12 全 NaN、0 只。
#      全历史逐周比对：2016-12-30 起点 vs 云端真实逐日持仓 **94.3% 集合完全一致 / Jaccard 0.974**
#      （2019 年起 ~98-100%）。置空字符串则回到"从 START(2015) 起数"的旧行为。
PANEL_WINDOW_START = os.environ.get("PANEL_WINDOW_START", "2016-12-30")
MIN_AMOUNT = 2e7                    # 云端 WHERE: amount > 2e7（**当日**额）
W_TURN_FAST, W_TURN_SLOW = 5, 60    # 单位是**周**（= 信号日行数）
W_MA = W_MOM = W_LIQ = W_VOL = 20


def load_bars() -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    """全市场日线（剔停牌）+ 真实交易日历。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    cal = pd.DatetimeIndex(pd.to_datetime(con.execute(
        f"SELECT DISTINCT date FROM stock_bar1d WHERE date >= '{START}' AND date <= '{END}' "
        f"ORDER BY date").fetchdf()["date"]))
    df = con.execute(f"""
        SELECT date, instrument AS symbol, name, close, open, pre_close, amount, turn
        FROM stock_bar1d WHERE date >= '{START}' AND date <= '{END}'
    """).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    n0 = len(df)
    df = df[df["close"].notna() & df["amount"].notna()].copy()       # 剔停牌（云端 suspended=0）
    print(f"日线 {n0:,} 行 → 剔停牌后 {len(df):,} 行")
    return df.sort_values(["symbol", "date"]).reset_index(drop=True), cal


def attach_industry(df: pd.DataFrame) -> pd.DataFrame:
    """行业归属。★ IND 开关（2026-10-12）：
      IND=component（默认，旧行为）→ stock_industry_component_daily(sw2021)，5,033 只
      IND=prefactors            → stock_prefactors_attr.sw_level_index_code/name，
                                  **5,830 只（=云端 cn_stock_prefactors 同源，池与云端对齐）**
      两源已验证：31 个一级行业同名、同日同股 100% 一致 → 换源只扩覆盖不改语义。
    """
    import os
    IND = os.environ.get("IND", "component")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    if IND == "prefactors":
        si = con.execute(f"""
            SELECT instrument AS symbol, date, sw_level1_name AS ind_name,
                   sw_level_index_code AS ind_code,
                   st_status, suspended, list_days
            FROM stock_prefactors_attr
            WHERE date >= '{START}' AND date <= '{END}' AND sw_level_index_code IS NOT NULL
        """).fetchdf()
    else:
        si = con.execute(f"""
            SELECT instrument AS symbol, date, industry_level1_name AS ind_name
            FROM stock_industry_component_daily
            WHERE date >= '{START}' AND date <= '{END}'
        """).fetchdf()
    con.close()
    si["date"] = pd.to_datetime(si["date"])
    return df.merge(si.drop_duplicates(["symbol", "date"]), on=["symbol", "date"], how="left")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    df, cal = load_bars()

    # ── listed_bars（与 build_stock_panel.py:113-114 同约定：剔停牌后 cumcount，
    #    首个交易日就在的股 += 252）──
    g = df.groupby("symbol", sort=False)
    first_seen = g["date"].transform("min")
    df["listed_bars"] = (g.cumcount()
                        + np.where(first_seen == df["date"].min(), MIN_LISTED_BARS, 0))

    sd = signal_dates(pd.Series(cal))
    print(f"信号日（周最后交易日）{len(sd)} 个：{sd[0].date()} ~ {sd[-1].date()}")

    # 执行价：下一交易日开盘（供 build_weekly_targets 的 exec_date 字段；本版不做过滤）
    next_td = pd.Series(cal[1:].values, index=cal[:-1].values)
    df["exec_open"] = g["open"].shift(-1)
    df["exec_date"] = g["date"].shift(-1)

    p = attach_industry(df[df["date"].isin(set(sd))].copy())
    if PANEL_WINDOW_START:                       # ★ 窗口行集起点对齐云端（见文件头常量说明）
        _b = len(p)
        p = p[p["date"] >= pd.Timestamp(PANEL_WINDOW_START)].copy()
        print(f"窗口起点对齐云端 {PANEL_WINDOW_START}: {_b:,} → {len(p):,} 行")
    n0 = len(p)

    # ── 云端 CTE 的五个过滤（**必须在算窗口之前**，这正是周频口径的来源）──
    # ★ 2026-10-12：过滤口径改为**与云端 WHERE 逐字对齐**。
    #   云端：st_status = 0 AND suspended = 0 AND list_days > 252 AND amount > min_amount
    #         AND sw_level_index_code IS NOT NULL
    #   本地原用「name 含 ST」+「listed_bars(交易日) > 252」—— 与云端不同源：
    #     · st_status 是显式字段（name 含 ST 会漏掉部分风险警示股 / 误伤）
    #     · list_days 是**自然日**，listed_bars 是**交易日**（252 自然日≈8.4 月 vs 252 交易日≈12 月）
    #   实测这导致约 2% 的 (股,周) 单边 NaN，进而影响 20/60 周窗口的行数。
    if "st_status" in p.columns:
        flt = {
            "非ST(st_status=0)": p["st_status"].fillna(0) == 0,
            "未停牌(suspended=0)": p["suspended"].fillna(0) == 0,
            "上市>252自然日(list_days)": p["list_days"].fillna(0) > 252,
            "当日额>2e7": p["amount"] > MIN_AMOUNT,
            "有行业归属": p["ind_name"].notna(),
        }
    else:
        flt = {
            "非ST(name含ST)": ~p["name"].fillna("").str.contains("ST"),
            "上市>252交易日(listed_bars)": p["listed_bars"] > 252,
            "当日额>2e7": p["amount"] > MIN_AMOUNT,
            "有行业归属": p["ind_name"].notna(),
        }
    mask = pd.Series(True, index=p.index)
    print("\n逐条过滤（信号日快照，对齐云端 CTE）:")
    for k, v in flt.items():
        nxt = mask & v
        print(f"  {k:<10} 剔除 {(mask.sum()-nxt.sum()):>7,} → 剩 {nxt.sum():>8,}")
        mask = nxt
    p = p[mask].copy()
    print(f"总计 {n0:,} → {len(p):,} 行（保留 {len(p)/n0:.1%}）")

    # ── ★ 周频窗口（m_avg 含当前行且要求满窗口 ⇒ rolling 默认 min_periods=n）──
    p = p.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = p.groupby("symbol", sort=False)
    print("\n算周频窗口因子 …", flush=True)
    p["turn_ratio"] = (g["turn"].transform(lambda s: s.rolling(W_TURN_FAST).mean())
                       / (g["turn"].transform(lambda s: s.rolling(W_TURN_SLOW).mean())
                          + 1e-8))                                    # 分母 +1e-8 同云端
    p["px_ma20"] = (p["close"]
                    / (g["close"].transform(lambda s: s.rolling(W_MA).mean()) + 1e-8) - 1)
    p["mom_20"] = p["close"] / g["close"].transform(lambda s: s.shift(W_MOM)) - 1
    p["liq_amount"] = g["amount"].transform(lambda s: s.rolling(W_LIQ).mean())
    p["_r"] = p["close"] / g["close"].transform(lambda s: s.shift(1)) - 1
    # ★ 2026-10-12：m_nanstd(x, n) 的 min_periods=**2**，不是满窗口！
    #   云端 `m_nanstd(close/m_lag(close,1)-1, 20)` 实测 = 可用行上的样本 std（≥2 行即算），
    #   与 rolling(20, min_periods=2) 在**全量 153,432 可比行**上最大绝对差 1.7e-14。
    #   本地原用 rolling(20)（默认 min_periods=20）⇒ 不足 20 周的老股 vol=NaN（NaN 率 6.15%
    #   vs 云端 0.59%），其权重经 1/vol 变 NaN → 被 weight>0 过滤掉、整只股消失
    #   （实测 8,580 行命中；2017 年 3 个调仓日的选股分歧全由此而来）。
    p["vol_20"] = p.groupby("symbol", sort=False)["_r"].transform(
        lambda s: s.rolling(W_VOL, min_periods=2).std(ddof=1))       # m_nanstd = 样本标准差(≥2行)

    cols = ["date", "symbol", "name", "ind_name", "close", "exec_date", "exec_open",
            "turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_20", "listed_bars"]
    p = p[cols].reset_index(drop=True)
    import os as _os
    _sfx = "_indpre" if _os.environ.get("IND", "component") == "prefactors" else ""
    out = OUT / f"signal_panel_weekly{_sfx}.parquet"
    p.to_parquet(out, index=False, compression="zstd")
    print(f"\n→ {out}  ({len(p):,} 行 × {p.shape[1]} 列)")

    print("\n每年信号日数 / 候选股数（注意：早期因窗口未满，因子为空）:")
    for y, gg in p.groupby(p["date"].dt.year):
        print(f"  {y}: {gg['date'].nunique():>2} 个信号日 / 候选 {len(gg):>7,} 行 / "
              f"四因子非空 {gg[['turn_ratio','px_ma20','mom_20','liq_amount']].notna().all(axis=1).mean():>6.1%}")


if __name__ == "__main__":
    main()
