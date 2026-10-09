"""stock_bar1d 近端补齐 —— 全市场最近若干个交易日（用户 2026-10-08 指定）。

背景：`stock_bar1d` 全市场（≥5,000 只/日）最后一天是 **2026-08-21**，其后 26 个交易日
（08-24 ~ 09-29）只有 3 只地产股（当时定向补的）→ 与指数表（已到 09-29）不对齐。

与既有 `refresh_stock_bar1d.py` 的区别（故另建脚本，不动那个）：
  · 该脚本 `load_syms()` 只取**沪深300 成分 668 只**，且用 `SELECT *`（违反列表）；
  · 本脚本：池 = 本地 stock_bar1d 全部标的 ∪ cn_stock_basic_info（抓新上市）；
    列 = **严格按 references/data_tables.md 的 16 列**。

★ 2026-10-09 两处修正（此前会导致"静默零拉取"和批次无序）：
  ① 断点改为**按日期区间隔离**（`{"range":[start,end],"done":[...]}`）。原实现存成纯标的
     列表、不含区间 → 换区间重跑时每只都被判成"已完成"，todo=0，**一行不拉却报成功**。
     旧版纯列表 ckpt 一律忽略（入库按 (instrument,date) 去重，重拉幂等）。
  ② 批次按用户指定优先级排序：**沪深300 → 中证500 → 中证1000 → 中证2000 → 其他**
     （用 index_component 全期并集，仅决定先后；配额中途耗尽时重要组已拉完）。

用法：python pull_bar1d_recent.py --start 2026-09-30 --end 2026-10-08 [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
TABLE, SOURCE = "stock_bar1d", "cn_stock_bar1d"
BATCH = 300
CKPT = ROOT / "_pull_bar1d_recent_ckpt.json"

# 用户指定的批次优先级：沪深300 → 中证500 → 中证1000 → 中证2000 → 其他。
# 意义同 pull_min_year_group.py：配额中途耗尽时，**重要的组已经拉完**。
# 用指数成分的**历史并集**（index_component 全期），仅决定批次先后，不影响语义。
INDEX_PRIORITY = [("000300.SH", "沪深300"), ("000905.SH", "中证500"),
                  ("000852.SH", "中证1000"), ("932000.CSI", "中证2000")]


def order_by_priority(syms: list[str]) -> list[str]:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    rest, out = set(syms), []
    for inst, name in INDEX_PRIORITY:
        grp = {r[0] for r in con.execute(
            "SELECT DISTINCT member_code FROM index_component WHERE instrument=?",
            [inst]).fetchall()}
        hit = sorted(rest & grp)
        print(f"   {name:8} {len(hit):>5} 只")
        out += hit
        rest -= grp
    con.close()
    print(f"   其他      {len(rest):>5} 只")
    return out + sorted(rest)


def read_ckpt(start: str, end: str) -> set[str]:
    """断点按**日期区间**隔离。

    ★ 2026-10-09 修：原实现把 ckpt 存成纯标的列表、不含区间 → 换区间重跑时每只都被
      判成"已完成"，todo=0，**一行不拉却打印"完成"**。旧版列表格式一律忽略（宁可重拉，
      入库有 (instrument,date) 主键去重，幂等）。
    """
    if not CKPT.exists():
        return set()
    raw = json.loads(CKPT.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and raw.get("range") == [start, end]:
        return set(raw.get("done", []))
    why = raw.get("range") if isinstance(raw, dict) else "旧版纯列表"
    print(f"（断点区间 {why} ≠ 本次 [{start}, {end}] → 忽略旧断点，从头拉）")
    return set()


def write_ckpt(start: str, end: str, done: set[str]):
    CKPT.write_text(json.dumps({"range": [start, end], "done": sorted(done)},
                               ensure_ascii=False), encoding="utf-8")

# ★ 严格按 data_tables.md 的 cn_stock_bar1d 定义列（16 列），禁 SELECT *
COLS = ["instrument", "date", "name", "open", "high", "low", "close", "pre_close",
        "volume", "amount", "turn", "deal_number", "change_ratio", "adjust_factor",
        "upper_limit", "lower_limit"]


def load_syms() -> list[str]:
    """池 = 本地已有个股 ∪ 标的母表（母表可抓到 08-21 之后新上市的）。"""
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    loc = {r[0] for r in con.execute(f"SELECT DISTINCT instrument FROM {TABLE}").fetchall()}
    con.close()
    try:
        from bigquant import dai
        ext = set(dai.query("SELECT instrument FROM cn_stock_basic_info").df()["instrument"])
    except Exception as e:
        print(f"（母表取用失败，仅用本地池: {str(e)[:60]}）")
        ext = set()
    return sorted(loc | ext)


def ingest(df: pd.DataFrame) -> None:
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, grp in df.groupby("year"):
        out = ROOT / TABLE / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            grp = pd.concat([pd.read_parquet(out), grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def rebuild_view() -> tuple[int, int]:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n, ns = con.execute(f"SELECT count(*), count(DISTINCT instrument) FROM {TABLE}").fetchone()
    con.close()
    return n, ns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-22")
    ap.add_argument("--end", default="2026-09-29")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    syms = load_syms()
    print(f"① 池 = 本地 ∪ 母表 = {len(syms):,} 只 · 区间 {a.start} ~ {a.end}")
    print("   批次优先级（沪深300 → 中证500 → 中证1000 → 中证2000 → 其他）：")
    syms = order_by_priority(syms)
    est = len(syms) * 26 * len(COLS)
    print(f"   估算上限 ≈ {est/1e6:.2f}M cells（实际按每天在市只数）")
    if a.dry_run:
        return

    from bigquant import dai
    done_set = read_ckpt(a.start, a.end)
    todo = [s for s in syms if s not in done_set]
    print(f"② 断点续传：已完成 {len(done_set)}，待拉 {len(todo)}")

    t0, total = time.time(), 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        in_list = ",".join(f"'{s}'" for s in batch)
        sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} WHERE instrument IN ({in_list}) "
               f"AND date >= '{a.start}' AND date <= '{a.end}'")
        df = None
        for attempt in range(3):
            try:
                df = dai.query(sql).df()[COLS]
                break
            except Exception as e:
                print(f"   重试 {attempt+1}/3: {str(e)[:80]}")
                time.sleep(5 * (attempt + 1))
        if df is None:
            print(f"   批 {i//BATCH+1} 三次失败，断点已存，重跑续传")
            break
        if len(df):
            ingest(df)
            total += len(df)
        done_set.update(batch)
        write_ckpt(a.start, a.end, done_set)
        print(f"   批 {i//BATCH+1:>3}: {len(batch):>4} 只 → {len(df):>7,} 行  累计 {total:>9,}")

    n, ns = rebuild_view()
    print(f"\n③ 完成：本次 +{total:,} 行；{TABLE} 现 {n:,} 行 / {ns:,} 只")

    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    print("\n④ 校验：近端每日只数（应与 ~5,500 同量级）")
    print(con.execute(f"""SELECT date::VARCHAR AS d, count(*) AS n FROM {TABLE}
        WHERE date >= TIMESTAMP '{a.start}' GROUP BY 1 ORDER BY 1""").fetchdf().to_string(index=False))
    dup = con.execute(f"""SELECT count(*) FROM (SELECT instrument, date FROM {TABLE}
        GROUP BY 1,2 HAVING count(*) > 1)""").fetchone()[0]
    print(f"\n   全表主键重复: {dup} {'OK' if dup == 0 else 'FAIL'}")
    print(f"   全表日期范围: {con.execute(f'SELECT min(date)::VARCHAR, max(date)::VARCHAR FROM {TABLE}').fetchone()}")
    con.close()

    meta_p = ROOT / "_meta.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    t = meta.setdefault("tables", {}).setdefault(TABLE, {})
    t.update({"rows": n, "symbols": ns, "end_date": a.end,
              "last_refresh_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "notes": f"2026-10-08 近端补齐全市场 {a.start}~{a.end}：+{total:,} 行；表 {n:,} 行/{ns:,} 只"})
    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n⑤ _meta.json 已更新（end_date={a.end}）")
    print(f"   用时 {(time.time()-t0)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
