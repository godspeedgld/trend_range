"""拉取 cn_stock_prefactors 的【状态+行业】属性列 → 本地 stock_prefactors_attr 表。

为什么只拉这 13 列（方案 B，2026-09-29 用户确认）：
  行情字段（close/amount/turn/...）已验证与本地 stock_bar1d **逐值一致**
  （2026-09-28 抽验 65/65），不必重拉；只补本地缺的：
    状态类 8 列：list_sector / list_date / list_days(自然日!) / st_status /
                 is_risk_warning / suspended / price_limit_status / line_price_limit
    行业类 4 列：sw_level_index_code(801xxx.SWI) / sw_level1_name / sw2021_level2
    键     2 列：date / instrument
  全字段 74 列要 ≈9 周；本方案 13 列 ≈1.54 亿 cells，**2 周拉完**。

落地结构（仓库既有模式 = Parquet + 视图，见 rebuild_warehouse_views.py）：
    stock_prefactors_attr/year=YYYY/part.parquet   ← 物理数据（本脚本写）
    视图 stock_prefactors_attr                      ← read_parquet 基础视图
    视图 v_prefactors                               ← stock_bar1d ⋈ attr（模拟云端宽表）
  ★ 视图建进 duckdb 后，rebuild_warehouse_views.py 换路径自动接管，无需登记。

配额：按**返回行×列**计费。本周剩 ~1.1M（2026-09-28 实测 98.87% 已用）→ 实际拉取
  等下一个滚动释放窗口。默认 --max-cells 9000 万/次（留 10% 余量）：
    第 1 周：2015–2021 ≈ 8,710 万 ✓
    第 2 周：2022–至今 ≈ 7,680 万 ✓

用法：
    python pull_prefactors_attr.py --dry-run            # 只看估算与配额
    python pull_prefactors_attr.py                      # 按断点续拉（预算内能拉几年拉几年）
    python pull_prefactors_attr.py --until 2026-09-26   # 增量刷新时指定截止日
    python pull_prefactors_attr.py --dates 2026-08-21   # 只拉指定日（冒烟/补洞，~7万 cells/日）
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
ROOT = Path(__file__).resolve().parent
TABLE = "stock_prefactors_attr"
SOURCE = "cn_stock_prefactors"
CKPT = ROOT / "_pull_prefactors_attr_ckpt.json"

# 13 列（键 2 + 状态 8 + 行业 3）；列名与云端一致，本地代码零映射
COLS = ["date", "instrument", "list_sector", "list_date", "list_days", "st_status",
        "is_risk_warning", "suspended", "price_limit_status", "line_price_limit",
        "sw_level_index_code", "sw_level1_name", "sw2021_level2"]

DEFAULT_MAX_CELLS = 90_000_000


def quota_left() -> int | None:
    from bigquant import dai
    try:
        q = dai.get_data_quota()
        return int(q["weekly_quota"]) - int(q["used_quota"])
    except Exception as e:
        print(f"  （查配额失败：{str(e)[:80]} → 按无配额信息处理）")
        return None


def pull_year(year: int, until: str) -> pd.DataFrame:
    """拉一个日历年（全市场、13 列）。date 范围过滤 + filters 分区裁剪（已验证可用模式）。"""
    from bigquant import dai
    lo, hi = f"{year}-01-01", min(f"{year}-12-31", until)
    sql = (f"SELECT {', '.join(COLS)} FROM {SOURCE} "
           f"WHERE date >= '{lo}' AND date <= '{hi}'")
    df = None
    for attempt in range(3):
        try:
            df = dai.query(sql, filters={"date": [lo, hi]}).df()[COLS]
            break
        except Exception as e:
            print(f"    重试 {attempt + 1}/3: {str(e)[:120]}")
            time.sleep(5)
    if df is None:
        raise RuntimeError(f"{year} 年三次拉取失败")
    return df


def ingest(df: pd.DataFrame) -> None:
    """按年分区落 parquet（同键去重 keep=last，幂等可重跑）。"""
    d2 = df.copy()
    d2["year"] = pd.to_datetime(d2["date"]).dt.year
    for year, grp in d2.groupby("year"):
        out = ROOT / TABLE / f"year={int(year)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            grp = pd.concat([pd.read_parquet(out), grp], ignore_index=True)
        grp = grp.drop_duplicates(subset=["instrument", "date"], keep="last")
        grp.to_parquet(out, index=False)


def rebuild_views() -> None:
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
    con.execute(f"""CREATE OR REPLACE VIEW {TABLE} AS
        SELECT * EXCLUDE (year) FROM read_parquet(
            '{(ROOT / TABLE).resolve().as_posix()}/**/*.parquet', hive_partitioning=true)""")
    # 合并宽表：行情来自 stock_bar1d（勿重复存），属性左连 —— 模拟云端 cn_stock_prefactors
    con.execute(f"""CREATE OR REPLACE VIEW v_prefactors AS
        SELECT b.date, b.instrument, b."name", b.adjust_factor, b.pre_close, b.open,
               b.high, b.low, b.close, b.volume, b.deal_number, b.amount,
               b.change_ratio, b.turn, b.upper_limit, b.lower_limit,
               a.list_sector, a.list_date, a.list_days, a.st_status,
               a.is_risk_warning, a.suspended, a.price_limit_status, a.line_price_limit,
               a.sw_level_index_code, a.sw_level1_name, a.sw2021_level2
        FROM stock_bar1d AS b
        LEFT JOIN {TABLE} AS a USING (instrument, date)""")
    con.close()


def pull_dates(dates: list[str]) -> pd.DataFrame:
    """拉指定日期列表（date IN + filters 范围 = 已验证模式）。冒烟/补洞用。"""
    from bigquant import dai
    dl = ",".join(f"'{d}'" for d in dates)
    sql = f"SELECT {', '.join(COLS)} FROM {SOURCE} WHERE date IN ({dl})"
    lo, hi = min(dates), max(dates)
    return dai.query(sql, filters={"date": [lo, hi]}).df()[COLS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只估算+查配额，不拉")
    ap.add_argument("--until", default=pd.Timestamp.now().strftime("%Y-%m-%d"),
                    help="截止日（默认今天；增量刷新用）")
    ap.add_argument("--max-cells", type=int, default=DEFAULT_MAX_CELLS,
                    help="本次拉取的 cells 预算（默认 9000 万）")
    ap.add_argument("--dates", default=None,
                    help="只拉指定日期（逗号分隔，如 2026-08-21）—— 冒烟/补洞，不走年批")
    a = ap.parse_args()

    # ── 冒烟/补洞模式：只拉指定日，不做预算判断（量级 ~7 万 cells/日）──
    if a.dates:
        dates = [d.strip() for d in a.dates.split(",") if d.strip()]
        print(f"指定日模式：{dates}（预计 {len(dates) * 5570 * len(COLS):,} cells）")
        df = pull_dates(dates)
        ingest(df)
        rebuild_views()
        con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
        n, d0, d1 = con.execute(
            f"SELECT count(*), min(date), max(date) FROM {TABLE}").fetchone()
        dup = con.execute(
            f"SELECT count(*) FROM (SELECT instrument, date FROM {TABLE} "
            f"GROUP BY 1, 2 HAVING count(*) > 1)").fetchone()[0]
        con.close()
        print(f"完成：本次 +{len(df):,} 行；{TABLE} 现 {n:,} 行 / {str(d0)[:10]}~{str(d1)[:10]}"
              f"  主键重复 {dup} {'OK' if dup == 0 else 'FAIL'}")
        print("视图已建：stock_prefactors_attr / v_prefactors → 可跑 validate_prefactors_attr.py")
        return

    years = list(range(2015, int(a.until[:4]) + 1))
    done = json.loads(CKPT.read_text()) if CKPT.exists() else []
    # 截止日变了（增量刷新）→ 已完成年份里晚于 until 的重拉；这里简单处理：2026 永远允许重拉
    todo = [y for y in years if str(y) not in done or y == int(a.until[:4])]

    print(f"目标：{SOURCE} 的 {len(COLS)} 列属性 → 本地 {TABLE}")
    print(f"年份 {years[0]}–{years[-1]}（截止 {a.until}）  断点已完成 {len(done)} 年  待拉 {len(todo)} 年")

    # 估算（本地 bar1d 行数为基数 + 对未覆盖月份外推）
    con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"), read_only=True)
    local_max = con.execute("SELECT max(date) FROM stock_bar1d").fetchone()[0]
    counts = dict(con.execute(
        f"SELECT year(date), count(*) FROM stock_bar1d WHERE date <= TIMESTAMP '{a.until}' "
        f"GROUP BY 1").fetchall())
    con.close()
    print(f"\n{'年份':<8}{'预计行数':>12}{'cells':>14}")
    est = {}
    for y in todo:
        n = counts.get(y, 0)
        # 本地数据截止 local_max；超出部分按 5570 只/日 × 21 日/月 外推
        if pd.Timestamp(a.until) > pd.Timestamp(local_max) and y >= pd.Timestamp(local_max).year:
            extra_months = ((pd.Timestamp(a.until).year - pd.Timestamp(local_max).year) * 12
                            + pd.Timestamp(a.until).month - pd.Timestamp(local_max).month)
            n += max(0, extra_months) * 21 * 5570
        est[y] = n
        print(f"{y:<8}{n:>12,}{n * len(COLS):>14,}")

    left = quota_left()
    if left is not None:
        print(f"\n当前剩余配额：{left:,} cells")
    if a.dry_run:
        budget = a.max_cells if left is None else min(a.max_cells, left)
        plan = [y for y in todo if sum(est[z] * len(COLS) for z in todo[:todo.index(y) + 1]) <= budget]
        print(f"（--dry-run）预算 {budget:,} 内可拉：{plan or '一个都放不下——等配额释放'}")
        print(f"全部待拉合计 {sum(est[y] for y in todo) * len(COLS):,} cells ≈ "
              f"{sum(est[y] for y in todo) * len(COLS) / 1e8:.2f} 个满配额周")
        return

    budget = a.max_cells if left is None else min(a.max_cells, left)
    spent = 0
    pulled_years = []
    for y in todo:
        cost = est[y] * len(COLS)
        if spent + cost > budget:
            print(f"\n· {y} 年需 {cost:,} cells，超预算（已用 {spent:,}/{budget:,}）→ 留到下次")
            break
        t0 = time.time()
        df = pull_year(y, a.until)
        ingest(df)
        spent += len(df) * len(COLS)
        pulled_years.append(str(y))
        if str(y) not in done:
            done.append(str(y))
        CKPT.write_text(json.dumps(sorted(set(done)), ensure_ascii=False))
        print(f"  {y}: {len(df):,} 行 × {len(COLS)} 列 = {len(df) * len(COLS):,} cells"
              f"  ({time.time() - t0:.0f}s)")

    if pulled_years:
        rebuild_views()
        con = duckdb.connect(str(ROOT / "bigquant_warehouse.duckdb"))
        n_sym, n_row, d0, d1 = con.execute(
            f"SELECT count(DISTINCT instrument), count(*), min(date), max(date) FROM {TABLE}"
        ).fetchone()
        dup = con.execute(
            f"SELECT count(*) FROM (SELECT instrument, date FROM {TABLE} "
            f"GROUP BY 1, 2 HAVING count(*) > 1)").fetchone()[0]
        # 与 bar1d 同年行数对照（两表应同覆盖）
        cmp = con.execute(f"""
            SELECT b.y, b.n AS bar1d, COALESCE(p.n, 0) AS attr,
                   round((COALESCE(p.n,0) - b.n) * 100.0 / b.n, 2) AS diff_pct
            FROM (SELECT year(date) y, count(*) n FROM stock_bar1d GROUP BY 1) b
            LEFT JOIN (SELECT year(date) y, count(*) n FROM {TABLE} GROUP BY 1) p USING (y)
            ORDER BY y""").fetchdf()
        con.close()
        print(f"\n完成 {pulled_years}：{TABLE} 现 {n_sym:,} 只 / {n_row:,} 行 / "
              f"{str(d0)[:10]}~{str(d1)[:10]}  主键重复 {dup} {'OK' if dup == 0 else 'FAIL'}")
        print("\n与 stock_bar1d 分年行数对照（diff 应 ≈0%，偏大说明覆盖不一致）：")
        print(cmp.to_string(index=False))
        print("\n视图已建：stock_prefactors_attr（基础）/ v_prefactors（bar1d⋈attr 宽表）")
        print("抽样校验请跑：python validate_prefactors_attr.py")
    else:
        print("\n本次未拉任何年份（配额不足或无待拉）。")


if __name__ == "__main__":
    main()
