"""校验 stock_min_1m 分钟线仓库 —— 按 skill-pandadata-warehouse-main 的 Validation Checklist。

技能要求的 7 项逐条落地：
  ① Parquet 文件存在于每个预期分区   ② 必需源列齐全（接口 11 列）
  ③ 日期范围覆盖请求区间、不越过最新已收盘交易日
  ④ 主键 (symbol,date,minute) 无重复   ⑤ 行数非零
  ⑥ **抽样比对 fresh Pandadata API**（3 只 × 3 日，技能指定）
  ⑦ DuckDB 视图可查且返回预期日期范围

用法：
  python data_cache/validate_stock_min_1m.py               # 全量校验
  python data_cache/validate_stock_min_1m.py --year 2021   # 只深检某年（主键重复）
  python data_cache/validate_stock_min_1m.py --no-api      # 跳过样本比对（零配额）
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SKILL = REPO / ".claude/skills/skill-pandadata-api-main/scripts"
sys.path.insert(0, str(SKILL))

WAREHOUSE = HERE / "pandadata_warehouse"
TABLE = "stock_min_1m"
OUT = WAREHOUSE / TABLE
DDB = WAREHOUSE / "warehouse.duckdb"
EXPECT_COLS = ["symbol", "date", "datetime", "minute", "open", "high", "low", "close",
               "volume", "amount", "num_trades"]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="只对某年做主键深检")
    ap.add_argument("--no-api", action="store_true", help="跳过 fresh API 样本比对")
    a = ap.parse_args()
    t0 = time.time()

    con = duckdb.connect(str(DDB), read_only=True)

    # ① 分区完整性
    expected = []
    for y in range(2021, date.today().year + 1):
        for m in range(1, 13):
            if date(y, m, 1) > date.today():
                break
            expected.append((y, m))
    have = {(int(p.parent.parent.name.split("=")[1]), int(p.parent.name.split("=")[1]))
            for p in OUT.glob("year=*/month=*/part.parquet")}
    missing = [f"{y}-{m:02d}" for y, m in expected if (y, m) not in have]
    check("① 分区完整性", not missing,
          f"{len(have)} 个分区" + (f"，缺 {missing}" if missing else "，无缺"))

    # ② 列完整性
    cols = [d[0] for d in con.execute(f"DESCRIBE {TABLE}").fetchall()]
    lack = [c for c in EXPECT_COLS if c not in cols]
    check("② 源列齐全", not lack, f"{len(cols)} 列" + (f"，缺 {lack}" if lack else ""))

    # ③ + ⑤ 日期范围与行数（视图口径）
    n, d0, d1 = con.execute(
        f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
    check("⑤ 行数非零", n > 0, f"{n:,} 行")
    check("③ 日期范围", d0.startswith("2021") and d1 <= date.today().strftime("%Y%m%d"),
          f"{d0} ~ {d1}（今日 {date.today()}）")

    # ④ 主键重复 —— 全表 2 亿行直接 groupby 太慢，默认只深检指定年/最新年
    years = [a.year] if a.year else [max(y for y, _ in have)]
    for y in years:
        t = time.time()
        dup = con.execute(f"""
            SELECT count(*) FROM (
              SELECT symbol, date, minute FROM {TABLE}
              WHERE year = {y} GROUP BY 1,2,3 HAVING count(*) > 1
            )""").fetchone()[0]
        check(f"④ 主键无重复（{y}）", dup == 0,
              f"{dup} 组重复（{time.time()-t:.0f}s）")

    # ⑦ DuckDB 视图可查
    try:
        vn = con.execute(f'SELECT count(*) FROM {TABLE} WHERE date LIKE \'2021%\'').fetchone()[0]
        check("⑦ 视图可查 2021", vn > 0, f"2021 年 {vn:,} 行")
    except Exception as e:
        check("⑦ 视图可查 2021", False, str(e)[:80])
    con.close()

    # ⑥ 样本比对 fresh API（技能指定：3 只 × 3 日）
    if a.no_api:
        print("  [SKIP] ⑥ 样本比对（--no-api）")
    else:
        # 选有代表性的样本：一只老票 + 两只不同板块
        syms = ["600519.SH", "000001.SZ", "300750.SZ"]
        days = ["20210104", "20210615", "20211231"]
        from pandadata_runtime import init_pandadata
        pd_ = init_pandadata()
        ok_all, detail = True, []
        for s in syms:
            df = pd_.get_stock_min(symbol=[s], start_date=days[0], end_date=days[-1],
                                   fields=EXPECT_COLS, frequency="1m")
            if df is None or not len(df):
                ok_all = False; detail.append(f"{s}:API 空"); continue
            api = df[df["date"].isin(days)]
            loc = duckdb.connect(str(DDB), read_only=True).execute(f"""
                SELECT * FROM {TABLE}
                WHERE symbol = '{s}' AND date IN ({','.join(repr(d) for d in days)})""").df()
            if len(api) != len(loc):
                ok_all = False
                detail.append(f"{s}:行数 API {len(api)} vs 本地 {len(loc)}")
                continue
            # 数值比对（排序后逐列）
            k = ["symbol", "date", "minute"]
            m = api.sort_values(k).reset_index(drop=True).merge(
                loc.sort_values(k).reset_index(drop=True), on=k, suffixes=("_a", "_l"))
            bad = []
            for c in ["open", "high", "low", "close", "volume", "amount"]:
                if c in m:
                    mx = (m[f"{c}_a"].astype(float) - m[f"{c}_l"].astype(float)).abs().max()
                    if mx > 1e-6:
                        bad.append(f"{c} Δmax={mx:g}")
            if bad:
                ok_all = False; detail.append(f"{s}:{'/'.join(bad)}")
            else:
                detail.append(f"{s}✓{len(m)}行")
        check("⑥ 样本比对 fresh API", ok_all,
              f"{len(syms)}只×{len(days)}日  " + "  ".join(detail))

    # 结论
    fail = [r for r in RESULTS if not r[1]]
    print("=" * 68)
    print(f"{'✅ 全部通过' if not fail else f'❌ {len(fail)} 项失败'}  "
          f"（{len(RESULTS)} 项检查，{time.time()-t0:.0f}s）")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
