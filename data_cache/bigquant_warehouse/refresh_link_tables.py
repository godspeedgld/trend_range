"""链路表刷新 + valuation 补全（2026-10-12，用户指令：三表刷到 09-30、valuation 拉剩余）。

列严格按 .claude/skills/skill-bigquant-sdk/references/data_tables.md：
  cn_stock_industry_bar1d      13 列（本地历史只入 method=1，保持一致）
  cn_stock_industry_component  11 列（月末快照口径，与本地历史一致）
  cn_stock_index_component      5 列（逐日）
  cn_stock_valuation           14 列（= 本地既有 schema；data_tables 14 数据列中的 12，
                               pcf_op_ttm/pcf_op_leading 历史批次未入，为免同表撕裂沿用）

valuation 配额守卫：剩 34.5M，缺口 52M → 中证2000并集(2,916只)优先，批 100 只，
累计 cells 超 --budget(默认 30M) 即停，断点 _valuation_gap_ckpt.json 下周续。

用法：
  python refresh_link_tables.py link      # 三张小表 → 2026-09-30（~0.3M）
  python refresh_link_tables.py valuation [--budget 30000000]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
from bigquant import dai  # noqa: E402

ROOT = Path(__file__).resolve().parent
DB = ROOT / "bigquant_warehouse.duckdb"
CKPT = ROOT / "_valuation_gap_ckpt.json"
UNTIL = "2026-09-30"

IND_IDX = ["000300.SH", "000905.SH", "000852.SH", "932000.CSI", "399001.SZ", "399006.SZ", "000688.SH"]


def ingest(df: pd.DataFrame, table: str, pk: list[str]):
    """按年分区合并去重写入（仓库既有模式）。"""
    if df.empty:
        return 0
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    tdir = ROOT / table
    for y, g in df.groupby("year"):
        out = tdir / f"year={int(y)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            old = pd.read_parquet(out)
            g = pd.concat([old, g.astype(old.dtypes.to_dict(), errors="ignore")],
                          ignore_index=True)
        g = g.drop_duplicates(subset=pk, keep="last")
        g.to_parquet(out, index=False)
    return len(df)


def rebuild_view(table: str):
    con = duckdb.connect(str(DB))
    tdir = (ROOT / table).resolve().as_posix()
    con.execute(f"CREATE OR REPLACE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{tdir}/**/*.parquet', hive_partitioning=true)")
    con.close()


def month_ends(a: str, b: str) -> list[str]:
    d = pd.date_range(a, b, freq="ME")
    return [x.strftime("%Y-%m-%d") for x in d]


def part_link():
    t0 = time.time()
    con = duckdb.connect(str(DB), read_only=True)

    # ── ① stock_industry_bar1d：09-12 ~ 09-30，method=1（13 列）──
    lo1 = str(con.execute("SELECT max(date)+INTERVAL 1 DAY FROM stock_industry_bar1d").fetchone()[0])[:10]
    COLS1 = ["instrument", "method", "pre_close", "open", "close", "high", "low", "volume",
             "deal_number", "amount", "change_ratio", "turn", "date"]
    df = dai.query(f"""SELECT {', '.join(COLS1)} FROM cn_stock_industry_bar1d
        WHERE method=1 AND date >= '{lo1}' AND date <= '{UNTIL}'""").df()
    n1 = ingest(df, "stock_industry_bar1d", ["instrument", "date", "method"])
    print(f"① industry_bar1d  {lo1}~{UNTIL}: +{n1:,} 行")

    # ── ② stock_industry_component：月末快照 08-31/09-30（11 列，sw2021）──
    lo2 = str(con.execute("SELECT max(date) FROM stock_industry_component").fetchone()[0])[:10]
    me = [d for d in month_ends(lo2, UNTIL) if d > lo2]
    COLS2 = ["instrument", "industry", "industry_name", "industry_instrument",
             "industry_level1_code", "industry_level1_name", "industry_level2_code",
             "industry_level2_name", "industry_level3_code", "industry_level3_name", "date"]
    if me:
        din = ",".join(f"TIMESTAMP '{d}'" for d in me)
        df = dai.query(f"""SELECT {', '.join(COLS2)} FROM cn_stock_industry_component
            WHERE industry='sw2021' AND date IN ({din})""").df()
        n2 = ingest(df, "stock_industry_component", ["instrument", "date"])
        print(f"② industry_component  月末 {me}: +{n2:,} 行")
    else:
        print("② industry_component 已是最新月末")

    # ── ③ index_component：逐日 08-20 ~ 09-30（5 列，7 指数）──
    lo3 = str(con.execute("SELECT max(date)+INTERVAL 1 DAY FROM index_component").fetchone()[0])[:10]
    inl = ",".join(f"'{i}'" for i in IND_IDX)
    df = dai.query(f"""SELECT instrument, name, member_code, member_name, date
        FROM cn_stock_index_component
        WHERE instrument IN ({inl}) AND date >= '{lo3}' AND date <= '{UNTIL}'""").df()
    n3 = ingest(df, "index_component", ["instrument", "member_code", "date"])
    print(f"③ index_component  {lo3}~{UNTIL}: +{n3:,} 行")
    con.close()

    for t in ("stock_industry_bar1d", "stock_industry_component", "index_component"):
        rebuild_view(t)
    print(f"三表视图已重建 · 用时 {time.time()-t0:.0f}s")


def part_valuation(budget: int):
    """补 valuation 键级缺口：中证2000并集优先 → 其余；批 100 只；超预算即停（断点续）。"""
    COLS = ["date", "instrument", "total_market_cap", "float_market_cap", "dividend_yield_ratio",
            "pe_ttm", "pe_leading", "pe_trailing", "pb", "ps_ttm", "ps_leading", "ps_trailing",
            "pcf_net_ttm", "pcf_net_leading", "pcf_op_ttm", "pcf_op_leading"]  # data_tables.md 全 14 数据列
    con = duckdb.connect(str(DB), read_only=True)
    miss = [r[0] for r in con.execute("""
        SELECT DISTINCT b.instrument FROM stock_bar1d b
        ANTI JOIN stock_valuation v ON v.instrument=b.instrument AND v.date=b.date
        ORDER BY 1""").fetchall()]
    # 需要的行数（每只的缺口行数，用来精确计 cells）
    rows_need = dict(con.execute("""
        SELECT b.instrument, count(*) FROM stock_bar1d b
        ANTI JOIN stock_valuation v ON v.instrument=b.instrument AND v.date=b.date
        GROUP BY 1""").fetchall())
    con.close()
    csi2k = {r[0] for r in duckdb.connect(str(DB), read_only=True).execute(
        "SELECT DISTINCT member_code FROM index_component WHERE instrument='932000.CSI'").fetchall()}
    order = [s for s in miss if s in csi2k] + [s for s in miss if s not in csi2k]

    done = set(json.loads(CKPT.read_text())) if CKPT.exists() else set()
    todo = [s for s in order if s not in done]
    print(f"缺口 {len(miss):,} 只（中证2000 {sum(1 for s in miss if s in csi2k):,}）"
          f" | 断点已完成 {len(done)} | 本轮待拉 {len(todo)} | 预算 {budget/1e6:.0f}M cells")

    spent, rows_in = 0, 0
    t0 = time.time()
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        est = sum(rows_need.get(s, 0) for s in batch) * len(COLS)
        if spent + est > budget:
            print(f"  预算守卫触发（已花 {spent/1e6:.1f}M + 本批 {est/1e6:.1f}M > {budget/1e6:.0f}M）→ 停，断点已存")
            break
        inl = ",".join(f"'{s}'" for s in batch)
        # ★ 分区裁剪要求 SQL 同时含 instrument 过滤 + date 范围（pull_csi1000_valuation.py
        #   历史验证的姿势；单独 instrument IN 或 filters 参数都过不了）
        try:
            df = dai.query(f"""SELECT {', '.join(COLS)} FROM cn_stock_valuation
                WHERE instrument IN ({inl}) AND date >= '2015-01-01' AND date <= '{UNTIL}'""").df()
        except Exception as ex:
            print(f"  查询失败（多为配额尽）: {str(ex)[:120]}")
            print(f"  → 停止，断点已存（下周同命令续传）")
            break
        if len(df):
            ingest(df, "stock_valuation", ["instrument", "date"])
            rows_in += len(df)
        # ★ 2026-10-12 教训：est（bar1d 键级缺口）比云端实际返回低 ~4×（云端含 bar1d 没有的日期行）
        #   → 计费一律按【实际返回行 × 列数】事后累计，est 只做粗筛
        spent += len(df) * len(COLS)
        done.update(batch)
        CKPT.write_text(json.dumps(sorted(done)))
        print(f"  批 {i//100+1}: {len(batch)} 只 → {len(df):,} 行 | 累计 {rows_in:,} 行 / {spent/1e6:.1f}M cells / {time.time()-t0:.0f}s", flush=True)
    rebuild_view("stock_valuation")
    con = duckdb.connect(str(DB), read_only=True)
    n, s, e = con.execute("SELECT count(*), count(DISTINCT instrument), max(date) FROM stock_valuation").fetchone()
    con.close()
    print(f"valuation 现 {n:,} 行 / {s:,} 只 / 至 {str(e)[:10]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["link", "valuation"])
    ap.add_argument("--budget", type=int, default=30_000_000)
    a = ap.parse_args()
    (part_link if a.cmd == "link" else lambda: part_valuation(a.budget))()
