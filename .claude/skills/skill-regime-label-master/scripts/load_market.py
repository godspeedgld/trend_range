#!/usr/bin/env python
"""从本地 warehouse 读取 ETF 日线数据（共用工具）。

用法（命令行导出 CSV）：
  python load_market.py --symbol 510300.SH --output ./data_510300.csv
  python load_market.py --all --output-dir ./data/

用法（模块导入）：
  from load_market import load_etf
  df = load_etf("510300.SH")
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

WAREHOUSE_DB = Path(__file__).resolve().parents[4] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"

CORE_SYMBOL = "510300.SH"      # 沪深300 ETF（核心）
GOLD_SYMBOL = "518880.SH"      # 黄金 ETF（验证）
BOND_SYMBOL = "511010.SH"      # 国债 ETF（验证）

ALL_SYMBOLS = {
    CORE_SYMBOL: "沪深300 ETF",
    GOLD_SYMBOL: "黄金 ETF",
    BOND_SYMBOL: "国债 ETF",
}


def load_etf(symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """读取单只 ETF 日线（date,symbol,open,high,low,close,volume,amount）。"""
    import duckdb
    if not WAREHOUSE_DB.exists():
        raise FileNotFoundError(f"warehouse 不存在: {WAREHOUSE_DB}")
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    sql = f"""
        SELECT date, instrument, open, high, low, close, volume, amount
        FROM fund_bar1d WHERE instrument = '{symbol}'
    """
    if start:
        sql += f" AND date >= '{start}'"
    if end:
        sql += f" AND date <= '{end}'"
    sql += " ORDER BY date"
    df = con.execute(sql).fetchdf()
    con.close()
    if df.empty:
        raise ValueError(f"无数据: {symbol}（检查 warehouse 是否含该品种）")
    df = df.rename(columns={"instrument": "symbol"})
    return df


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol", help="单只 ETF 代码，如 510300.SH")
    g.add_argument("--all", action="store_true", help="导出全部三只")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--output", help="单只导出路径 (.csv)")
    p.add_argument("--output-dir", help="--all 导出目录")
    args = p.parse_args()

    if args.all:
        out_dir = Path(args.output_dir or ".").resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        for sym, name in ALL_SYMBOLS.items():
            df = load_etf(sym, args.start, args.end)
            out = out_dir / f"{sym.split('.')[0]}.csv"
            df.to_csv(out, index=False)
            print(f"{name} {sym}: {len(df)} rows → {out}")
    else:
        df = load_etf(args.symbol, args.start, args.end)
        out = Path(args.output or f"{args.symbol.split('.')[0]}.csv").resolve()
        df.to_csv(out, index=False)
        print(f"{args.symbol}: {len(df)} rows → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
