"""analysis_012 更新一 — 三特征决策树预测收益率四分类。

特征（用户指定，t 日值，月度截面 z-score）：ma_turn20_z / ma_vol20_z / dividend_yield_z。
标签（按事件 ret 四类）：
  c1: ret < 0%
  c2: 0% <= ret < 5%
  c3: 5% <= ret < 20%
  c4: ret >= 20%
训练 2015-2020（实际 2017-04 起），测试 2021-至今。
模型：DecisionTree（深度扫描 d=3/4/5 + class_weight 平衡对照），输出：
  混淆矩阵、总体正确率、各类 precision/recall/F1；
  二值化指标（预测>0% vs 实际>0%）：正确率/查准率/查全率/F1/AUC；
  与"全预测为最常见类"基线对照。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

FEATS = ["ma_turn20_z", "ma_vol20_z", "dividend_yield_ratio_z"]
TRAIN_END = "2020-12-31"


def label_of(ret: float) -> int:
    if ret < 0:
        return 1
    if ret < 0.05:
        return 2
    if ret < 0.20:
        return 3
    return 4


def main():
    fx = pd.read_parquet(HERE / "features.parquet")
    fx = fx.dropna(subset=FEATS).copy()
    fx["label"] = fx["ret"].apply(label_of)
    tr = fx[fx["date"] <= TRAIN_END]
    te = fx[fx["date"] > TRAIN_END]
    print(f"训练 {len(tr)}（{tr['date'].min().date()}~{tr['date'].max().date()}） | "
          f"测试 {len(te)}（{te['date'].min().date()}~{te['date'].max().date()}）")
    print("训练标签分布:", tr["label"].value_counts(normalize=True).round(3).to_dict())
    print("测试标签分布:", te["label"].value_counts(normalize=True).round(3).to_dict())

    Xtr, ytr = tr[FEATS], tr["label"].values
    Xte, yte = te[FEATS], te["label"].values

    from sklearn.tree import DecisionTreeClassifier
    from sklearn.metrics import (classification_report, confusion_matrix,
                                 precision_score, recall_score, f1_score,
                                 accuracy_score, roc_auc_score)

    results = {}
    for depth in (3, 4, 5):
        for bal in (None, "balanced"):
            m = DecisionTreeClassifier(max_depth=depth, class_weight=bal,
                                       random_state=42, min_samples_leaf=30)
            m.fit(Xtr, ytr)
            yp = m.predict(Xte)
            acc = accuracy_score(yte, yp)
            # 二值化：>0% 即 label∈{2,3,4}
            yte_bin = (yte >= 2).astype(int)
            yp_bin = (yp >= 2).astype(int)
            prec = precision_score(yte_bin, yp_bin, zero_division=0)
            rec = recall_score(yte_bin, yp_bin, zero_division=0)
            f1 = f1_score(yte_bin, yp_bin, zero_division=0)
            prob = m.predict_proba(Xte)[:, 1:].sum(axis=1)   # P(label>=2)
            auc = roc_auc_score(yte_bin, prob)
            name = f"depth={depth}" + ("+bal" if bal else "")
            results[name] = {"acc4": acc, "bin_acc": accuracy_score(yte_bin, yp_bin),
                             "precision": prec, "recall": rec, "f1": f1, "auc": auc, "model": m}
            print(f"{name:14s} 四类正确率 {acc:.3f} | >0%二值: 正确率 {accuracy_score(yte_bin, yp_bin):.3f} "
                  f"查准 {prec:.3f} 查全 {rec:.3f} F1 {f1:.3f} AUC {auc:.3f}")

    # 基线：全预测最常见类
    base = yte.mean() and pd.Series(yte).value_counts().idxmax()
    yp_base = np.full_like(yte, base)
    base_bin = np.ones(len(yte), dtype=int) if base >= 2 else np.zeros(len(yte), dtype=int)
    yte_bin = (yte >= 2).astype(int)
    print(f"\n基线（全预测类{base}）: 四类正确率 {accuracy_score(yte, yp_base):.3f} | "
          f">0% 二值正确率 {accuracy_score(yte_bin, base_bin):.3f} "
          f"查全 {recall_score(yte_bin, base_bin, zero_division=0):.3f} "
          f"查准 {precision_score(yte_bin, base_bin, zero_division=0):.3f}")

    # 最优（按 AUC）模型详细报告 + 混淆矩阵 + 树规则
    best_name = max(results, key=lambda k: results[k]["auc"])
    best = results[best_name]
    print(f"\n═══ 最优（{best_name}，AUC {best['auc']:.3f}）详细 ═══")
    m = best["model"]
    yp = m.predict(Xte)
    print(classification_report(yte, yp, target_names=["c1<0%", "c2 0-5%", "c3 5-20%", "c4>20%"]))
    cm = confusion_matrix(yte, yp)
    print("混淆矩阵（行=实际 c1..c4，列=预测）:")
    print(pd.DataFrame(cm, index=[f"真c{i}" for i in range(1, 5)],
                      columns=[f"预c{i}" for i in range(1, 5)]).to_string())
    from sklearn.tree import export_text
    print("\n树规则（前 22 行）:")
    print("\n".join(export_text(m, feature_names=[f.split("_z")[0] for f in FEATS],
                                max_depth=10).splitlines()[:22]))

    # 训练段自评（过拟合检查）
    ytr_p = m.predict(Xtr)
    print(f"\n训练段四类正确率 {accuracy_score(ytr, ytr_p):.3f} vs 测试 "
          f"{accuracy_score(yte, yp):.3f} → 差距 = 过拟合程度")

    # 落盘预测明细（供可视化/后续）
    out = te.copy()
    out["pred_label"] = yp
    out["pred_prob_ge0"] = prob if (prob := m.predict_proba(Xte)[:, 1:].sum(axis=1)) is not None else np.nan
    out.to_parquet(HERE / "tree_test_pred.parquet", index=False)
    pd.DataFrame(results).drop(index="model").T.to_csv(
        HERE / "tree_results.csv", encoding="utf-8-sig")
    print("\n写出 tree_test_pred.parquet / tree_results.csv")
    return results


if __name__ == "__main__":
    main()
