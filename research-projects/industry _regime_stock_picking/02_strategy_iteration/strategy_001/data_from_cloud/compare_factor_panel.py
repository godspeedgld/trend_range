"""对比【云端 vs 本地】的候选池 + 四因子值 —— 确定性口径（两边都是源头直出）。

用法：
  1. 云端跑 `cloud_code_with_panel_log.py` → 生成 `panel_log.parquet`（或 .csv.gz）
  2. 下载到本目录
  3. 跑本脚本

回答两个问题：
  ① **候选池差异**：同一信号日，两边的可投股票集合差在哪（云端有本地无 / 反之）
     → 若池差异大 ⇒ 过滤规则口径不同（云端 `amount>2e7` 是**当日**成交额，
        本地实现是 **20 日均额**；另有行业归属覆盖差异）
  ② **因子值差异**：两边共有的 (信号日, 股票) 上，四个因子的逐值差异
     → 若池一致但排名不同 ⇒ 因子计算口径不同（DAU `m_avg/m_lag` vs pandas rolling）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CACHE = ROOT / "research-projects/industry _regime_stock_picking/shared/_cache"
FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]

# 云端 ind_code(801xxx) → 本地行业中文名（与 shared/build_panel.py 的 SW801 一致）
SW801 = {
    "农林牧渔": "801010", "基础化工": "801030", "钢铁": "801040", "有色金属": "801050",
    "电子": "801080", "汽车": "801880", "家用电器": "801110", "食品饮料": "801120",
    "纺织服饰": "801130", "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160",
    "交通运输": "801170", "房地产": "801180", "商贸零售": "801200", "社会服务": "801210",
    "银行": "801780", "非银金融": "801790", "综合": "801230", "建筑材料": "801710",
    "建筑装饰": "801720", "电力设备": "801730", "机械设备": "801890", "国防军工": "801740",
    "计算机": "801750", "传媒": "801760", "通信": "801770", "煤炭": "801950",
    "石油石化": "801960", "环保": "801970", "美容护理": "801980",
}
CODE2NAME = {v: k for k, v in SW801.items()}


def load_cloud() -> pd.DataFrame:
    pq, gz = HERE / "panel_log.parquet", HERE / "panel_log.csv.gz"
    if pq.exists():
        df = pd.read_parquet(pq)
    elif gz.exists():
        df = pd.read_csv(gz, compression="gzip")
    else:
        raise SystemExit(f"缺少 panel_log.parquet / panel_log.csv.gz —— "
                         f"请先在云端跑 cloud_code_with_panel_log.py 并下载到 {HERE}")
    df = df.rename(columns={"instrument": "symbol"})
    df["date"] = pd.to_datetime(df["date"])
    df["ind_name"] = df["ind_code"].map(CODE2NAME)
    print(f"云端 panel: {len(df):,} 行 / {df.date.nunique()} 信号日 / {df.symbol.nunique()} 只")
    print(f"  行业映射命中: {df.ind_name.notna().mean():.1%}")
    return df


def main():
    cl = load_cloud()
    lo = pd.read_parquet(CACHE / "signal_panel_full.parquet")
    lo["date"] = pd.to_datetime(lo["date"])
    lo = lo.rename(columns={"vol_20": "vol_stock"})
    print(f"本地 panel: {len(lo):,} 行 / {lo.date.nunique()} 信号日 / {lo.symbol.nunique()} 只")

    # ── ① 候选池差异（按信号日）──
    cd = cl.groupby("date")["symbol"].apply(set)
    ld = lo.groupby("date")["symbol"].apply(set)
    common_days = sorted(set(cd.index) & set(ld.index))
    print(f"\n=== ① 候选池差异（可比信号日 {len(common_days)} 个）===")
    rows = []
    for d in common_days:
        c, l = cd[d], ld[d]
        rows.append({"date": d, "n_cloud": len(c), "n_local": len(l),
                     "both": len(c & l), "only_cloud": len(c - l), "only_local": len(l - c)})
    r = pd.DataFrame(rows)
    r["jaccard"] = r.both / (r.both + r.only_cloud + r.only_local)
    print(f"  云端口径候选数 中位 {r.n_cloud.median():.0f}；本地说 {r.n_local.median():.0f}")
    print(f"  交集/并集(Jaccard) 中位 {r.jaccard.median():.1%}")
    print(f"  云端独有 中位 {r.only_cloud.median():.0f} 只；本地独有 中位 {r.only_local.median():.0f} 只")
    print("\n  最近的 6 个信号日:")
    print(r.tail(6).round(3).to_string(index=False))

    # 抽一天看差异明细
    if common_days:
        d = common_days[-1]
        oc, ol = sorted(cd[d] - ld[d])[:12], sorted(ld[d] - cd[d])[:12]
        print(f"\n  样本 {str(d)[:10]}: 云端独有(前12) {oc}")
        print(f"                本地独有(前12) {ol}")

    # ── ② 因子值差异（共有的 (date,symbol)）──
    print(f"\n=== ② 因子值差异（两边共有的 信号日×股票）===")
    k = ["date", "symbol"]
    m = cl[k + FACTORS + ["ind_name"]].merge(
        lo[k + FACTORS], on=k, suffixes=("_c", "_l"), how="inner")
    print(f"  可比行: {len(m):,}")
    for f in FACTORS:
        a, b = m[f"{f}_c"].astype(float), m[f"{f}_l"].astype(float)
        ok = a.notna() & b.notna()
        if not ok.any():
            print(f"  {f:<12} 两边均非空 0 行（检查列名）"); continue
        diff = (a[ok] - b[ok])
        rel = (diff.abs() / b[ok].abs().replace(0, np.nan))
        print(f"  {f:<12} 可比 {int(ok.sum()):>7,}  |Δ|中位 {diff.abs().median():.3g}  "
              f"相对差中位 {rel.median():.2%}  完全相等 {float((diff.abs()<1e-9).mean()):.1%}")

    # ── ③ 行业内排名（两边各算，看选股为何不同）──
    print(f"\n=== ③ 行业内复合分排名对比（抽样 1 个信号日）===")
    if common_days:
        d = common_days[-1]
        for tag, df, indcol, symcol in [("云端", cl, "ind_name", "symbol"),
                                        ("本地", lo, "ind_name", "symbol")]:
            sub = df[df.date == d].copy()
            sub = sub.dropna(subset=FACTORS)
            sub["score"] = (sub.groupby(indcol, group_keys=False)
                            .apply(lambda g: pd.concat(
                                [g[f].mul(-1).rank(pct=True) for f in FACTORS], axis=1).mean(axis=1)))
            top = sub.sort_values("score", ascending=False).groupby(indcol).head(2)
            print(f"  [{tag}] {str(d)[:10]} top2/行业:")
            for ind, g in top.groupby(indcol):
                print(f"     {ind:<8} {list(g[symbol][:2])}")

    r.to_csv(HERE / "factor_panel_diff.csv", index=False, encoding="utf-8-sig")
    m.to_parquet(HERE / "factor_value_diff.parquet", index=False)
    print(f"\n→ factor_panel_diff.csv（池差异）/ factor_value_diff.parquet（因子逐值）")


if __name__ == "__main__":
    main()
