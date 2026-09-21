"""拉取中证1000 历史并集成分股日线（cn_stock_bar1d，2015-01-01 至今）→ 入库 stock_bar1d

- 成分股：本地 index_component WHERE instrument='000852.SH' 历史并集（2800 只），
  **跳过已入库的 903 只**（HS300∪CSI500 已有），净新增约 1897 只
- 列：与现有 stock_bar1d 完全一致（16 数据列 + year 分区）——显式 SELECT，不 SELECT *
- 严格按 skill-bigquant-sdk warehouse-playbook：年分区 part.parquet 追加合并去重
  （主键 instrument+date）→ 重建视图 → 更新 _meta.json → 校验
- 分批（BATCH 只/批）+ 断点续拉（checkpoint 文件），配额断掉时重跑即续
- 安全：2026-03-06 起本地日期不超过 all_trading_days 最新（本脚本拉到 '2026-08-24' 硬上限，
  与现有表 watermark 对齐）
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent          # data_cache/bigquant_warehouse
TABLE = "stock_bar1d"
SOURCE = "cn_stock_bar1d"
BATCH = 100
CKPT = ROOT / "_pull_csi1000_ckpt.json"
START, END = "2015-01-01", "2026-08-24"

# ★ 与现有 stock_bar1d 落盘列完全一致（用户指定"跟之前沪深300中证500相同"）；
#   旧批当时是 SELECT * 落盘的 17 列，这里显式列出数据列（year 为分区键落盘时生成）
COLS = ["date", "instrument", "name", "adjust_factor", "pre_close", "open", "close", "high",
        "low", "volume", "deal_number", "amount", "change_ratio", "turn", "upper_limit", "lower_limit"]


def load_todo() -> list[str]:
    """中证1000 并集 − 已入库 = 待拉清单"""
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    rows = con.execute("""
        SELECT DISTINCT member_code FROM index_component ic
        WHERE instrument='000852.SH'
          AND NOT EXISTS (SELECT 1 FROM stock_bar1d s WHERE s.instrument = ic.member_code)
        ORDER BY 1""").fetchall()
    con.close()
    return [r[0] for r in rows]


def pull_batch(syms: list[str]) -> pd.DataFrame | None:
    from bigquant import dai
    in_list = ",".join(f"'{s}'" for s in syms)
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE instrument IN ({in_list}) AND date >= '{START}' AND date <= '{END}'")
    for attempt in range(3):
        try:
            return dai.query(sql).df()[COLS]
        except Exception as e:
            print(f"    重试 {attempt+1}/3: {str(e)[:100]}")
            time.sleep(5)
    return None


def write_partitions(df: pd.DataFrame):
    """年分区追加 + 主键去重（与既有分区文件合并）"""
    df = df.copy()
    df["year"] = pd.to_datetime(df["date"]).dt.year
    table_dir = ROOT / TABLE
    for year, grp in df.groupby("year"):
        out = table_dir / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            old = pd.read_parquet(out)
            grp = pd.concat([old, grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def rebuild_view():
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet',
                                   hive_partitioning=true)""")
    n_syms, n_rows, d0, d1 = con.execute(
        f"SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM {TABLE}").fetchone()
    con.close()
    return n_syms, n_rows, str(d0)[:10], str(d1)[:10]


def update_meta(n_added_rows: int):
    m = json.loads((ROOT / "_meta.json").read_text(encoding="utf-8"))
    t = m["tables"][TABLE]
    t["row_count"] = t.get("row_count", 0) + n_added_rows
    t["last_refresh_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    t["note"] = (t.get("note", "") +
                 f"；2026-09-21 增中证1000并集缺口（约1897只，2015起，+{n_added_rows:,}行）").lstrip("；")
    (ROOT / "_meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")


def main():
    todo = load_todo()
    done = json.loads(CKPT.read_text()) if CKPT.exists() else []
    done_set, todo = set(done), [s for s in todo if s not in set(done)]
    print(f"中证1000 并集待拉: {len(todo)} 只（已完成 {len(done_set)}）· {START}~{END} · 批大小 {BATCH}")
    total_rows = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        t0 = time.time()
        df = pull_batch(batch)
        if df is None:
            print(f"  批 {i//BATCH+1} 三次失败，断点已存（{len(done_set)} 只），配额恢复后重跑本脚本续传")
            break
        if len(df):
            write_partitions(df)
            total_rows += len(df)
        done.extend(batch); done_set.update(batch)
        CKPT.write_text(json.dumps(done, ensure_ascii=False))
        print(f"  批 {i//BATCH+1:>2}: {len(batch)} 只 → {len(df):>7,} 行  累计 {total_rows:>9,}  "
              f"({time.time()-t0:.0f}s)")
    n_syms, n_rows, d0, d1 = rebuild_view()
    update_meta(total_rows)
    print(f"\n完成：stock_bar1d 现有 {n_syms} 只 / {n_rows:,} 行 / {d0}~{d1}（本次 +{total_rows:,} 行）")
    # 校验：主键重复（playbook 八项之核心项）
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    dup = con.execute(f"SELECT count(*) FROM (SELECT instrument, date, count(*) c "
                      f"FROM {TABLE} GROUP BY 1,2 HAVING c > 1)").fetchone()[0]
    con.close()
    print(f"校验：主键重复 {dup} {'OK' if dup == 0 else 'FAIL'}")


if __name__ == "__main__":
    main()
