"""更新五 · 信号扫描 — 沪深300 历史成分 668 只 × v2 动态窗（LOO 截断）分位回归线。

多进程逐股跑 shared/quantreg_sr_algo_v2（causal 口径，N_max=120/N_min=60/w=5/τ=0.9,0.1/
min_pts=3），缓存 signals_v2_members.parquet（成分过滤后）。供 backtest.py 消费。
成分过滤（铁律：股票池用当日成分）：warehouse index_component 000300.SH 当日记录。
"""
from __future__ import annotations

import sys
import time
import warnings
from multiprocessing import Pool
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ / "shared"))
warnings.filterwarnings("ignore")

PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = PROJ.parents[2] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"


def members_by_date() -> dict:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    comp = con.execute("SELECT date, member_code FROM index_component "
                       "WHERE instrument='000300.SH'").fetchdf()
    con.close()
    comp["date"] = pd.to_datetime(comp["date"])
    return {d: set(g["member_code"]) for d, g in comp.groupby("date")}


_MEMBERS: dict | None = None


def _init(members):
    global _MEMBERS
    _MEMBERS = members


COLS = ["symbol", "close", "R", "S", "p1", "p2", "dur_pattern", "chan_pattern",
        "breakout", "win_len", "win0", "truncated"]


def scan_one(args):
    sym, df = args
    from quantreg_sr_algo_v2 import rolling_lines_v2
    from quantreg_sr_algo import breakout_signals
    df = df.set_index("date").sort_index()
    sig = breakout_signals(rolling_lines_v2(df, causal=True), df["close"])
    sig = sig[sig["R"].notna()].copy()
    if len(sig) == 0:                       # 次新股/短样本：空表但列对齐
        return pd.DataFrame(columns=COLS)
    sig["symbol"] = sym
    # 成分过滤：信号日须为当日成分（最近一次成员记录 ≤ 信号日）
    md = sorted(_MEMBERS.keys())
    import bisect
    keep = np.zeros(len(sig), dtype=bool)
    for j, d in enumerate(sig.index):
        i = bisect.bisect_right(md, d) - 1
        keep[j] = i >= 0 and sym in _MEMBERS[md[i]]
    sig = sig.loc[keep]
    return sig[COLS].reset_index()


def main():
    panel = pd.read_parquet(PANEL, columns=["date", "symbol", "open", "high", "low", "close"])
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.dropna(subset=["open", "high", "low", "close"]).sort_values(["symbol", "date"])
    groups = [(s, g[["date", "close"]]) for s, g in panel.groupby("symbol")]
    members = members_by_date()
    print(f"{len(groups)} 只股票，成分日 {len(members)} 个", flush=True)

    t0 = time.time()
    with Pool(processes=10, initializer=_init, initargs=(members,)) as pool:
        parts = []
        for i, sig in enumerate(pool.imap_unordered(scan_one, groups, chunksize=4), 1):
            parts.append(sig)
            if i % 50 == 0:
                print(f"{i}/{len(groups)} 只完成，耗时 {time.time()-t0:.0f}s", flush=True)
    out = pd.concat(parts, ignore_index=True)
    out.to_parquet(HERE / "signals_v2_members.parquet", index=False)
    nb = int(out["breakout"].sum())
    print(f"完成：{len(out)} 行有效线，突破 {nb} 日，总耗时 {time.time()-t0:.0f}s")
    print(out.groupby(out["date"].dt.year)["breakout"].sum().to_string())


if __name__ == "__main__":
    main()
