"""对比【云端 vs 本地】每次调仓的行业 —— 确定性口径（两边都是直接输出，非反推）。

用法：
  1. 在云端跑 `cloud_code_with_industry_log.py`（或 .ipynb）
  2. 把输出里 INDUSTRY_LOG_BEGIN ~ INDUSTRY_LOG_END 之间的内容
     原样存成 `cloud_industry_log.csv`（含表头 signal_date,regime,exposure,top3）
  3. 跑本脚本

判据：
  · top3 集合完全相同 → 行业信号一致
  · 否则列出差异（云端独有 / 本地独有）
  另比 regime（momentum/reversal）与 exposure（1=满仓 0=空仓）。

注意：云端从 2015-01 起、本地从 2016-12 起（变盘指数预热需 460 bar，本地行业数据
2015-01 才开始）→ 只比**日期交集**。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load(path: Path, tag: str) -> pd.DataFrame:
    # ★ 必须用 utf-8-sig 读：云端 to_csv 写的是 utf-8-sig（带 BOM），
    #   用 utf-8 读会把 BOM 留在首个列名上（"﻿signal_date"）→ 表头检测失效、
    #   pandas 解析报 "Unknown datetime string format"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    # 容忍把 BEGIN/END 标记也一起复制进来
    lines = [l for l in lines if l.strip() and not l.startswith(("INDUSTRY_LOG_BEGIN",
                                                                 "INDUSTRY_LOG_END"))]
    if not lines:
        raise SystemExit(f"{path} 为空")
    if not lines[0].startswith("signal_date"):
        lines = ["signal_date,regime,exposure,top3"] + lines
    import io
    df = pd.read_csv(io.StringIO("\n".join(lines)))
    df["signal_date"] = pd.to_datetime(df["signal_date"])
    df["set3"] = df["top3"].fillna("").apply(lambda s: frozenset(s.split("|")) if s else frozenset())
    print(f"{tag}: {len(df)} 周  {df.signal_date.min().date()} ~ {df.signal_date.max().date()}")
    return df


def main():
    cloud_p = HERE / "industry_log.csv"
    if not cloud_p.exists():
        raise SystemExit(f"缺少 {cloud_p}\n请先在云端跑 cloud_code_with_industry_log.py，"
                         f"把 INDUSTRY_LOG_BEGIN~END 之间的输出存成该文件")
    cl = load(cloud_p, "云端")
    lo = load(HERE / "local_industry_log.csv", "本地")

    m = cl.merge(lo, on="signal_date", suffixes=("_c", "_l"), how="inner")
    print(f"\n可比周（交集）: {len(m)}  "
          f"{m.signal_date.min().date()} ~ {m.signal_date.max().date()}")
    if m.empty:
        raise SystemExit("交集为空——检查两端日期格式")

    m["same3"] = [a == b for a, b in zip(m.set3_c, m.set3_l)]
    m["same_regime"] = m.regime_c == m.regime_l
    m["same_exp"] = m.exposure_c == m.exposure_l

    print("\n" + "=" * 72)
    print(f"★ 行业 top3 完全一致 : {m.same3.mean():.1%}   （{int(m.same3.sum())}/{len(m)}）")
    print(f"  regime 一致        : {m.same_regime.mean():.1%}   （{int(m.same_regime.sum())}/{len(m)}）")
    print(f"  exposure 一致      : {m.same_exp.mean():.1%}   （{int(m.same_exp.sum())}/{len(m)}）")
    # 交集一致（云端 ⊆ 本地，容忍云端因流动性少买）
    sub = [c <= l for c, l in zip(m.set3_c, m.set3_l)]
    print(f"  云端 ⊆ 本地（宽松）: {sum(sub)/len(m):.1%}")

    m["year"] = m.signal_date.dt.year
    print("\n按年份（top3 完全一致率 / regime 一致率）:")
    g = m.groupby("year").agg(周数=("same3", "size"), top3一致=("same3", "mean"),
                              regime一致=("same_regime", "mean")).round(3)
    print(g.to_string())

    bad = m[~m.same3]
    print(f"\n=== top3 不一致的周（{len(bad)} 个，列前 20）===")
    for r in bad.head(20).itertuples():
        print(f"  {str(r.signal_date)[:10]}  云端 {sorted(r.set3_c)}")
        print(f"                       本地 {sorted(r.set3_l)}")

    if len(bad):
        only_c = bad[~bad.same_regime]
        print(f"\n其中 regime 也不同的: {len(only_c)} 周")
        for r in only_c.head(10).itertuples():
            print(f"  {str(r.signal_date)[:10]}  云端 {r.regime_c} / 本地 {r.regime_l}")

    m[["signal_date", "regime_c", "regime_l", "exposure_c", "exposure_l",
       "top3_c", "top3_l", "same3", "same_regime", "same_exp"]].to_csv(
        HERE / "industry_log_diff.csv", index=False, encoding="utf-8-sig")
    print(f"\n→ {HERE}/industry_log_diff.csv")


if __name__ == "__main__":
    main()
