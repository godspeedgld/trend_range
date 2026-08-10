#!/usr/bin/env python
"""BigQuant 数据拉取 + 本地保存。

通过 dai.query() SQL 拉取数据，保存为 Parquet/CSV。

用法：
  python scripts/call_api.py \\
    --table cn_stock_bar1d \\
    --instruments 000001.SZ,600000.SH \\
    --start 2024-01-01 --end 2025-06-30 \\
    --output ./data/stocks.parquet

认证：自动读取 ~/.bigquant/config.json 中的 AK/SK。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_sql(table: str, instruments: list[str] | None,
              start_date: str | None, end_date: str | None,
              fields: list[str] | None) -> str:
    """构建 dai.query() SQL。"""
    cols = ", ".join(fields) if fields else "*"
    conditions = []
    if start_date:
        conditions.append(f"date >= '{start_date}'")
    if end_date:
        conditions.append(f"date <= '{end_date}'")
    if instruments:
        quoted = ", ".join(f"'{s}'" for s in instruments)
        conditions.append(f"instrument IN ({quoted})")

    sql = f"SELECT {cols} FROM {table}"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY date, instrument"
    return sql


def fetch(sql: str):
    """执行 dai.query() 并返回 DataFrame。"""
    from bigquant import dai

    print(f"[bigquant] {sql[:120]}...", file=sys.stderr)
    result = dai.query(sql)
    df = result.df()
    print(f"[bigquant] {len(df)} 行, {len(df.columns)} 列", file=sys.stderr)
    return df


def save(df, output: Path, fmt: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "parquet":
        df.to_parquet(output, index=False)
    elif fmt == "csv":
        df.to_csv(output, index=False, encoding="utf-8-sig")
    else:
        raise ValueError(f"不支持格式: {fmt}")
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"[bigquant] 已保存: {output} ({size_mb:.1f} MB)", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--table", required=True, help="SQL 表名，如 cn_stock_bar1d")
    p.add_argument("--instruments", help="合约代码（逗号分隔），省略=全市场")
    p.add_argument("--start", help="开始日期 yyyy-mm-dd")
    p.add_argument("--end", help="结束日期 yyyy-mm-dd")
    p.add_argument("--fields", help="字段（逗号分隔），省略=全字段")
    p.add_argument("--output", required=True, help="输出文件路径 (.parquet / .csv)")
    p.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    args = p.parse_args()

    instruments = [s.strip() for s in args.instruments.split(",") if s.strip()] if args.instruments else None
    fields = [s.strip() for s in args.fields.split(",") if s.strip()] if args.fields else None

    sql = build_sql(args.table, instruments, args.start, args.end, fields)

    try:
        df = fetch(sql)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    if df is None or len(df) == 0:
        print("警告: 无数据", file=sys.stderr)
        return 0

    save(df, Path(args.output).resolve(), args.format)

    # 摘要
    info = {"rows": len(df), "columns": list(df.columns)}
    if "date" in df.columns:
        info["date_range"] = [str(df["date"].min())[:10], str(df["date"].max())[:10]]
    if "instrument" in df.columns:
        info["n_instruments"] = int(df["instrument"].nunique())
    print(json.dumps(info, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
