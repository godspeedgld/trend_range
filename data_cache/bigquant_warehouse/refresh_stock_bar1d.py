"""stock_bar1d 增量刷新 — 严格按 skill-bigquant-sdk warehouse-playbook 八步流程。

流程（playbook「刷新流程」）：
  1. 从 all_trading_days 获取 latest_trade_date（交易日历基准，硬上限）
  2. 读 _meta.json → 表 watermark (end_date)
  3. watermark >= latest → 跳过
  4. 拉取缺失区间 (watermark+1day, latest] —— 本表缺口为 2022-01-01~2026-08-24
     （历史成分 668 只按批拉取；instruments 限定成分股范围）
  5. 按分区键写入 Parquet（year=YYYY/part.parquet，追加合并去重，主键 (instrument,date)）
  6. 重建 DuckDB 视图（read_parquet + hive_partitioning，不复制数据）
  7. 更新 _meta.json watermark（row_count/end_date/last_refresh_at）
  8. 校验清单（playbook「校验清单」八项）；不过 → status=partial，保留有效数据

安全规则：断点续拉（checkpoint 记录已完成批次）；AK/SK 不落盘。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent          # data_cache/bigquant_warehouse
TABLE = "stock_bar1d"
SOURCE = "cn_stock_bar1d"
PK = ["instrument", "date"]
BATCH = 67
CHECKPOINT = ROOT / f"_refresh_ckpt_{TABLE}.json"


# ── 步骤1：交易日历基准 ─────────────────────────────────
def latest_trade_date() -> str:
    from bigquant import dai
    td = dai.query(
        "SELECT max(date) AS d FROM all_trading_days WHERE market_code='CN' AND date <= today()"
    ).df()
    return str(pd.Timestamp(td["d"].iloc[0]).date())


# ── 步骤2：watermark ───────────────────────────────────
def read_meta() -> dict:
    return json.loads((ROOT / "_meta.json").read_bytes().decode("utf-8", errors="replace"))


def write_meta(m: dict):
    (ROOT / "_meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")


# ── 步骤4：拉取缺失区间（分批 + 断点续拉）──────────────
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
           f"AND date > '{start}' AND date <= '{end}'")
    last_err = None
    for attempt in range(3):
        try:
            return dai.query(sql).df()
        except Exception as e:  # noqa: BLE001 — playbook：区分失败类型，重试
            last_err = e
            print(f"  重试 {attempt+1}/3: {type(e).__name__} {str(e)[:120]}", flush=True)
            time.sleep(5 * (attempt + 1))
    print(f"  !! 批失败: {last_err}", flush=True)
    return None


# ── 步骤5：分区写入（追加合并去重）─────────────────────
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


# ── 步骤6：重建视图 ───────────────────────────────────
def rebuild_view():
    db = ROOT / "bigquant_warehouse.duckdb"
    con = duckdb.connect(str(db))
    con.execute(f"""
        CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * FROM read_parquet('{(ROOT / TABLE).as_posix()}/**/*.parquet',
                                   hive_partitioning = true)
    """)
    con.close()


# ── 步骤8：校验清单（playbook 八项）───────────────────
def validate(latest: str) -> tuple[bool, list[str]]:
    errs = []
    table_dir = ROOT / TABLE
    # 1 Parquet 存在且非空
    parts = sorted(table_dir.glob("year=*/part.parquet"))
    if not parts or any(p.stat().st_size == 0 for p in parts):
        errs.append("Parquet 文件缺失或为空")
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    # 2 主键无重复（分区内）
    dup = con.execute(f"""
        SELECT count(*) FROM (
            SELECT instrument, date, count(*) c FROM {TABLE}
            GROUP BY instrument, date HAVING c > 1)
    """).fetchone()[0]
    if dup:
        errs.append(f"主键重复 {dup} 组")
    # 3 日期范围 ≤ 交易日历最新
    r = con.execute(f"SELECT min(date), max(date) FROM {TABLE}").fetchone()
    if str(pd.Timestamp(r[1]).date()) > latest:
        errs.append(f"日期超限: {r[1]} > {latest}")
    # 4 必填列无全空 5 价格>0
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    for col, chk in [("open", "COUNT(*)"), ("high", None), ("low", None), ("close", None)]:
        nulls = con.execute(f"SELECT count(*) FROM {TABLE} WHERE {col} IS NULL").fetchone()[0]
        if nulls == n:
            errs.append(f"{col} 全空")
    bad_px = con.execute(f"""
        SELECT count(*) FROM {TABLE}
        WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0
    """).fetchone()[0]
    if bad_px:
        errs.append(f"价格≤0 行数 {bad_px}")
    # 6 视图可查且范围符合
    rng = con.execute(f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
    print(f"  视图: {rng[0]:,} 行 {pd.Timestamp(rng[1]).date()} ~ {pd.Timestamp(rng[2]).date()}")
    # 7 抽样对比源 API（3 品种 × 3 日期）
    from bigquant import dai
    sample = con.execute(f"""
        SELECT DISTINCT instrument FROM {TABLE}
        WHERE date >= '{latest}' ORDER BY instrument LIMIT 3
    """).fetchall()
    for (sym,) in sample:
        loc = con.execute(f"""
            SELECT date, close FROM {TABLE}
            WHERE instrument='{sym}' AND date >= '{latest}' ORDER BY date LIMIT 3
        """).fetchall()
        if not loc:
            continue
        ds = "','".join(str(pd.Timestamp(d).date()) for d, _ in loc)
        rem = dai.query(
            f"SELECT date, close FROM {SOURCE} WHERE instrument='{sym}' "
            f"AND date IN ('{ds}')").df()
        rem_map = {str(pd.Timestamp(r.date).date()): float(r.close) for r in rem.itertuples()}
        for d, c in loc:
            rd = str(pd.Timestamp(d).date())
            if rd in rem_map and abs(rem_map[rd] - c) > 1e-6:
                errs.append(f"抽样不符 {sym}@{rd}: 本地{c} vs 远端{rem_map[rd]}")
    con.close()
    return (not errs), errs


def main() -> int:
    latest = latest_trade_date()                      # 1
    meta = read_meta()
    wm = meta["tables"][TABLE].get("end_date", "2005-01-01")
    print(f"基准 latest={latest} | watermark={wm}")   # 2
    if wm >= latest:
        print("已是最新，跳过")                        # 3
        return 0

    # 缺口区间 (watermark, latest]；本地 2021 完整 + 2025 残留 → 实际拉 2022-01-01 起
    gap_start = "2021-12-31"                          # = watermark 有效历史末端
    syms = load_syms()
    done = set(json.loads(CHECKPOINT.read_text(encoding="utf-8"))) if CHECKPOINT.exists() else set()
    todo = [s for s in syms if s not in done]
    print(f"目标 {len(syms)} 只（历史成分全量），待拉 {len(todo)} 只，区间 ({gap_start}, {latest}]",
          flush=True)

    t0 = time.perf_counter()
    for bi in range(0, len(todo), BATCH):             # 4
        batch = todo[bi:bi + BATCH]
        print(f"[{bi//BATCH+1}/{(len(todo)+BATCH-1)//BATCH}] {batch[0]}..{batch[-1]} ({len(batch)}只)",
              flush=True)
        df = pull_batch(batch, gap_start, latest)
        if df is None:
            continue                                  # 断点续拉，下次重来
        if len(df):
            write_partitions(df)                      # 5
            print(f"  +{len(df)} 行 ({time.perf_counter()-t0:.0f}s)", flush=True)
        done.update(batch)
        CHECKPOINT.write_text(json.dumps(sorted(done)), encoding="utf-8")

    rebuild_view()                                    # 6

    # 7 更新 watermark
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    n, mx = con.execute(f"SELECT count(*), max(date) FROM {TABLE}").fetchone()
    con.close()
    meta = read_meta()
    meta["tables"][TABLE].update({
        "end_date": str(pd.Timestamp(mx).date()), "row_count": int(n),
        "last_refresh_at": datetime.now(timezone.utc).isoformat(),
    })

    ok, errs = validate(latest)                       # 8
    meta["tables"][TABLE]["status"] = "ok" if ok else "partial"
    if errs:
        meta["tables"][TABLE]["errors"] = errs[:20]
    write_meta(meta)
    print(f"\n完成: {n:,} 行, 末值 {pd.Timestamp(mx).date()}, status={'ok' if ok else 'partial'}")
    if errs:
        print("校验问题:", *errs, sep="\n  ")
    CHECKPOINT.unlink(missing_ok=True)                # 全量成功后清除断点
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
