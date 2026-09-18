"""stock_valuation 增量刷新 — cn_stock_valuation（估值表）沪深300历史成分 2015 至今入库。

严格按 skill-bigquant-sdk warehouse-playbook 八步流程 + 硬性规定：
  1. all_trading_days 取 latest_trade_date（硬上限）
  2. 读 _meta.json watermark（新表无 → 初始化）
  3. watermark >= latest → 跳过
  4. 拉缺失区间（668 只历史成分分批；断点续拉）
  5. year 分区写 Parquet，主键 (instrument,date) 合并去重
  6. 重建视图 —— 硬性规定：绝对路径 + 正斜杠（as_posix），创建后双目录验证
  7. 更新 _meta.json —— 硬性规定：UTF-8 写入；watermark == 实际 max(date) 同步
  8. 校验清单（playbook 十一项）
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent
TABLE = "stock_valuation"            # 本地仓库名
SOURCE = "cn_stock_valuation"        # BigQuant SQL 表名
PK = ["instrument", "date"]
START = "2015-01-01"                 # 首次全量起点
BATCH = 67
CHECKPOINT = ROOT / f"_refresh_ckpt_{TABLE}.json"


def latest_trade_date() -> str:
    from bigquant import dai
    td = dai.query(
        "SELECT max(date) AS d FROM all_trading_days WHERE market_code='CN' AND date <= today()"
    ).df()
    return str(pd.Timestamp(td["d"].iloc[0]).date())


def read_meta() -> dict:
    return json.loads((ROOT / "_meta.json").read_text(encoding="utf-8"))


def write_meta(m: dict):
    (ROOT / "_meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")


def load_syms() -> list[str]:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    syms = [r[0] for r in con.execute(
        "SELECT DISTINCT member_code FROM index_component WHERE instrument='000300.SH' ORDER BY 1"
    ).fetchall()]
    con.close()
    return syms


def pull_batch(syms: list[str], start: str, end: str) -> pd.DataFrame | None:
    from bigquant import dai
    in_list = ",".join(f"'{s}'" for s in syms)
    sql = (f"SELECT * FROM {SOURCE} WHERE instrument IN ({in_list}) "
           f"AND date >= '{start}' AND date <= '{end}'")
    last_err = None
    for attempt in range(3):
        try:
            return dai.query(sql).df()
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  重试 {attempt+1}/3: {type(e).__name__} {str(e)[:120]}", flush=True)
            time.sleep(5 * (attempt + 1))
    print(f"  !! 批失败: {last_err}", flush=True)
    return None


def write_partitions(df: pd.DataFrame):
    df["year"] = pd.to_datetime(df["date"]).dt.year
    table_dir = ROOT / TABLE
    for year, grp in df.groupby("year"):
        part_dir = table_dir / f"year={year}"
        part_dir.mkdir(parents=True, exist_ok=True)
        out = part_dir / "part.parquet"
        if out.exists():
            existing = pd.read_parquet(out)
            grp = pd.concat([existing, grp], ignore_index=True)
            grp = grp.drop_duplicates(subset=PK, keep="last")
        grp.to_parquet(out, index=False)


def rebuild_view():
    # 硬性规定：绝对路径 + 正斜杠
    pattern = (ROOT / TABLE).resolve().as_posix() + "/**/*.parquet"
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)
    """)
    con.close()


