"""拉取沪深300成分股资金流向（cn_stock_moneyflow）→ 本地仓库（断点续传版）。

范围：668 只沪深300历史成分股（=本地 stock_bar1d 全集），2015-01-05 ~ 2026-08-21
（对齐本地 cn_stock_bar1d 沪深300成分股日线的起止）。

断点续传（2026-09-03 首跑撞周配额后改造）：
  - 跳过已入库的 (instrument) —— 从现有 stock_moneyflow 分区读已覆盖股票集合
  - 逐批拉取 + 立即落盘（每批合并进年度分区），配额耗尽/网络断自动保留进度
  - 进度文件 stock_moneyflow/_progress.json 记录已完成批次；重跑从未完成处继续
  - 全部批次完成后刷新 DuckDB 视图 + 更新 _meta.json

用法（下周配额刷新后直接跑）：
  python fetch_hs300_moneyflow.py            # 续传剩余 ~548 只
  python fetch_hs300_moneyflow.py --retry-failed  # 重试上次失败批次
主键：(instrument, date)。资金流为当日事实数据（无复权问题），历史稳定可增量。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range\data_cache\bigquant_warehouse")
TABLE = "stock_moneyflow"                 # 仓库表名
SOURCE = "cn_stock_moneyflow"             # BigQuant SQL 表名
PANEL = Path(r"C:\Quant\trend_range\replication\research-projects"
             r"/hs300-enh-2017-2021/_market_hs300_panel.parquet")
BATCH = 60                                # 每批 instruments 数（小批省配额、断点细）
START, END = "2015-01-05", "2026-08-21"


def done_symbols() -> set:
    """已入库股票集合（读现有分区文件）。"""
    table_dir = ROOT / TABLE
    if not table_dir.exists():
        return set()
    syms = set()
    for p in table_dir.glob("year=*/part.parquet"):
        syms.update(pd.read_parquet(p, columns=["instrument"])["instrument"].unique())
    return syms


def write_batch(df: pd.DataFrame):
    """单批立即落盘（合并进年度分区，主键去重）。"""
    if df.empty:
        return
    df["year"] = pd.to_datetime(df["date"]).dt.year
    for year, grp in df.groupby("year"):
        part_dir = ROOT / TABLE / f"year={year}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out = part_dir / "part.parquet"
        if out.exists():
            grp = pd.concat([pd.read_parquet(out), grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def main(retry_failed: bool = False) -> int:
    from bigquant import dai
    prog_path = ROOT / TABLE / "_progress.json"
    prog = {"failed": []}
    if prog_path.exists():
        prog = json.loads(prog_path.read_text(encoding="utf-8"))
    failed_last = set(prog.get("failed", []))

    all_syms = sorted(pd.read_parquet(PANEL, columns=["symbol"])["symbol"].unique())
    done = done_symbols()
    todo = [s for s in all_syms if s not in done and (retry_failed or s not in failed_last)]
    print(f"全量 {len(all_syms)} 只 | 已入库 {len(done)} | 本次待拉 {len(todo)} "
          f"| 上次失败跳过 {len(failed_last - set(todo)) if not retry_failed else 0}")

    failed_now = []
    n_done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        in_list = ",".join(f"'{s}'" for s in batch)
        sql = (f"SELECT * FROM {SOURCE} WHERE instrument IN ({in_list}) "
               f"AND date >= '{START}' AND date <= '{END}'")
        try:
            df = dai.query(sql).df()
            write_batch(df)
            n_done += len(df)
            print(f"  [{i // BATCH + 1}/{(len(todo) + BATCH - 1) // BATCH}] "
                  f"{len(batch)} 只 → {len(df)} 行（累计 {n_done}）", flush=True)
        except Exception as e:                            # noqa: BLE001 配额/网络
            msg = str(e)[:160]
            print(f"  [{i // BATCH + 1}] 失败: {msg}", flush=True)
            failed_now.extend(batch)
            if "配额" in msg or "quota" in msg.lower():
                print("  ⚠ 周配额耗尽，进度已保存，下周重跑续传")
                break
    # 落进度
    prog["failed"] = failed_now
    prog_path.parent.mkdir(parents=True, exist_ok=True)
    prog_path.write_text(json.dumps(prog, ensure_ascii=False, indent=2), encoding="utf-8")

    refresh_view()
    return 0


def refresh_view():
    db = ROOT / "bigquant_warehouse.duckdb"
    table_dir = (ROOT / TABLE)
    if not any(table_dir.glob("year=*/part.parquet")):
        print("无分区数据，跳过视图刷新")
        return
    table_posix = table_dir.resolve().as_posix()
    con = duckdb.connect(str(db))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{table_posix}/**/*.parquet', hive_partitioning=true)
    """)
    n = con.execute(f"SELECT count(*), count(distinct instrument), "
                    f"min(date), max(date) FROM {TABLE}").fetchone()
    con.close()
    print(f"视图 {TABLE}: {n[0]:,} 行 / {n[1]} 只 / {n[2]} ~ {n[3]}")
    # _meta 登记
    mp = ROOT / "_meta.json"
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta.setdefault("tables", {})[TABLE] = {
        "source": SOURCE,
        "primary_key": ["instrument", "date"],
        "start_date": str(pd.Timestamp(n[2]).date()),
        "end_date": str(pd.Timestamp(n[3]).date()),
        "rows": int(n[0]),
        "instruments": int(n[1]),
        "note": "沪深300历史成分股668只资金流向（档位×主被动×买卖，32数据列）；"
                "断点续传中，目标 668 只",
    }
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"_meta.json 已更新 {TABLE}")


if __name__ == "__main__":
    retry = "--retry-failed" in sys.argv
    raise SystemExit(main(retry_failed=retry))
