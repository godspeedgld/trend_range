#!/usr/bin/env python
"""数据检查：按用户投研方向核对本地数据是否满足。

用法：
  python check_data.py {project_dir} --needs 沪深300,中证500      # 指数
  python check_data.py {project_dir} --needs 成分股                # 成分股
  python check_data.py {project_dir} --needs 期货                  # 期货
  python check_data.py {project_dir} --needs 沪深300,成分股,期货   # 混合

输出：缺失清单。有缺失 → exit 1（终止），提示用 skill-bigquant-sdk 拉取。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

WAREHOUSE_DB = Path(__file__).resolve().parents[4] / "data_cache" / "bigquant_warehouse" / "bigquant_warehouse.duckdb"

# 指数代码映射
INDEX_CODES = {
    "沪深300": "000300.SH", "中证500": "000905.SH", "中证1000": "000852.SH",
    "中证2000": "932000.CSI", "创业板指": "399006.SZ", "科创50": "000688.SH",
}


def check_index(con, code: str) -> bool:
    r = con.execute(
        f"SELECT count(*) FROM index_bar1d WHERE instrument='{code}'"
    ).fetchone()
    return bool(r and r[0] > 0)


def check_stocks(con) -> tuple[int, str]:
    r = con.execute("SELECT count(DISTINCT instrument) FROM stock_bar1d").fetchone()
    n = r[0] if r else 0
    r2 = con.execute("SELECT min(date), max(date) FROM stock_bar1d").fetchone()
    return n, f"{r2[0]}~{r2[1]}" if r2 and r2[0] else "无"


def check_futures(con) -> bool:
    try:
        r = con.execute("SELECT count(*) FROM future_bar1d").fetchone()
        return bool(r and r[0] > 0)
    except Exception:
        return False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--needs", required=True, help="逗号分隔：指数名/成分股/期货")
    args = p.parse_args()

    needs = [s.strip() for s in args.needs.split(",") if s.strip()]
    if not WAREHOUSE_DB.exists():
        print(f"错误: warehouse 不存在: {WAREHOUSE_DB}")
        return 1

    import duckdb
    con = duckdb.connect(str(WAREHOUSE_DB), read_only=True)
    missing, available = [], []

    for item in needs:
        if item == "成分股":
            n, rng = check_stocks(con)
            if n > 100:  # 成分股需要全市场，>100 只才视为可用
                available.append(f"成分股: {n} 只 ({rng})")
            else:
                missing.append(f"成分股: 仅 {n} 只 ({rng})，不满足全市场成分股需求")
        elif item == "期货":
            if check_futures(con):
                available.append("期货: 有数据")
            else:
                missing.append("期货: 无数据")
        elif item in INDEX_CODES:
            code = INDEX_CODES[item]
            if check_index(con, code):
                r = con.execute(f"SELECT min(date), max(date) FROM index_bar1d WHERE instrument='{code}'").fetchone()
                available.append(f"{item}({code}): {r[0]}~{r[1]}")
            else:
                missing.append(f"{item}({code}): 缺失")
        else:
            missing.append(f"未知需求: {item}")
    con.close()

    print("=== 数据检查 ===")
    for a in available:
        print(f"  [OK] {a}")
    for m in missing:
        print(f"  [MISSING] {m}")
    print(f"\n缺失 {len(missing)} 项")

    # 更新 manifest
    mp = Path(args.project_dir).resolve() / "manifest.json"
    if mp.exists():
        m = json.loads(mp.read_text(encoding="utf-8-sig"))
        m["data_check"] = {"status": "ok" if not missing else "missing",
                           "missing": missing, "note": None if not missing else
                           "请用 skill-bigquant-sdk 拉取缺失数据后重试"}
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if missing:
        print("\n【终止】数据不满足，请先用 skill-bigquant-sdk 拉取缺失数据。")
        return 1
    print("\n【通过】数据满足，可进入数据分析或策略迭代。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
