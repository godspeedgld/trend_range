"""拉取**中证500 成分股**的 个股日线 + 估值 → 本地仓库（断点续传版）。

范围：中证500（000905.SH）历史成分股中**本地尚未覆盖**的股票，2015-01-05 ~ 2026-08-21
（对齐现有 stock_bar1d 沪深300 面板的起止）。

为什么要拉：本地 stock_bar1d/stock_valuation 是按**沪深300 的 668 只**拉的并集面板，
而中证500 与沪深300 当期不重叠（中证500 定义上剔除沪深300），故只有 446 只迁移过的股票有数据
（成分股-日覆盖率仅 35.2%）。

口径：**并集面板**（每只股票 × 全历史），与现有 668 只一致——
不用"仅成分日"是因为策略需要 MA200/ATR 等滚动指标的**预热历史**，只拉成分窗口会丢失。

列：**严格按 references/data_tables.md**（cn_stock_bar1d 16 列 / cn_stock_valuation 16 列），
已校验与本地表列完全一致，不多拉一列。禁 SELECT *。

配额：910 只 × ~2826 日 × 16 列 ≈ 3,700 万单元格/表（≈37%），两表合计 ≈74%。
周配额 1 亿。**两阶段执行**（先日线后估值），配额不足时断点续传，重跑自动跳过已完成股票。

用法：
  python fetch_csi500_stock.py             # 续传（自动跳过已入库股票）
  python fetch_csi500_stock.py --bar-only  # 只拉日线阶段
  python fetch_csi500_stock.py --val-only  # 只拉估值阶段
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range\data_cache\bigquant_warehouse")
INDEX = "000905.SH"                        # 中证500
START, END = "2015-01-05", "2026-08-21"    # 对齐现有 stock_bar1d
BATCH = 60

# ── 严格按 references/data_tables.md；已与本地表列逐字校验一致 ──
COLS_BAR = ["instrument", "date", "name", "open", "high", "low", "close", "pre_close",
            "volume", "amount", "turn", "deal_number", "change_ratio", "adjust_factor",
            "upper_limit", "lower_limit"]
COLS_VAL = ["instrument", "date", "total_market_cap", "float_market_cap", "dividend_yield_ratio",
            "pe_ttm", "pe_leading", "pe_trailing", "pb", "ps_ttm", "ps_leading", "ps_trailing",
            "pcf_net_ttm", "pcf_net_leading", "pcf_op_ttm", "pcf_op_leading"]
PHASES = [("stock_bar1d", "cn_stock_bar1d", COLS_BAR),
          ("stock_valuation", "cn_stock_valuation", COLS_VAL)]


def csi500_members() -> list[str]:
    """中证500 历史成分股全集（本地 index_component，无需联网）。"""
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    df = con.execute(f"SELECT DISTINCT member_code FROM index_component "
                     f"WHERE instrument='{INDEX}'").df()
    con.close()
    return sorted(df["member_code"])


def done_symbols(table: str) -> set:
    syms = set()
    for p in (ROOT / table).glob("year=*/part.parquet"):
        syms.update(pd.read_parquet(p, columns=["instrument"])["instrument"].unique())
    return syms


def write_batch(df: pd.DataFrame, table: str):
    """单批立即落盘（合并进年度分区，主键去重）。"""
    if df.empty:
        return
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, grp in df.groupby("year"):
        part_dir = ROOT / table / f"year={year}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out = part_dir / "part.parquet"
        if out.exists():
            grp = pd.concat([pd.read_parquet(out), grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def refresh_view(table: str, note: str):
    db = ROOT / "bigquant_warehouse.duckdb"
    tdir = (ROOT / table).resolve().as_posix()
    con = duckdb.connect(str(db))
    con.execute(f"""CREATE OR REPLACE VIEW {table} AS
        SELECT * FROM read_parquet('{tdir}/**/*.parquet', hive_partitioning=true)""")
    n = con.execute(f"SELECT count(*), count(DISTINCT instrument), min(date), max(date) "
                    f"FROM {table}").fetchone()
    con.close()
    print(f"  视图 {table}: {n[0]:,} 行 / {n[1]} 只 / {n[2]} ~ {n[3]}")
    mp = ROOT / "_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.setdefault("tables", {})[table] = {
        "source": note.split("|")[0], "primary_key": ["instrument", "date"],
        "start_date": str(pd.Timestamp(n[2]).date()), "end_date": str(pd.Timestamp(n[3]).date()),
        "rows": int(n[0]), "instruments": int(n[1]), "note": note.split("|")[1],
    }
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main(bar_only=False, val_only=False) -> int:
    from bigquant import dai
    members = csi500_members()
    print(f"中证500 历史成分股 {len(members)} 只")

    phases = PHASES
    if bar_only:
        phases = PHASES[:1]
    if val_only:
        phases = PHASES[1:]

    for table, source, cols in phases:
        print(f"\n===== 阶段 {table}（{source}，{len(cols)} 列）=====")
        done = done_symbols(table)
        todo = [s for s in members if s not in done]
        print(f"  全量 {len(members)} | 已有 {len(done)} | 本次待拉 {len(todo)}")
        if not todo:
            refresh_view(table, f"{source}|中证500成分股补拉完成")
            continue
        cols_sql = ", ".join(cols)
        n_done, quota_hit, failed = 0, False, []
        for i in range(0, len(todo), BATCH):
            batch = todo[i:i + BATCH]
            in_list = ",".join(f"'{s}'" for s in batch)
            sql = (f"SELECT {cols_sql} FROM {source} WHERE instrument IN ({in_list}) "
                   f"AND date >= '{START}' AND date <= '{END}'")
            try:
                df = dai.query(sql).df()[cols]          # 双保险：显式列 + 落盘前裁剪
                write_batch(df, table)
                n_done += len(df)
                print(f"  [{i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH}] "
                      f"{len(batch)} 只 -> {len(df):,} 行（累计 {n_done:,}）", flush=True)
            except Exception as e:                      # noqa: BLE001 配额/网络
                msg = str(e)[:160]
                print(f"  [{i // BATCH + 1}] 失败: {msg}", flush=True)
                failed.extend(batch)
                if "配额" in msg or "quota" in msg.lower():
                    quota_hit = True
                    break
        print(f"  [阶段小结] 新增 {n_done:,} 行 | 失败 {len(failed)} 只 | "
              f"配额{'耗尽' if quota_hit else '正常'}")
        refresh_view(table, f"{source}|中证500成分股补拉（910 只并集面板，2015-2026）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(bar_only="--bar-only" in sys.argv,
                          val_only="--val-only" in sys.argv))
