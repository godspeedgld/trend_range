"""抽样校验：本地 v_prefactors / stock_prefactors_attr 是否与云端 cn_stock_prefactors 一致。

思路（沿用「源头直出」铁律）：本地视图是合并产物（bar1d + attr），云端是原始宽表 ——
抽若干个交易日，两边各取**同一批 (instrument, date) 的同一批列**，逐值比对：

  ① 键集合   两边各有哪些 (instrument, date) —— 缺行/多行
  ② 属性列   13 列里本地存的 11 个数据列逐值比（NULL==NULL 视为相等）
  ③ join 完整性（本地内部检查，零配额）
       v_prefactors 的 attr 列非空率 —— bar1d 有行而 attr 没跟上的比例
  ④ 行情列抽查  close/amount/turn 三列（走 v_prefactors，即 bar1d 侧）
       —— 顺带守住「bar1d 与云端逐值一致」这条前提没有漂移

配额成本：抽样 N 天 × 全市场 ~5,500 行 × 18 列(键+属性13+行情5) ≈ N×10 万 cells
  （默认 --days 30 ≈ 300 万；单日 filters=[d,d] 只扫当日分区，是已验证的省钱模式）

用法：
    python validate_prefactors_attr.py --dry-run     # 只列抽样日和成本，不查
    python validate_prefactors_attr.py               # 抽 30 个交易日全查
    python validate_prefactors_attr.py --days 60     # 更密抽样
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DB = ROOT / "bigquant_warehouse.duckdb"

# 本地存的 11 个数据列（键除外）；行情 3 列走 v_prefactors 单独抽查
ATTR_COLS = ["list_sector", "list_date", "list_days", "st_status", "is_risk_warning",
             "suspended", "price_limit_status", "line_price_limit",
             "sw_level_index_code", "sw_level1_name", "sw2021_level2"]
QUOTE_COLS = ["close", "amount", "turn"]
KEY = ["date", "instrument"]


def sample_dates(n: int) -> list[str]:
    """在本地 attr 已覆盖的日期里均匀抽 n 天（首尾必含，便于盯边界）。"""
    try:
        con = duckdb.connect(str(DB), read_only=True)
        days = [str(r[0])[:10] for r in con.execute(
            "SELECT DISTINCT date FROM stock_prefactors_attr ORDER BY 1").fetchall()]
        con.close()
    except duckdb.CatalogException:
        raise SystemExit("本地 stock_prefactors_attr 视图/数据还不存在 —— 先跑 pull_prefactors_attr.py")
    if not days:
        raise SystemExit("本地 stock_prefactors_attr 还没有数据 —— 先跑 pull_prefactors_attr.py")
    if n >= len(days):
        return days
    idx = np.linspace(0, len(days) - 1, n).round().astype(int)
    return sorted({days[i] for i in idx})


def fetch_remote(dates: list[str], cols: list[str]) -> pd.DataFrame:
    """云端逐日拉（单日 filters 分区裁剪，省钱模式）。"""
    from bigquant import dai
    frames = []
    for d in dates:
        df = dai.query(f"SELECT date, instrument, {', '.join(cols)} FROM cn_stock_prefactors",
                       filters={"date": [d, d]}).df()
        frames.append(df)
        print(f"    {d}: {len(df):,} 行")
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


def cmp_col(a: pd.Series, b: pd.Series) -> tuple[int, int]:
    """逐值比（None/NaN 双空视为相等；时间戳比到日；**数值列按数值比**）。

    ★ 冒烟测试（2026-09-29）踩过：云端单日查询会混进若干 date=NaT 的退市股幽灵行，
      把含 NULL 的整型列（st_status/list_days/...）污染成 float64；若按字符串比，
      "0.0" vs "0" 会**全行误报不一致**。数值列必须数值比。
    """
    a2 = a.reset_index(drop=True)
    b2 = b.reset_index(drop=True)
    num = (pd.api.types.is_numeric_dtype(a2) and pd.api.types.is_numeric_dtype(b2))
    if str(a2.dtype).startswith("datetime") and str(b2.dtype).startswith("datetime"):
        a2 = pd.to_datetime(a2).dt.strftime("%Y-%m-%d")
        b2 = pd.to_datetime(b2).dt.strftime("%Y-%m-%d")
    both = a2.notna() & b2.notna()
    only_a, only_b = a2.notna() & ~b2.notna(), b2.notna() & ~a2.notna()
    if num:
        eq = (a2[both].astype("float64").values == b2[both].astype("float64").values)
    else:
        eq = (a2[both].astype(str).values == b2[both].astype(str).values)
    n_bad = int((~eq).sum()) + int(only_a.sum()) + int(only_b.sum())
    return int(both.sum()), n_bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)   # 用户 2026-09-29 定：默认 30 个交易日
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    dates = sample_dates(a.days)
    print(f"抽样 {len(dates)} 个交易日：{dates[0]} ~ {dates[-1]}")
    n_cols = (2 + len(ATTR_COLS)) + (2 + len(QUOTE_COLS))   # 两趟：属性 13 列 + 行情 5 列
    print(f"预计配额：{len(dates)} × ~5,500 行 × {n_cols} 列（两趟）"
          f"≈ {len(dates) * 5500 * n_cols / 1e4:.0f} 万 cells")
    if a.dry_run:
        print("（--dry-run 到此为止）")
        return

    print("\n① 云端取数（逐日）：")
    r_attr = fetch_remote(dates, ATTR_COLS)
    r_quote = fetch_remote(dates, QUOTE_COLS)   # 单独一趟，避免与 attr 列拼错位
    # ★ 丢弃 date=NaT 的退市股幽灵行（单日分区过滤拦不住 NULL 日期；本地拉取的
    #   WHERE date IN (...) 天然排除它们，故比对前必须对齐口径）
    n_ghost = int(r_attr["date"].isna().sum())
    if n_ghost:
        print(f"    （丢弃 {n_ghost} 行 date=NaT 退市股幽灵行）")
    r_attr = r_attr[r_attr["date"].notna()]
    r_quote = r_quote[r_quote["date"].notna()]

    con = duckdb.connect(str(DB), read_only=True)
    dq = ",".join(f"'{d}'" for d in dates)
    l_attr = con.execute(f"""
        SELECT date, instrument, {', '.join(ATTR_COLS)}
        FROM stock_prefactors_attr WHERE date IN ({dq})""").fetchdf()
    l_quote = con.execute(f"""
        SELECT date, instrument, {', '.join(QUOTE_COLS)}
        FROM v_prefactors WHERE date IN ({dq})""").fetchdf()
    cov = con.execute(f"""
        SELECT count(*) AS total,
               sum(CASE WHEN st_status IS NULL THEN 1 ELSE 0 END) AS attr_null
        FROM v_prefactors WHERE date IN ({dq})""").fetchone()
    con.close()
    for d in (l_attr, l_quote):
        d["date"] = pd.to_datetime(d["date"])

    # ── ② 键集合 ──
    print(f"\n② 键集合（attr）")
    rk, lk = set(zip(r_attr["date"], r_attr["instrument"])), set(zip(l_attr["date"], l_attr["instrument"]))
    print(f"  云端 {len(rk):,}  本地 {len(lk):,}  交集 {len(rk & lk):,}"
          f"  仅云端 {len(rk - lk):,}  仅本地 {len(lk - rk):,}")
    if rk - lk:
        print(f"    仅云端样例: {sorted((str(d)[:10], s) for d, s in (rk - lk))[:6]}")

    # ── ③ 属性列逐值 ──
    print(f"\n③ 属性列逐值（共有键上，NULL==NULL 相等）")
    m = r_attr.merge(l_attr, on=KEY, how="inner", suffixes=("_c", "_l"))
    print(f"  可比行 {len(m):,}")
    all_ok = True
    for c in ATTR_COLS:
        n, bad = cmp_col(m[f"{c}_c"], m[f"{c}_l"])
        ok = bad == 0
        all_ok &= ok
        print(f"    {c:<22} 比对 {n:>7,}  不一致 {bad:>4}  {'✓' if ok else '✗'}")

    # ── ④ 行情列抽查（bar1d 侧没漂移）──
    print(f"\n④ 行情列抽查（close/amount/turn，走 v_prefactors=bar1d 侧）")
    mq = r_quote.merge(l_quote, on=KEY, how="inner", suffixes=("_c", "_l"))
    for c in QUOTE_COLS:
        d_ = (mq[f"{c}_c"].astype(float) - mq[f"{c}_l"].astype(float)).abs()
        both = mq[f"{c}_c"].notna() & mq[f"{c}_l"].notna()
        bad = int((d_[both] > 1e-9 + 1e-9 * mq.loc[both, f"{c}_l"].abs()).sum()) \
            + int((mq[f"{c}_c"].notna() ^ mq[f"{c}_l"].notna()).sum())
        ok = bad == 0
        all_ok &= ok
        print(f"    {c:<22} 比对 {int(both.sum()):>7,}  不一致 {bad:>4}  {'✓' if ok else '✗'}")

    # ── ⑤ join 完整性 ──
    total, attr_null = cov
    print(f"\n⑤ v_prefactors join 完整性：{total:,} 行中 attr 全空 {attr_null:,} 行"
          f"（{attr_null / max(1, total):.2%}，应≈0）")

    print("\n" + "=" * 60)
    print("★ 结论：" + ("本地视图与云端 cn_stock_prefactors **抽样一致**。" if all_ok
                       else "存在不一致 —— 见上方 ✗ 列，先修再用于策略。"))
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
