"""校验 build_factor_weekly.py 的产物（factor_dir_1w / factor_volstat_1w / v_factor_1w）。

五项：
  ① 形状     —— 列名集合与由 SPEC 推出的 296/216 个 key **逐名相等**（不多不少）；(date,instrument) 唯一
  ② 逐值抽检 —— 随机 N 只 × 随机 K 个因子目录 → 调**库自己的公开 `compute_factor()`** 在同一周频 bars
                上重算 → 与宽表列 rtol=1e-5 **全等**（这是「我算的 == 库算的」的硬证据）
  ③ 覆盖率   —— 逐列 NaN 率 min/中位/max（与库 validation_real 的 coverage≈0.99 同量级）
  ④ 键完整性 —— 无重复键；instrument 全 .SH/.SZ；表内日期 ⊂ 真实交易日；报告「是当周最后交易日」的比例
  ⑤ 视图     —— 三视图可查、行数一致；v_factor_1w 取一行 512 列非全空

用法：python validate_factor_weekly.py [--symbols 20] [--factors 10] [--seed 7]
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
import build_factor_weekly as bfw          # 复用 load_bars / to_weekly / load_specs（同目录）

OK, BAD = "✓", "✗"
fails: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {OK if ok else BAD} {label}" + (f" —— {detail}" if detail else ""))
    if not ok:
        fails.append(label)


def load_dir_module(lib: str, dirname: str):
    fp = bfw.LIBS[lib] / dirname / "scripts" / "factor.py"
    spec = importlib.util.spec_from_file_location("v_" + dirname, fp)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=20)
    ap.add_argument("--factors", type=int, default=10)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    t0 = time.time()
    con = duckdb.connect(str(bfw.DB), read_only=True)

    # ───────── ① 形状 ─────────
    print("① 形状（列名逐名比对 SPEC）")
    for lib, table in bfw.TABLE.items():
        specs = bfw.load_specs(lib)
        want = {c["col"] for c in bfw.build_combos(specs)}
        have = {r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'").fetchall()}
        have -= {"date", "instrument", "year"}
        check(f"{table} 列名 == SPEC 推出的 {len(want)} 个",
              want == have, f"缺 {sorted(want-have)[:5]} / 多 {sorted(have-want)[:5]}" if want != have else f"{len(have)} 列")

    # ───────── ④ 键完整性 ─────────
    print("④ 键完整性")
    for table in list(bfw.TABLE.values()) + ["v_factor_1w"]:
        dup = con.execute(f"SELECT count(*) FROM (SELECT date, instrument FROM \"{table}\" "
                          "GROUP BY 1,2 HAVING count(*)>1)").fetchone()[0]
        check(f"{table} (date,instrument) 无重复", dup == 0, f"{dup} 组重复")
    nbad = con.execute("SELECT count(*) FROM factor_dir_1w "
                       "WHERE NOT (instrument LIKE '%.SH' OR instrument LIKE '%.SZ')").fetchone()[0]
    check("instrument 全为 .SH/.SZ", nbad == 0, f"{nbad} 行越界")

    sd = set(bfw.signal_dates(bfw.load_calendar()))
    for table in ("factor_dir_1w", "factor_volstat_1w"):
        ds = set(pd.to_datetime(
            con.execute(f"SELECT DISTINCT date FROM {table} ORDER BY 1").df()["date"]))
        check(f"{table} 日期 ⊂ 全局周频信号日", ds <= sd, f"{len(ds - sd)} 个非信号日")
        print(f"      · {table}: {len(ds)} 个信号日（全局信号日共 {len(sd)} 个，"
              f"缺 {len(sd - ds)} 个 = 当日无个股有行）")

    # ───────── ② 逐值抽检（硬证据）─────────
    print(f"② 逐值抽检（{a.symbols} 只 × 每库 {a.factors} 个因子目录，调库的 compute_factor 重算）")
    syms = [r[0] for r in con.execute(
        "SELECT DISTINCT instrument FROM factor_dir_1w ORDER BY instrument").fetchall()]
    pick_syms = list(rng.choice(sorted(syms), size=min(a.symbols, len(syms)), replace=False))
    bars = bfw.load_bars(pick_syms)
    weekly = bfw.to_weekly(bars, bfw.signal_dates(bfw.load_calendar()))
    for lib, table in bfw.TABLE.items():
        specs = bfw.load_specs(lib)
        dirs = sorted({s["_dir"] for s in specs})
        pick = rng.choice(dirs, size=min(a.factors, len(dirs)), replace=False)
        n_grp = n_ok = n_row = 0
        worst, worst_where = 0.0, ""
        for sym in pick_syms:
            sub = weekly[weekly["instrument"] == sym][
                ["date", "open", "high", "low", "close", "volume"]].copy()
            if sub.empty:
                continue
            sub["symbol"] = sym
            for dn in pick:
                mod = load_dir_module(lib, dn)
                col = f"{mod.SPEC['base']}_{int(mod.SPEC['params'].get('window', 20))}w_{mod.SPEC['transform']}"
                # ★ 用 to_numpy 对齐（compute_factor 单标的下按 date 排序，与 sub 同序）
                got = mod.compute_factor(sub)[mod.FACTOR_COLUMN].to_numpy(dtype=float)
                exp = con.execute(f'SELECT date, "{col}" FROM {table} WHERE instrument=? ORDER BY date',
                                  [sym]).df()
                e = exp[col].to_numpy(dtype=float)
                n_grp += 1
                if len(got) != len(e):
                    worst_where = f"{sym}/{dn} 行数 {len(got)}≠{len(e)}"
                    continue
                msk = ~(np.isnan(got) & np.isnan(e))
                n_row += int(msk.sum())
                if msk.any():
                    denom = np.where(np.abs(e[msk]) > 0, np.abs(e[msk]), np.nan)
                    if np.isfinite(denom).any():
                        rel = float(np.nanmax(np.abs(got[msk] - e[msk]) / denom))
                        if rel > worst:
                            worst, worst_where = rel, f"{sym}/{dn}"
                if np.allclose(got, e, rtol=1e-5, atol=1e-8, equal_nan=True):
                    n_ok += 1
        check(f"{lib}: 抽检 {len(pick_syms)}×{len(pick)} = {n_grp} 组逐值一致", n_ok == n_grp,
              f"{n_ok}/{n_grp} 组通过（{n_row:,} 可比行）；最大相对差 {worst:.2e} @ {worst_where}")

    # ───────── ③ 覆盖率 ─────────
    print("③ 覆盖率（逐列 NaN 率，全表）")
    for table in bfw.TABLE.values():
        cols = [r[0] for r in con.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name='{table}'").fetchall()
            if r[0] not in ("date", "instrument", "year")]
        agg = ", ".join(f'count("{c}") AS c{i}' for i, c in enumerate(cols))
        row = con.execute(f"SELECT count(*) AS n, {agg} FROM {table}").df().iloc[0]
        cov = (row[[f"c{i}" for i in range(len(cols))]].to_numpy(dtype=float) / row["n"])
        check(f"{table} 逐列覆盖率合理", float(cov.min()) > 0.5,
              f"min {cov.min():.1%} / 中位 {np.median(cov):.1%} / max {cov.max():.1%}（{len(cols)} 列）")

    # ───────── ⑤ 视图 ─────────
    print("⑤ 视图")
    nd = con.execute("SELECT count(*) FROM factor_dir_1w").fetchone()[0]
    nv = con.execute("SELECT count(*) FROM factor_volstat_1w").fetchone()[0]
    ncomb = con.execute("SELECT count(*) FROM v_factor_1w").fetchone()[0]
    check("v_factor_1w 行数 == 两表（键一致）", ncomb == nd == nv, f"dir {nd:,} / volstat {nv:,} / combined {ncomb:,}")
    ncol = len(con.execute("DESCRIBE v_factor_1w").fetchall())
    check("v_factor_1w 列数 == 514", ncol == 514, f"{ncol} 列")
    # 用**最近一个信号日**整截面（老股都该有满窗口值）——比随机 LIMIT 更有意义
    last = con.execute("SELECT max(date) FROM v_factor_1w").fetchone()[0]
    sample = con.execute(f"SELECT * EXCLUDE(date, instrument) FROM v_factor_1w "
                         f"WHERE date = TIMESTAMP '{last}'").df()
    filled = sample.notna().mean(axis=1)
    check("v_factor_1w 最新信号日截面基本填满", float(filled.median()) > 0.9,
          f"{last}: {len(sample)} 只，行内非空比例 中位 {filled.median():.1%} / min {filled.min():.1%}")
    con.close()

    print("\n" + "=" * 70)
    if fails:
        print(f"{BAD} 未通过 {len(fails)} 项：{fails}")
        return 1
    print(f"{OK} 全部通过（{time.time()-t0:.0f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
