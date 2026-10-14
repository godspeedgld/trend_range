"""构造「形态辅助」打分因子 → `factor_score_1d`（4 个分项 + 总分，小整数，方便看数值）。

## 是什么（用户 2026-10-14 定稿）
把 4 个指标各转成 **0~2 分**，**加总**成 0~8 的总分：

| 列 | 范围 | 分项 |
|---|---|---|
| `s_glue`     | 0~2 | ① 均线**粘合**（`dual_ema_gap_10w_compress` 绝对值小） |
| `s_converge` | 0~2 | ② 振幅**收敛**（`range_ratio_10w_rank` 低） |
| `s_break`    | 0~2 | ③ **突破 × 量能**（`breakout_10w_confirm_volume` 大） |
| `s_volume`   | 0~2 | ④ **非巨量**（`volume_ratio_5w_rank` 低） |
| **`total`**  | **0~8** | **四个分项直接加总** ← **副图只画这一条**（4 个分项留在表里，SQL 随时可拆开看） |

阈值按**全历史分位点**标定（P25/P50/P75/P95），不是拍脑袋：

| 指标 | P5 | 中位 | P95 | P99 | 定档 |
|---|---|---|---|---|---|
| ① `dual_ema_gap_10w_compress` | −0.050 | −0.001 | +0.046 | +0.086 | \|x\|≤0.01→2 / ≤0.04→1（极度集中在 0 附近） |
| ② `range_ratio_10w_rank` | −0.45 | 0.00 | +0.50 | +0.50 | x≤−0.15→2 / ≤0.15→1（rank 类，均匀铺满） |
| ③ `breakout_10w_confirm_volume` | −0.187 | −0.044 | +0.014 | +0.135 | x≥0.05→2 / x>0→1（**绝大多数是负的** = 平时没突破） |
| ④ `volume_ratio_5w_rank` | −0.45 | +0.05 | +0.50 | +0.50 | x≤0.0→2 / ≤0.3→1（rank 类，均匀铺满） |

## ★★ 两条设计边界（用户裁决，别再踩）
1. **不做任何"突破日"筛选/遮罩**。曾有 `quality = foundation.where(s_break>0)` 一版 —— **已删**
   （用户：完全是用了未来信息构造的因子；且它替使用者决定了"哪天算突破"——用的是库的
   `breakout` 口径=今收>前10日最高，而形态突破（W底颈线/三角形上沿）未必创10日新高）。
   **突破日由使用者自己判断，本表只提供分数。**
2. **`total` 是四项直接加总，不是"综合质量"**：实测 4 项与未来收益的方向**不一致**
   （`s_break` IC 为负 −0.032 追高衰竭；①②④ 为正），相加会互相抵消，且总分与突破率不单调
   （2~3分突破率 12% > 6分 3.5%）。**当多空观察索引用，别当因子信号**；要拆开看就用分项。

产物：`factor_score_1d/year=YYYY/part.parquet` + duckdb 视图（绝对路径，同仓库约定）
用法：python build_factor_score.py [--start 2015-01-01]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent
DB = ROOT / "bigquant_warehouse.duckdb"
TABLE = "factor_score_1d"
SUB = ["s_glue", "s_converge", "s_break", "s_volume"]
COLS = SUB + ["total"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2015-01-01")
    a = ap.parse_args()
    t0 = time.time()
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(f"""
        SELECT d.date, d.instrument,
               d.dual_ema_gap_10w_compress   AS x1,
               e.range_ratio_10w_rank        AS x2,
               d.breakout_10w_confirm_volume AS x3,
               v.volume_ratio_5w_rank        AS x4
        FROM factor_dir_1d d
        JOIN factor_ext_1d     e USING(date, instrument)
        JOIN factor_volstat_1d v USING(date, instrument)
        WHERE d.date >= TIMESTAMP '{a.start}'
    """).df()
    con.close()
    print(f"读入 {len(df):,} 行（{df['date'].min().date()}~{df['date'].max().date()}）")

    x1, x2, x3, x4 = (df[c].to_numpy(dtype=float) for c in ("x1", "x2", "x3", "x4"))
    out = df[["date", "instrument"]].copy()
    out["s_glue"]     = np.where(np.abs(x1) <= 0.01, 2, np.where(np.abs(x1) <= 0.04, 1, 0))
    out["s_converge"] = np.where(x2 <= -0.15, 2, np.where(x2 <= 0.15, 1, 0))
    out["s_break"]    = np.where(x3 >= 0.05, 2, np.where(x3 > 0, 1, 0))
    out["s_volume"]   = np.where(x4 <= 0.0, 2, np.where(x4 <= 0.3, 1, 0))
    nan = ~np.isfinite(x1) | ~np.isfinite(x2) | ~np.isfinite(x3) | ~np.isfinite(x4)
    for c in SUB:                                     # 窗口预热段（任一输入为空）→ 分项置空
        out.loc[nan, c] = np.nan
    out["total"] = out[SUB].sum(axis=1)               # ★ 四项直接加总（0~8）
    for c in COLS:
        out[c] = out[c].astype("Int8")                # 小整数，省空间（整表 ~12MB）

    print("\n=== 各分项分布（0/1/2 各占多少）===")
    for c in SUB:
        vc = out[c].value_counts(dropna=False).sort_index()
        print(f"  {c:<11} " + "  ".join(f"{k}:{v/len(out):.1%}" for k, v in vc.items()))
    print("\n=== 总分分布（0~8）===")
    for k, v in out["total"].value_counts(dropna=False).sort_index().items():
        print(f"  {str(k):>4} 分: {v:>12,}  {v/len(out):>8.3%}")

    out["year"] = pd.to_datetime(out["date"]).dt.year
    tdir = ROOT / TABLE
    if tdir.exists():
        import shutil
        if tdir.parent == ROOT:
            shutil.rmtree(tdir)
    for y, g in out.groupby("year"):
        p = tdir / f"year={int(y)}"
        p.mkdir(parents=True, exist_ok=True)
        g.drop(columns=["year"]).to_parquet(p / "part.parquet", index=False, compression="zstd")
    con = duckdb.connect(str(DB))
    con.execute(f"CREATE OR REPLACE VIEW {TABLE} AS SELECT * FROM read_parquet("
                f"'{tdir.resolve().as_posix()}/**/*.parquet', hive_partitioning=true)")
    n = con.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0]
    con.close()
    print(f"\n→ {TABLE}: {n:,} 行 × {len(COLS)+2} 列（{time.time()-t0:.0f}s）")
    print("  ★ 副图只画 total；4 个分项留在表里，SQL 随时拆开看")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
