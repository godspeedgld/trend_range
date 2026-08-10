#!/usr/bin/env python
"""BigQuant 数据拉取 + 本地保存 CLI。

用法：
  python scripts/call_api.py \\
    --table bar1d_CN_FUTURE \\
    --instruments IF2506.CFX,IC2506.CFX \\
    --start 2024-01-01 --end 2025-06-30 \\
    --output ./data/futures.parquet \\
    --format parquet

认证：SDK 自动读取 ~/.bigquant/config.json 中的 AK/SK 密钥对。
获取密钥：https://bigquant.com/account/settings → API 密钥
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_sdk() -> bool:
    """检查 bigquant SDK 是否可用。"""
    try:
        import bigquant  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def fetch_data(table: str, instruments: list[str] | None,
               start_date: str | None, end_date: str | None,
               fields: list[str] | None):
    """通过 dai.query() SQL 拉取数据。"""
    from bigquant import dai

    cols = ", ".join(fields) if fields else "*"
    sql = f"SELECT {cols} FROM {table} WHERE 1=1"
    if start_date:
        sql += f" AND date >= '{start_date}'"
    if end_date:
        sql += f" AND date <= '{end_date}'"
    if instruments:
        quoted = ", ".join(f"'{s}'" for s in instruments)
        sql += f" AND instrument IN ({quoted})"
    sql += " ORDER BY date, instrument"

    print(f"[bigquant] 拉取 {table} ...", file=sys.stderr)
    if instruments:
        print(f"[bigquant] 合约: {instruments}", file=sys.stderr)
    if start_date or end_date:
        print(f"[bigquant] 日期: {start_date or '不限'} ~ {end_date or '不限'}", file=sys.stderr)

    result = dai.query(sql)
    df = result.df()
    print(f"[bigquant] 获取 {len(df)} 行, {len(df.columns)} 列", file=sys.stderr)
    return df


def save_data(df, output: Path, fmt: str) -> None:
    ensure_dir(output)
    if fmt == "parquet":
        df.to_parquet(output, index=False)
    elif fmt == "csv":
        df.to_csv(output, index=False, encoding="utf-8-sig")
    else:
        raise ValueError(f"不支持格式: {fmt}")
    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"[bigquant] 已保存: {output} ({size_mb:.1f} MB)", file=sys.stderr)


def info_data(df) -> dict:
    """生成数据摘要。"""
    info = {
        "rows": len(df),
        "columns": list(df.columns),
        "memory_mb": round(df.memory_usage(deep=True).sum() / (1024 * 1024), 2),
    }
    if "date" in df.columns:
        info["date_range"] = [str(df["date"].min()), str(df["date"].max())]
    if "instrument" in df.columns:
        symbols = df["instrument"].unique()
        info["symbols"] = list(symbols[:20])
        info["n_symbols"] = int(len(symbols))
    return info


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--table", required=True, help="数据表 ID，如 bar1d_CN_FUTURE")
    p.add_argument("--instruments", help="合约代码（逗号分隔），省略=全市场")
    p.add_argument("--start", help="开始日期 yyyy-mm-dd")
    p.add_argument("--end", help="结束日期 yyyy-mm-dd")
    p.add_argument("--fields", help="字段（逗号分隔），省略=全字段")
    p.add_argument("--output", required=True, help="输出文件路径 (.parquet / .csv)")
    p.add_argument("--format", default="parquet", choices=["parquet", "csv"])
    p.add_argument("--json", action="store_true", help="以 JSON 输出数据摘要")
    args = p.parse_args()

    if not check_sdk():
        print("错误: bigquant SDK 未安装。请执行: pip install bigquant -U", file=sys.stderr)
        return 1

    instruments = [s.strip() for s in args.instruments.split(",") if s.strip()] if args.instruments else None
    fields = [s.strip() for s in args.fields.split(",") if s.strip()] if args.fields else None

    try:
        df = fetch_data(args.table, instruments, args.start, args.end, fields)
    except Exception as e:
        print(f"错误: 数据拉取失败: {e}", file=sys.stderr)
        print("提示: 检查 ~/.bigquant/config.json 中 AK/SK 是否有效", file=sys.stderr)
        return 2

    if df is None or len(df) == 0:
        print("警告: 返回数据为空（检查日期范围/合约代码/权限）", file=sys.stderr)
        return 0

    output = Path(args.output).resolve()
    save_data(df, output, args.format)

    if args.json:
        info = info_data(df)
        info["output"] = str(output)
        print(json.dumps(info, ensure_ascii=False, indent=2, default=str))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
