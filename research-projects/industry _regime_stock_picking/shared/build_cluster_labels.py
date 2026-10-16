"""行业聚类标签（周频动态）—— strategy_009 的行业层输入件（新增文件，不改任何冻结件）。

来源：广发「重构行业轮动框架之十 · 行业聚类方法探讨」
      （提取件 research_report/行业轮动框架-广发/industry_clustering_guangfa_20211117_main.md）
      原文最终配置 = 凝聚层次聚类 + 余弦距离 + 全链 + 1 年窗（K=5）。

本件默认 **K=7**（analysis_020 的候选配置）：**偏离原文 K=5 的理由是"簇均衡度"这个事前结构标准**
（K=5 有 47% 的周出现"半壁簇"、最大簇占行业中位 48.4% ⇒ "同簇"语义失真；K=7 降至 38.7%/21.5%），
**不是按回测绩效挑的**。

口径（逐周、无前视）：
  对每个**调仓信号日 t**，取截至 t 的**前 WIN 个交易日**日收益率（31 行业 × WIN 矩阵），
  对行业（行）做 cosine 距离 + 全链的凝聚层次聚类 → 该周的簇标签。

用法：
    python build_cluster_labels.py                       # 默认 K=7 / complete / WIN=252
    CLUSTER_K=5 CLUSTER_WIN=126 python build_cluster_labels.py
产物：shared/_cache/industry_cluster_weekly_K{K}_{linkage}_w{WIN}.parquet
      （index = 信号日，columns = 行业名，值 = 簇 id）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from sklearn.cluster import AgglomerativeClustering

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
CACHE = HERE / "_cache"

K = int(os.environ.get("CLUSTER_K", 7))
LINKAGE = os.environ.get("CLUSTER_LINKAGE", "complete")
WIN = int(os.environ.get("CLUSTER_WIN", 252))


def out_path(K=K, linkage=LINKAGE, win=WIN) -> Path:
    return CACHE / f"industry_cluster_weekly_K{K}_{linkage}_w{win}.parquet"


def build_labels(K=K, linkage=LINKAGE, win=WIN,
                 panel_file="signal_panel_weekly_indpre.parquet") -> pd.DataFrame:
    """逐周聚类标签。信号日取自 panel（= 每周最后一个交易日），保证与策略同一天。"""
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    ind["date"] = pd.to_datetime(ind["date"])
    px = ind.pivot(index="date", columns="ind_name", values="close").sort_index()
    ret = px.pct_change()
    panel = pd.read_parquet(CACHE / panel_file)
    sig_dates = sorted(pd.to_datetime(panel["date"].unique()))
    dates = list(px.index)

    rows = {}
    for t in sig_dates:
        if t not in px.index:
            continue
        pos = dates.index(t)
        if pos + 1 < win:                       # 窗口未热（对齐陷阱 10 的纪律：显式跳过而非静默 NaN）
            continue
        X = ret.iloc[pos - win + 1: pos + 1].T.dropna()
        if X.shape[0] < 10:
            continue
        lb = AgglomerativeClustering(n_clusters=K, metric="cosine",
                                     linkage=linkage).fit_predict(X.values)
        rows[t] = pd.Series(lb, index=X.index)
    lab = pd.DataFrame(rows).T
    return lab


def main():
    lab = build_labels()
    p = out_path()
    lab.to_parquet(p)
    print(f"K={K} linkage={LINKAGE} win={WIN} → {lab.shape[0]} 周 × {lab.shape[1]} 行业 → {p}")
    mx = lab.apply(lambda r: r.value_counts().max() / lab.shape[1], axis=1)
    print(f"  簇均衡度：最大簇占比 中位 {mx.median():.1%} / P90 {mx.quantile(.9):.1%} / "
          f"半壁簇(≥50%)周占比 {(mx >= 0.5).mean():.1%}")


if __name__ == "__main__":
    main()