def validate(latest: str) -> tuple[bool, list[str]]:
    errs = []
    parts = sorted((ROOT / TABLE).glob("year=*/part.parquet"))
    if not parts or any(p.stat().st_size == 0 for p in parts):
        errs.append("Parquet 缺失或为空")
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    dup = con.execute(f"""
        SELECT count(*) FROM (SELECT instrument, date, count(*) c FROM {TABLE}
                              GROUP BY 1,2 HAVING c > 1)
    """).fetchone()[0]
    if dup:
        errs.append(f"主键重复 {dup} 组")
    n, lo, hi = con.execute(f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
    if str(pd.Timestamp(hi).date()) > latest:
        errs.append(f"日期超限 {hi} > {latest}")
    if n and str(pd.Timestamp(lo).date()) < "2015-01-01":
        errs.append(f"起始早于预期: {lo}")
    # 必填列无全空（估值核心列）
    for col in ["total_market_cap", "pe_ttm", "pb"]:
        nulls = con.execute(f"SELECT count(*) FROM {TABLE} WHERE {col} IS NULL").fetchone()[0]
        if nulls == n:
            errs.append(f"{col} 全空")
    # 抽样 3 品种 × 3 日期对比源
    from bigquant import dai
    sample = con.execute(f"""
        SELECT DISTINCT instrument FROM {TABLE}
        WHERE date >= '{latest}' ORDER BY instrument LIMIT 3
    """).fetchall()
    for (sym,) in sample:
        loc = con.execute(f"""
            SELECT date, total_market_cap FROM {TABLE}
            WHERE instrument='{sym}' AND date >= '{latest}' ORDER BY date LIMIT 3
        """).fetchall()
        if not loc:
            continue
        ds = "','".join(str(pd.Timestamp(d).date()) for d, _ in loc)
        rem = dai.query(f"SELECT date, total_market_cap FROM {SOURCE} "
                        f"WHERE instrument='{sym}' AND date IN ('{ds}')").df()
        rem_map = {str(pd.Timestamp(r.date).date()): float(r.total_market_cap)
                   for r in rem.itertuples()}
        for d, v in loc:
            rd = str(pd.Timestamp(d).date())
            if rd in rem_map and abs(rem_map[rd] - v) > 1e-3:
                errs.append(f"抽样不符 {sym}@{rd}: 本地{v} vs 远端{rem_map[rd]}")
    con.close()
    return (not errs), errs


def main() -> int:
    latest = latest_trade_date()                                   # 1
    meta = read_meta()
    entry = meta["tables"].get(TABLE, {
        "source_table": SOURCE, "partition_keys": ["year"], "primary_keys": PK,
        "date_column": "date", "status": "initialized",
        "note": "沪深300历史成分（index_component 全量 member_code）",
    })
    wm = entry.get("end_date", "")
    print(f"基准 latest={latest} | watermark={wm or '(新表)'}")
    if wm and wm >= latest:                                        # 3
        print("已是最新，跳过")
        return 0

    start = START if not wm else wm                               # 新表全量 / 旧表增量
    syms = load_syms()
    done = set(json.loads(CHECKPOINT.read_text(encoding="utf-8"))) if CHECKPOINT.exists() else set()
    todo = [s for s in syms if s not in done]
    print(f"目标 {len(syms)} 只，待拉 {len(todo)} 只，区间 [{start}, {latest}]", flush=True)

    t0 = time.perf_counter()
    for bi in range(0, len(todo), BATCH):                          # 4
        batch = todo[bi:bi + BATCH]
        print(f"[{bi//BATCH+1}/{(len(todo)+BATCH-1)//BATCH}] {batch[0]}..{batch[-1]} ({len(batch)}只)",
              flush=True)
        df = pull_batch(batch, start, latest)
        if df is None:
            continue
        if len(df):
            write_partitions(df)                                   # 5
            print(f"  +{len(df)} 行 ({time.perf_counter()-t0:.0f}s)", flush=True)
        done.update(batch)
        CHECKPOINT.write_text(json.dumps(sorted(done)), encoding="utf-8")

    rebuild_view()                                                 # 6

    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    n, lo, hi = con.execute(f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
    con.close()
    entry.update({
        "start_date": str(pd.Timestamp(lo).date()), "end_date": str(pd.Timestamp(hi).date()),
        "row_count": int(n), "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    })

    ok, errs = validate(latest)                                    # 8
    entry["status"] = "ok" if ok else "partial"
    if errs:
        entry["errors"] = errs[:20]
    meta = read_meta()
    meta["tables"][TABLE] = entry
    write_meta(meta)                                               # 7（UTF-8 + watermark 同步）
    print(f"\n完成: {n:,} 行 {pd.Timestamp(lo).date()}~{pd.Timestamp(hi).date()} "
          f"status={'ok' if ok else 'partial'}")
    if errs:
        print("校验问题:", *errs, sep="\n  ")
    CHECKPOINT.unlink(missing_ok=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
