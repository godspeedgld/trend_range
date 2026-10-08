"""stock_min_1m 全市场增量刷新 —— 按「缺哪几天」补齐（skill-pandadata-warehouse-main 流程）。

为什么另建：`pull_stock_min_1m.py` 虽有 `--force-month/--until`，但 `load_symbols()`
只读 HS300 成员表（成分股刷新用）；2026 各系列脚本又没有 `--force-month`。
本脚本面向**全市场**，且**只拉缺失的交易日**（增量优先，不做整月重写）。

缺口判定：某月应有交易日（本地 `trading_days`）− 分钟表该月已有日期。
  · 同时用 `stock_bar1d` 交叉印证该日确实是交易日（防 trading_days 的休市日脏数据）
  · `--until` 限制到**已收盘日**（别把当日盘中快照入库）

用法：
    python refresh_min_fullmarket.py --month 202609 --until 20260930
    python refresh_min_fullmarket.py --month 202609 --until 20260930 --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO / ".claude/skills/skill-pandadata-api-main/scripts"))

WAREHOUSE = HERE / "pandadata_warehouse"
TABLE, OUT = "stock_min_1m", HERE / "pandadata_warehouse/stock_min_1m"
DDB = WAREHOUSE / "warehouse.duckdb"
BQ = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
FIELDS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
          "volume", "amount", "num_trades"]
ROW_GROUP = 200_000


def missing_days(month: str, until: str) -> tuple[list[str], list[str]]:
    """返回 (应补交易日, 分钟表该月已有日期)。"""
    y, m = int(month[:4]), int(month[4:6])
    lo, hi = f"{y}-{m:02d}-01", f"{y}-{m:02d}-31"
    if until:
        hi = min(hi, f"{until[:4]}-{until[4:6]}-{until[6:]}")
    bq = duckdb.connect(str(BQ), read_only=True)
    cal = {str(r[0])[:10] for r in bq.execute(
        f"SELECT DISTINCT date FROM trading_days WHERE date >= '{lo}' AND date <= '{hi}'").fetchall()}
    bq.close()
    # ★ 不用 `stock_bar1d` 做交集印证：bar1d 本身可能只拉到更早的日期（本例只到 09-29），
    #   会把 09-30 这类**真实交易日**误判为"不在日历里"（2026-10-08 踩）。
    #   trading_days 的少量休市日脏数据由「空返回自动跳过」兜住 —— 拉不到就当无数据。
    dw = duckdb.connect(str(DDB), read_only=True)
    # ★ 分钟表的 date 是 "YYYYMMDD"（无横线），日历是 "YYYY-MM-DD" —— 必须归一化后再比，
    #   否则集合差恒为"全部待补"（2026-10-08 踩，本日第二次踩同类格式坑）
    have_raw = {r[0] for r in dw.execute(
        f"SELECT DISTINCT date FROM {TABLE} WHERE year='{y}' AND month='{m:02d}'").fetchall()}
    have = {f"{d[:4]}-{d[4:6]}-{d[6:]}" if "-" not in d else d for d in have_raw}
    syms = [r[0] for r in dw.execute(
        f"SELECT DISTINCT symbol FROM {TABLE} WHERE year='{y}'").fetchall()]
    dw.close()
    return sorted(cal - have), sorted(have), syms


def rebuild_view() -> int:
    con = duckdb.connect(str(DDB))
    glob = str(OUT / "year=*" / "month=*" / "*.parquet").replace("\\", "/")
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", required=True, help="YYYYMM，如 202609")
    ap.add_argument("--until", default=None, help="截止日 YYYYMMDD（务必用已收盘日）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    days, have, syms = missing_days(a.month, a.until)
    print(f"月份 {a.month}：日历应有日期 {len(have) + len(days)} 天，分钟表已有 {len(have)} 天")
    print(f"  已补: {have}")
    print(f"  ★待补: {days}")
    if not days:
        print("  无需刷新（已是最新）")
        return
    if len(syms) < 100:
        print(f"  ⚠ 该年分钟表只有 {len(syms)} 只，异常 —— 先确认年份写对")
        return
    est = len(days) * len(syms) * len(FIELDS)
    print(f"  池 = 该年分钟表全部标的 {len(syms):,} 只 → 估算 ≈ {est/1e6:.2f}M cells")
    if a.dry_run:
        return

    from pandadata_runtime import init_pandadata
    pd_ = init_pandadata()
    m = int(a.month[4:6])
    f = OUT / f"year={a.month[:4]}" / f"month={m:02d}" / "part.parquet"
    for d in days:
        t = time.time()
        try:
            df = pd_.get_stock_min(symbol=syms, start_date=d.replace("-", ""),
                                   end_date=d.replace("-", ""), fields=FIELDS, frequency="1m")
        except Exception as e:
            print(f"  {d} ✗ {type(e).__name__} {str(e)[:90]}")
            return 1
        if df is None or not len(df):
            print(f"  {d} — 无数据（可能未收盘/未发布）")
            continue
        df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        old = pd.read_parquet(f) if f.exists() else pd.DataFrame()
        df = pd.concat([old, df], ignore_index=True).drop_duplicates(
            subset=["symbol", "date", "minute"], keep="last")
        df = df.sort_values(["symbol", "date", "minute"], ignore_index=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(f, compression="zstd", index=False, row_group_size=ROW_GROUP)
        print(f"  {d}  +{len(df) - len(old):>9,} 行（合并后 {len(df):,} 行 / {df['symbol'].nunique()} 只）"
              f"  {f.stat().st_size/1e6:.1f} MB  {time.time()-t:.0f}s")

    n = rebuild_view()
    print(f"\n完成：{TABLE} 现共 {n:,} 行")
    con = duckdb.connect(str(DDB), read_only=True)
    dup = con.execute(f"""SELECT count(*) FROM (SELECT symbol,date,minute FROM {TABLE}
        WHERE year='{a.month[:4]}' GROUP BY 1,2,3 HAVING count(*)>1)""").fetchone()[0]
    print(f"  {a.month[:4]} 年主键重复: {dup} {'OK' if dup == 0 else 'FAIL'}")
    con.close()


if __name__ == "__main__":
    raise SystemExit(main())
