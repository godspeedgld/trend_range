"""按年**向前**补齐 BigQuant 仓库 4 张表（默认 --year 2014）。

顺序（用户 2026-10-13 指定，不可颠倒）：
   step1  stock_bar1d                  —— 5 组**按序**：沪深300 → 中证500 → 中证1000 → 中证2000 → 其他
   step2  stock_prefactors_attr        —— 13 列（键2 + 状态8 + 行业3）
   step3  stock_industry_sw_bar1d      —— 31 个申万一级行业（3 列，与既有本地表一致）
   step4  stock_industry_component_daily —— 11 列，**月末快照**（sw2021）

两条硬依赖（否则跑出来是错的）：
  ★ step1 的 4 个指数组符号池来自**本地 index_component** ⇒ 先跑 `pull_index_component_backward.py`
    （不跑 = 指数组并集为空 ⇒ 全市场都塞进「其他」组，分组语义失真）
  ★ bar1d 必须先于 prefactors_attr：后者既有的「逐年全量校验」以 bar1d 为基准键级反连接

口径严格按 skill-bigquant-sdk（SKILL.md Part 2 + references/warehouse-playbook.md）：
  · **列拉取铁律**：显式列出 data_tables.md 定义列，禁 `SELECT *`
  · 年分区 `year=YYYY/part.parquet` + 主键合并去重（keep=last）
  · 视图重建用**绝对路径 + as_posix()**
  · **拉前先估 cells**；分批（bar1d 40 只/批）+ 断点续拉 + 失败重试
  · 采集日 / 月末日一律取**本地日历缓存**（1990~2026），不额外调 all_trading_days

用法：
  python pull_year_backward.py --year 2014 --dry-run     # 只估算，不调 API
  python pull_year_backward.py --year 2014               # 真拉
（配额不够时中途停，重跑同命令按断点续传）
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DB = ROOT / "bigquant_warehouse.duckdb"
CKPT = ROOT / "_pull_year_backward_ckpt.json"
CAL_PKL = ROOT.parent / "trading_calendar_cache.pkl"
BATCH = 40

# ── 列清单：全部照 data_tables.md，禁 SELECT * ──
COLS_BAR1D = ["instrument", "date", "name", "open", "high", "low", "close", "pre_close",
              "volume", "amount", "turn", "deal_number", "change_ratio", "adjust_factor",
              "upper_limit", "lower_limit"]                                        # 16 列
COLS_PRE = ["date", "instrument", "list_sector", "list_date", "list_days", "st_status",
            "is_risk_warning", "suspended", "price_limit_status", "line_price_limit",
            "sw_level_index_code", "sw_level1_name", "sw2021_level2"]              # 13 列
COLS_SW = ["date", "instrument", "close"]                                          # 3 列
COLS_IND = ["instrument", "industry", "industry_name", "industry_instrument",
            "industry_level1_code", "industry_level1_name", "industry_level2_code",
            "industry_level2_name", "industry_level3_code", "industry_level3_name",
            "date"]                                                                # 11 列

INDEXES = "('000300.SH','000905.SH','000852.SH','932000.CSI')"
GROUP_ORDER = [("hs300", "000300.SH"), ("csi500", "000905.SH"),
               ("csi1000", "000852.SH"), ("csi2000", "932000.CSI")]


# ───────────────────────── 通用工具 ─────────────────────────
def cal_dates(year: int) -> pd.DatetimeIndex:
    d = pickle.load(open(CAL_PKL, "rb"))
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(d["calendar"] if isinstance(d, dict) else d)))
    return cal[cal.year == year]


def month_ends(year: int) -> list[str]:
    y = cal_dates(year)
    s = pd.Series(y, index=y)
    return [pd.Timestamp(v).strftime("%Y-%m-%d") for v in s.groupby(y.to_period("M")).last().values]


def ingest(df: pd.DataFrame, table: str, pk: list[str]) -> int:
    if df.empty:
        return 0
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["year"] = df["date"].dt.year
    tdir = ROOT / table
    for y, g in df.groupby("year"):
        out = tdir / f"year={int(y)}" / "part.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.exists():
            old = pd.read_parquet(out)
            g = pd.concat([old, g.astype(old.dtypes.to_dict(), errors="ignore")], ignore_index=True)
        g.drop_duplicates(subset=pk, keep="last").to_parquet(out, index=False)
    return len(df)


def rebuild_view(table: str):
    con = duckdb.connect(str(DB))
    tdir = (ROOT / table).resolve().as_posix()
    con.execute(f"CREATE OR REPLACE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{tdir}/**/*.parquet', hive_partitioning=True)")
    con.close()


def q(sql: str, cols: list[str], tries: int = 3):
    """dai.query + 重试；返回 df 或 None（配额尽/网络）。"""
    from bigquant import dai
    for i in range(tries):
        try:
            return dai.query(sql).df()[cols]
        except Exception as e:
            print(f"    重试 {i+1}/{tries}: {str(e)[:110]}")
            time.sleep(5)
    return None


def local_syms(sql: str) -> set[str]:
    con = duckdb.connect(str(DB), read_only=True)
    try:
        return {r[0] for r in con.execute(sql).fetchall()}
    finally:
        con.close()


# ───────────────────────── 各步 ─────────────────────────
def step1_bar1d(year: int) -> bool:
    print(f"\n【step1】stock_bar1d {year} —— 5 组按序")
    lo, hi = f"{year}-01-01", f"{year}-12-31"
    # 4 个指数组：该年 index_component 并集（**先跑 pull_index_component_backward.py**）
    grp_syms = {}
    for name, idx in GROUP_ORDER:
        grp_syms[name] = local_syms(
            f"SELECT DISTINCT member_code FROM index_component "
            f"WHERE instrument='{idx}' AND TRY_CAST(date AS VARCHAR) LIKE '{year}%'")
        if not grp_syms[name]:
            print(f"  ⚠ {name} 该年并集为空 —— 是否忘了先跑 pull_index_component_backward.py？")
    four = set().union(*grp_syms.values())
    # 其他组：母表 − 四指数并集（母表查询仅 1 列，~5K cells；退市老代码拉取返回空属预期）
    ext = q("SELECT instrument FROM cn_stock_basic_info", ["instrument"])
    if ext is None:
        print("  ✗ 母表查询失败（配额/网络）→ 中止"); return False
    ext = set(ext["instrument"])
    grp_syms["rest"] = ext - four
    print(f"  组规模：" + " | ".join(f"{k} {len(v):,}" for k, v in grp_syms.items()))

    done = set(json.loads(CKPT.read_text()).get(str(year), [])) if CKPT.exists() else set()
    ck = json.loads(CKPT.read_text()) if CKPT.exists() else {}
    ck.setdefault(str(year), [])
    for name, _ in GROUP_ORDER + [("rest", None)]:
        syms = sorted(grp_syms[name])
        for i in range(0, len(syms), BATCH):
            b = syms[i:i + BATCH]
            tag = f"{name}:{b[0]}"
            if tag in ck[str(year)]:
                continue
            inl = ",".join(f"'{s}'" for s in b)
            df = q(f"SELECT {', '.join(COLS_BAR1D)} FROM cn_stock_bar1d "
                   f"WHERE instrument IN ({inl}) AND date >= '{lo}' AND date <= '{hi}'", COLS_BAR1D)
            if df is None:
                CKPT.write_text(json.dumps(ck)); print("  ✗ 中止（断点已存，重跑续传）"); return False
            n = ingest(df, "stock_bar1d", ["instrument", "date"])
            ck[str(year)].append(tag); CKPT.write_text(json.dumps(ck))
            print(f"    {name} 批{i//BATCH+1:>3}: {len(b):>3} 只 → {n:>8,} 行", flush=True)
    rebuild_view("stock_bar1d")
    return True


def step2_prefactors(year: int) -> bool:
    print(f"\n【step2】stock_prefactors_attr {year} —— 13 列")
    df = q(f"SELECT {', '.join(COLS_PRE)} FROM cn_stock_prefactors "
           f"WHERE date >= '{year}-01-01' AND date <= '{year}-12-31'", COLS_PRE)
    if df is None:
        print("  ✗ 中止（配额/网络）"); return False
    n = ingest(df, "stock_prefactors_attr", ["instrument", "date"])
    print(f"  {len(df):,} 行 → 入库 {n:,}")
    rebuild_view("stock_prefactors_attr")
    return True


def step3_sw(year: int) -> bool:
    print(f"\n【step3】stock_industry_sw_bar1d {year} —— 3 列")
    df = q(f"SELECT {', '.join(COLS_SW)} FROM cn_stock_industry_sw_bar1d "
           f"WHERE date >= '{year}-01-01' AND date <= '{year}-12-31'", COLS_SW)
    if df is None:
        print("  ✗ 中止（配额/网络）"); return False
    n = ingest(df, "stock_industry_sw_bar1d", ["instrument", "date"])
    print(f"  {len(df):,} 行 → 入库 {n:,}")
    rebuild_view("stock_industry_sw_bar1d")
    return True


def step4_industry_component(year: int) -> bool:
    print(f"\n【step4】stock_industry_component_daily {year} —— 月末快照 11 列（sw2021）")
    me = month_ends(year)
    din = ",".join(f"TIMESTAMP '{d}'" for d in me)
    df = q(f"SELECT {', '.join(COLS_IND)} FROM cn_stock_industry_component "
           f"WHERE industry='sw2021' AND date IN ({din})", COLS_IND)
    if df is None:
        print("  ✗ 中止（配额/网络）"); return False
    n = ingest(df, "stock_industry_component_daily", ["instrument", "date"])
    print(f"  {len(me)} 个月末 {len(df):,} 行 → 入库 {n:,}")
    rebuild_view("stock_industry_component_daily")
    return True


# ───────────────────────── 估算 / 主流程 ─────────────────────────
def estimate(year: int) -> int:
    """cells 粗估（行数用「本地 2015+ 的实际密度」按年份外推不现实 → 用上界口径）。"""
    nd = len(cal_dates(year))
    n_stk = 3000                                    # 2010-2014 沪深上市数 ~2,100~2,600，取上界
    parts = [
        ("stock_bar1d 16 列",            n_stk * nd * len(COLS_BAR1D)),
        ("stock_prefactors_attr 13 列",  n_stk * nd * len(COLS_PRE)),
        ("stock_industry_sw_bar1d 3 列",     31 * nd * len(COLS_SW)),
        ("industry_component 11 列(月末)", n_stk * len(month_ends(year)) * len(COLS_IND)),
    ]
    print(f"\n{year} 年估算（交易日 {nd}，股票数上限 {n_stk}）：")
    tot = 0
    for k, c in parts:
        tot += c
        print(f"  {k:34} ≈ {c/1e6:7.2f}M cells")
    print(f"  ── 合计 ≈ {tot/1e6:.1f}M cells")
    return tot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    est = estimate(a.year)
    if a.dry_run:
        con = duckdb.connect(str(DB), read_only=True)
        for t in ("stock_bar1d", "stock_prefactors_attr", "stock_industry_sw_bar1d",
                  "stock_industry_component_daily"):
            r = con.execute(f"SELECT min(date), max(date), count(*) FROM {t}").fetchone()
            print(f"  本地 {t:32} {str(r[0])[:10]} ~ {str(r[1])[:10]} | {r[2]:,} 行")
        con.close()
        print("\n(--dry-run：未调 API)")
        return 0

    for step in (step1_bar1d, step2_prefactors, step3_sw, step4_industry_component):
        if not step(a.year):
            print(f"\n✗ 中断于 {step.__name__}（已完成部分已落盘，重跑同命令续传）")
            return 1
    print(f"\n✓ {a.year} 年四表完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
