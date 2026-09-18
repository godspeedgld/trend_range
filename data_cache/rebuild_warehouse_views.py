"""重建仓库视图 —— 换电脑 / 挪目录后跑一次即可

**为什么需要它**：Parquet 数据本身与路径无关，但 .duckdb 文件里那些视图把**绝对路径**
写死在 `read_parquet('C:/Quant/trend_range/data_cache/xxx/**/*.parquet')` 里。
所以仓库一旦不在原路径（拷到别的电脑、或换个盘符），视图**全部失效**（数据还在，只是
DuckDB 找不到）。

本脚本做两件事：读出旧库全部视图的原始 SQL → 把旧根路径替换成当前实际路径 → 建回去。
派生视图（如 v_stock_panel / stock_industry_component_daily）依赖别的视图，所以按
依赖顺序建：先 read_parquet 的基础视图，再建引用它们的。

用法：
    python data_cache/rebuild_warehouse_views.py                       # 两个仓库都重建
    python data_cache/rebuild_warehouse_views.py data_cache/bigquant_warehouse
    python data_cache/rebuild_warehouse_views.py <目录> --from "C:/旧路径"
    python data_cache/rebuild_warehouse_views.py <目录> --dry-run        # 只看会建哪些
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import duckdb

# 视图 SQL 里 read_parquet('...') 的路径；用来判断哪些是"基础视图"
PARQUET_RE = re.compile(r"read_parquet\(\s*'([^']+)'", re.I)
SYS_PREFIX = ("duckdb_", "sqlite_", "pragma_", "information_schema")


def new_root_from_sql(sql: str) -> str | None:
    """从视图 SQL 里反推旧仓库根路径（read_parquet 路径里 '/*.parquet' 之前那段）"""
    m = PARQUET_RE.search(sql)
    if not m:
        return None
    p = m.group(1).replace("\\", "/")
    # 'C:/.../warehouse/stock_bar1d/**/*.parquet' → 去掉表名与通配
    return p.split("/**")[0].rsplit("/", 1)[0] if "/**" in p else None


def collect_views(db: Path) -> list[tuple[str, str]]:
    con = duckdb.connect(str(db), read_only=True)
    rows = con.execute("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal").fetchall()
    con.close()
    return [(n, s) for n, s in rows
            if s and not n.startswith(SYS_PREFIX) and "TEMP VIEW" not in s.upper()]


def rebuild(root: Path, old_prefix: str | None, dry: bool) -> int:
    db = next(iter(root.glob("*.duckdb")), None)
    if db is None:
        print(f"  {root.name}: 目录里没有 .duckdb 文件 —— 跳过（数据还在，只是没有视图定义）")
        return 0
    views = collect_views(db)
    if not views:
        print(f"  {root.name}: 库里没有自定义视图 —— 跳过")
        return 0
    now = root.resolve().as_posix()
    # 基础视图（直接读 parquet）先建，其余（引用别的视图）后建
    base = [(n, s) for n, s in views if PARQUET_RE.search(s)]
    derived = [(n, s) for n, s in views if not PARQUET_RE.search(s)]
    print(f"  {root.name}: {len(base)} 个基础视图 + {len(derived)} 个派生视图")
    if dry:
        for n, s in base + derived:
            print(f"     · {n}")
        return len(views)

    con = duckdb.connect(str(db))
    ok, no_data, failed = 0, [], []
    for n, sql in base + derived:
        old = old_prefix or new_root_from_sql(sql)
        if old:
            for variant in {old, old.replace("/", "\\"), str(Path(old))}:
                sql = sql.replace(variant, now)
        sql = re.sub(r"^CREATE\s+(OR\s+REPLACE\s+)?VIEW", "CREATE OR REPLACE VIEW", sql,
                     count=1, flags=re.I)
        try:
            # ★ 注意：DuckDB 建视图时会**校验 glob**，所以数据目录不存在时这里就会报
            #   "No files found that match the pattern" —— 这属于"这份数据没拷过来"，
            #   不是脚本问题，单列出来而不是当失败
            con.execute(sql)
            ok += 1
        except Exception as e:
            (no_data if "No files found" in str(e) else failed).append(n)
    # 校验：能查到行数才算真的通了
    bad = []
    for n, _ in base + derived:
        try:
            con.execute(f'SELECT count(*) FROM "{n}"').fetchone()
        except Exception:
            bad.append(n)
    con.close()
    msg = f"     建好 {ok}/{len(views)} 个"
    if no_data:
        msg += f"；{len(no_data)} 个因数据目录不存在跳过 {no_data}"
    if failed:
        msg += f"；{len(failed)} 个报错 {failed}"
    if bad:
        msg += f"；建后仍查不了 {bad}"
    print(msg)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*", help="仓库目录（默认 data_cache 下所有含 .duckdb 的目录）")
    ap.add_argument("--from", dest="old", default=None, help="显式指定旧根路径")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    targets = [Path(d) for d in a.dirs] if a.dirs else sorted(
        p.parent for p in Path(__file__).resolve().parent.glob("*/*.duckdb"))
    print(f"重建 {len(targets)} 个仓库的视图：")
    total = sum(rebuild(t, a.old, a.dry_run) for t in targets)
    print(f"完成，共 {total} 个视图" + ("（dry-run，未写库）" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
