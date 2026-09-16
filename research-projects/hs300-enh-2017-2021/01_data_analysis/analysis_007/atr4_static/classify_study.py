"""更新八 — 4.1 degree×decile 组合 + 4.2 特征区分研究。

y = 成功(1)/失败(0)。全部特征用信号日 ≤t 数据，无未来。
特征：degree、decile(过去252日)、runup5/runup20(前5/20日涨幅)、pctile60(60日分位)、
      dist_line(close_sig/line−1 突破强度)、range_pos(20日区间位置)。
检验：单特征 IC(spearman)+十分位单调；LR / 决策树 / 随机森林 5 折 AUC。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
A7 = HERE.parent
PROJ = A7.parents[1]

det = pd.read_parquet(HERE / "detail_atr4static.parquet")
det["date"] = pd.to_datetime(det["date"])
dec = det[det["result"].isin(["success", "fail"])].copy()
dec["y"] = (dec["result"] == "success").astype(int)

panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
g_close = {s: g.set_index("date")["close"].astype(float) for s, g in panel.groupby("symbol")}

feats = {k: [] for k in ["degree", "decile", "runup5", "runup20", "pctile60",
                         "dist_line", "range_pos"]}
for r in dec.itertuples():
    cser = g_close.get(r.symbol)
    d = pd.Timestamp(r.date)
    if cser is None or d not in cser.index:
        for k in feats:
            feats[k].append(np.nan)
        continue
    i = cser.index.get_loc(d)
    c = float(cser.iloc[i])
    c5 = float(cser.iloc[i - 5]) if i >= 5 else np.nan
    c20 = float(cser.iloc[i - 20]) if i >= 20 else np.nan
    win = cser.iloc[max(0, i - 251):i + 1]
    hi20 = float(cser.iloc[max(0, i - 19):i + 1].max())
    lo20 = float(cser.iloc[max(0, i - 19):i + 1].min())
    feats["degree"].append(int(r.degree))
    feats["decile"].append(min(int(float((win < c).mean()) * 10) + 1, 10))
    feats["runup5"].append(c / c5 - 1 if not np.isnan(c5) else np.nan)
    feats["runup20"].append(c / c20 - 1 if not np.isnan(c20) else np.nan)
    tail60 = win.tail(60)
    feats["pctile60"].append(float((tail60 < c).mean()) if len(tail60) >= 30 else np.nan)
    feats["dist_line"].append(r.close_sig / r.line - 1 if r.line else np.nan)
    feats["range_pos"].append((c - lo20) / (hi20 - lo20) if hi20 > lo20 else np.nan)
fx = pd.DataFrame(feats, index=dec.index)
# dec 已有 degree；fx 重算的 decile 更准（含新 252 窗口径）；去掉 dec 的重复列保留 fx 版本
dec2 = pd.concat([dec.drop(columns=["degree"]).reset_index(drop=True),
                  fx.reset_index(drop=True)], axis=1)
dec2.to_parquet(HERE / "classify_input.parquet", index=False)

print(f"═══ 4.1 degree×decile 组合 胜率%（样本）═══")
dec2["deg_c"] = dec2["degree"].apply(lambda d: "2" if d == 2 else "3-5" if d <= 5
                                     else "6-11" if d <= 11 else "12+")
dec2["dcl_c"] = dec2["decile"].apply(lambda x: "1-3" if x <= 3 else "4-6" if x <= 6
                                     else "7-9" if x <= 9 else "10")
pv = dec2.pivot_table(index="deg_c", columns="dcl_c", values="y",
                      aggfunc=["mean", "count"])
cols = ["1-3", "4-6", "7-9", "10"]
print("胜率：\n", pv["mean"].reindex(["2", "3-5", "6-11", "12+"])[cols].round(3).to_string())
print("样本：\n", pv["count"].reindex(["2", "3-5", "6-11", "12+"])[cols].astype(int).to_string())

print(f"\n═══ 4.2 单特征 IC（y spearman）+ 十分位单调 ═══")
from scipy.stats import spearmanr
feat_cols = ["degree", "decile", "runup5", "runup20", "pctile60", "dist_line", "range_pos"]
for f in feat_cols:
    s = dec2[[f, "y"]].dropna()
    if len(s) < 500:
        print(f"{f:11s} n={len(s)} 不足"); continue
    ic, p = spearmanr(s[f], s["y"])
    try:
        q = pd.qcut(s[f], 10, labels=False, duplicates="drop")
        ym = s.groupby(q)["y"].mean()
        up = ym.iloc[-1] >= ym.iloc[0]
        mono = (np.diff(ym) >= 0 if up else np.diff(ym) <= 0).mean()
        print(f"{f:11s} IC={ic:+.3f}(p={p:.3f}) | 十档胜率[{ym.min():.2f}~{ym.max():.2f}] "
              f"单调{mono*100:.0f}% n={len(s)}")
    except Exception:
        print(f"{f:11s} IC={ic:+.3f}(p={p:.3f}) n={len(s)}")

print(f"\n═══ 模型 5 折 AUC ═══")
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

X = dec2[feat_cols].replace([np.inf, -np.inf], np.nan)
X = X.fillna(X.median())
y = dec2["y"].values
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
specs = [("Logistic", lambda: LogisticRegression(max_iter=1000), True),
         ("DecisionTree(d3)", lambda: DecisionTreeClassifier(max_depth=3, random_state=42), False),
         ("RandomForest(d4)", lambda: RandomForestClassifier(n_estimators=100, max_depth=4,
                                                             random_state=42), False)]
for name, make, use_scaler in specs:
    aucs = []
    for tr, te in skf.split(X, y):
        model = make()
        if use_scaler:
            sc = StandardScaler().fit(X.iloc[tr])
            Xtr, Xte = sc.transform(X.iloc[tr]), sc.transform(X.iloc[te])
        else:
            Xtr, Xte = X.iloc[tr], X.iloc[te]
        model.fit(Xtr, y[tr])
        aucs.append(roc_auc_score(y[te], model.predict_proba(Xte)[:, 1]))
    print(f"{name:20s} AUC={np.mean(aucs):.3f}±{np.std(aucs):.3f}")
