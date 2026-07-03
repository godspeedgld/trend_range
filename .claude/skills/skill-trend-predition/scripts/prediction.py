"""趋势预测 —— 模板与子工具（不做路由、不写死指标/特征/标签/模型）。

设计理念
--------
本模块只固化**流程骨架**与**可复用子工具**。具体内容（用哪些指标、评判规则、特征、
标签、模型种类）一律由**调用方根据用户输入动态生成代码**后，作为参数传入模板：

- **指标法模板** `predict_by_indicator(df, indicators=, rule=, label_fn=)`
    * indicators: 调用方算好的指标 dict（用 indicator.py 的函数构造）
    * rule: 调用方写的"评判函数"（把用户自然语言规则翻译成代码），输入指标 dict，输出逐 bar 预测标签
    * label_fn: 调用方给的 ground-truth 标签函数（如 indicator.trend_label）

- **决策树法模板** `predict_by_tree(df, features=, label_fn=, task=, ...)`
    * 固化流程：① 特征量纲统一 + 相关性剔除 ② 标签处理(分类/回归) ③ 滚动训练(切/训/验/汇总)
    * features / label_fn / task(分类0/1 or 回归连续) / models 由调用方给

- 子工具（写死、可独立复用）：`standardize` / `correlation_filter` / `rolling_train` / metrics。

路由（用哪条流程）由调用方（LLM/agent）决定，不在本模块。
"""

from __future__ import annotations

import warnings
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
)
from sklearn.preprocessing import StandardScaler

from scripts import indicator as ind

warnings.filterwarnings("ignore")


# ════════════════════════════════════════════════════════════
# 子工具（写死）
# ════════════════════════════════════════════════════════════
def standardize(X_train: pd.DataFrame, X_test: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """用训练集 fit StandardScaler，返回 (train_scaled, test_scaled)。避免泄漏。"""
    sc = StandardScaler().fit(X_train)
    return sc.transform(X_train), sc.transform(X_test)


def correlation_filter(
    X: pd.DataFrame, threshold: float = 0.9, reference: Optional[pd.DataFrame] = None
) -> tuple[list[str], list[tuple], pd.DataFrame]:
    """相关性剔除：|corr|>threshold 的成对特征剔除其一（保留在 `keep` 中靠前的）。

    reference: 计算相关性的子集（建议传初始训练段，避免泄漏）；None 则用全量 X。
    返回 (保留特征名, [(被剔除名, 原因)], 相关性矩阵)。
    """
    base = (reference if reference is not None else X).copy()
    corr = base.corr().abs()
    keep = list(X.columns)
    dropped = []
    upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
    for col in upper.columns:
        if col not in keep:
            continue
        hi = upper[col][upper[col] > threshold]
        for other in hi.index:
            if other in keep:
                keep.remove(other)
                dropped.append((other, f"与 {col} 相关性 {corr.loc[other, col]:.2f}>{threshold}，剔除冗余"))
    return keep, dropped, corr


def _make_model(name: str, task: str):
    name = name.lower()
    if task == "classification":
        if name == "rf":
            return RandomForestClassifier(n_estimators=200, max_depth=8, n_jobs=-1, random_state=0)
        if name == "xgb":
            from xgboost import XGBClassifier
            return XGBClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                                 subsample=0.9, colsample_bytree=0.9, n_jobs=-1,
                                 eval_metric="mlogloss", verbosity=0)
    else:  # regression
        if name == "rf":
            return RandomForestRegressor(n_estimators=200, max_depth=8, n_jobs=-1, random_state=0)
        if name == "xgb":
            from xgboost import XGBRegressor
            return XGBRegressor(n_estimators=300, max_depth=6, learning_rate=0.05,
                                subsample=0.9, colsample_bytree=0.9, n_jobs=-1, verbosity=0)
    raise ValueError(f"unknown model/task: {name}/{task}")


def _fit_predict(name: str, task: str, Xtr, ytr, Xte):
    """训练一个模型并预测 test；返回 (pred_array, fitted_model, importances_dict)。"""
    m = _make_model(name, task)
    if task == "classification":
        # XGBoost 需标签 0..k-1：对非连续标签做 remap
        if name == "xgb":
            classes = sorted(pd.Series(ytr).unique())
            mp = {c: i for i, c in enumerate(classes)}
            inv = {i: c for c, i in mp.items()}
            m.fit(Xtr, pd.Series(ytr).map(mp))
            pred = np.vectorize(inv.get)(m.predict(Xte))
        else:
            m.fit(Xtr, ytr)
            pred = m.predict(Xte)
    else:
        m.fit(Xtr, ytr)
        pred = m.predict(Xte)
    imp = dict(zip(getattr(Xtr, "columns", range(Xtr.shape[1])), getattr(m, "feature_importances_", [])))
    return pred, m, imp


def rolling_train(
    X: pd.DataFrame,
    y: pd.Series,
    *,
    task: str = "classification",
    min_train: int = 750,
    step: int = 100,
    test_block: int = 200,
    models: tuple = ("rf", "xgb"),
) -> dict:
    """滚动训练（expanding window）：每折 train[:t] → test[t:t+test_block]，滑 step。

    返回 {fold_metrics, oos_index, oos_pred:{model:Series}, oos_y, importances:{model:dict}}。
    """
    mask = X.notna().all(axis=1) & y.notna()
    X, y = X[mask].copy(), y[mask].copy()
    n = len(X)
    if n < min_train + test_block:  # 小样本降级
        min_train = max(int(n * 0.6), 30)
        test_block = max(n - min_train, 10)
        step = max(test_block, 1)

    fold_metrics, oos_idx = [], []
    oos_pred = {m: [] for m in models}
    importances = {m: {} for m in models}
    t, fid = min_train, 0
    while t + test_block <= n:
        tr_X, te_X = X.iloc[:t], X.iloc[t:t + test_block]
        tr_y, te_y = y.iloc[:t], y.iloc[t:t + test_block]
        tr_Xs, te_Xs = standardize(tr_X, te_X)
        fold = {"fold": fid, "train_end": int(t), "test_size": int(len(te_X))}
        last_imp = {}
        for name in models:
            try:
                pred, _m, imp = _fit_predict(name, task, tr_Xs, tr_y.values, te_Xs)
                oos_pred[name].extend(np.asarray(pred).tolist())
                last_imp[name] = imp
                if task == "classification":
                    fold[name] = _fold_cls(te_y.values, pred)
                else:
                    fold[name] = _fold_reg(te_y.values, pred)
            except Exception as e:  # 单个模型失败不影响其它
                fold[name] = {"error": str(e)}
        importances = {k: (v or importances[k]) for k, v in last_imp.items()}
        fold_metrics.append(fold)
        oos_idx.extend(te_X.index.tolist())
        fid += 1
        t += step

    oos_index = pd.Index(oos_idx)
    oos_pred_s = {m: pd.Series(preds, index=oos_index) for m, preds in oos_pred.items() if preds}
    return {
        "fold_metrics": fold_metrics,
        "oos_index": oos_index,
        "oos_pred": oos_pred_s,
        "oos_y": y.loc[oos_index] if len(oos_index) else pd.Series(dtype=float),
        "importances": importances,
        "setup": {"task": task, "min_train": min_train, "step": step, "test_block": test_block, "models": list(models)},
    }


# ════════════════════════════════════════════════════════════
# 指标法模板
# ════════════════════════════════════════════════════════════
def predict_by_indicator(
    df: pd.DataFrame,
    *,
    indicators: dict[str, pd.Series],
    rule: Callable[[dict[str, pd.Series]], pd.Series],
    label_fn: Callable[[pd.DataFrame], pd.Series],
    class_labels: Optional[list] = None,
    series_name: str = "series",
    output_dir: Optional[str] = None,
) -> dict:
    """指标法模板：indicators/rule/label_fn 由调用方提供。

    - indicators: 已算好的指标 dict（key=名，value=对齐 Series）
    - rule: 评判函数，输入 indicators dict → 返回逐 bar 预测 Series
    - label_fn: 输入 df → 返回 ground-truth Series
    - class_labels: 评估用的标签取值集合（默认从预测+真值推断，含 0）
    """
    pred = pd.Series(rule(indicators))
    pred.name = "pred"
    y_true = pd.Series(label_fn(df))
    y_true.name = "y_true"
    common = pred.index.intersection(y_true.index)
    pred, y_true = pred.loc[common], y_true.loc[common]
    valid = pred.notna() & y_true.notna()
    pred, y_true = pred[valid], y_true[valid]
    classes = class_labels or sorted(set(pred.unique()) | set(y_true.unique()))
    metrics = _cls_metrics(y_true, pred, classes)
    cm = confusion_matrix(y_true, pred, labels=classes) if len(classes) > 1 else None

    result = {
        "branch": "indicator",
        "indicators": indicators,
        "rule_src": _try_source(rule),
        "label_src": _try_source(label_fn),
        "pred": pred, "y_true": y_true,
        "metrics": metrics, "confusion": cm, "classes": classes,
        "distribution": {str(k): int(v) for k, v in pred.value_counts().items()},
        "n_valid": int(len(pred)),
        "series_name": series_name,
    }
    _maybe_report(result, df, output_dir, series_name)
    return result


# ════════════════════════════════════════════════════════════
# 决策树法模板
# ════════════════════════════════════════════════════════════
def predict_by_tree(
    df: pd.DataFrame,
    *,
    features: pd.DataFrame,
    label_fn: Callable[[pd.DataFrame], pd.Series],
    task: str = "classification",
    min_train: int = 750,
    step: int = 100,
    test_block: int = 200,
    models: tuple = ("rf", "xgb"),
    corr_threshold: float = 0.9,
    series_name: str = "series",
    output_dir: Optional[str] = None,
) -> dict:
    """决策树法流程模板：① 量纲统一+相关性剔除 ② 标签(分类0/1 or 回归连续) ③ 滚动训练。

    features / label_fn / task / models 由调用方提供；切分参数有默认。
    """
    y = pd.Series(label_fn(df))
    common = features.index.intersection(y.index)
    X, y = features.loc[common].copy(), y.loc[common].copy()
    # 相关性筛选（基于初始训练段，避免泄漏）
    init = X.iloc[:min(min_train, len(X))]
    keep, dropped, corr = correlation_filter(X, corr_threshold, reference=init)
    X_sel = X[keep]

    rt = rolling_train(X_sel, y, task=task, min_train=min_train, step=step,
                       test_block=test_block, models=models)

    oos_y = rt["oos_y"]
    oos = {}
    confusion = {}
    for name, preds in rt["oos_pred"].items():
        if task == "classification":
            classes = sorted(set(oos_y.unique()) | set(preds.unique()))
            oos[name] = _cls_metrics(oos_y, preds, classes)
            confusion[name] = confusion_matrix(oos_y, preds, labels=classes) if len(classes) > 1 else None
        else:
            oos[name] = _reg_metrics(oos_y, preds)

    pred = rt["oos_pred"][models[0]] if models[0] in rt["oos_pred"] else next(iter(rt["oos_pred"].values()))
    result = {
        "branch": "tree",
        "task": task,
        "features_all": list(features.columns),
        "features_selected": keep,
        "features_dropped": dropped,
        "corr": corr,
        "importances": rt["importances"],
        "fold_metrics": rt["fold_metrics"],
        "oos": oos,
        "confusion": confusion,
        "setup": rt["setup"],
        "pred": pred, "y_true": oos_y, "oos_index": rt["oos_index"],
        "n_features": len(keep), "n_samples": int(len(X)),
        "label_src": _try_source(label_fn),
        "series_name": series_name,
    }
    _maybe_report(result, df, output_dir, series_name)
    return result


# ════════════════════════════════════════════════════════════
# 默认 / 占位
# ════════════════════════════════════════════════════════════
def describe_data(df: pd.DataFrame, hint: str = "", *, series_name: str = "series",
                  output_dir: Optional[str] = None) -> dict:
    """数据描述报告（用户输入无法匹配具体流程时用）。"""
    from statsmodels.tsa.stattools import adfuller
    close, *_ = ind.extract_ohlcv(df)
    ret = np.log(close).diff().dropna()
    try:
        adf_p = float(adfuller(ret)[1])
    except Exception:
        adf_p = float("nan")
    result = {
        "branch": "default", "hint": hint, "columns": list(df.columns),
        "n_rows": int(len(df)),
        "close_summary": {"min": float(close.min()), "max": float(close.max()),
                          "first": float(close.iloc[0]), "last": float(close.iloc[-1])},
        "ret_summary": {"mean": float(ret.mean()), "std": float(ret.std())},
        "adf_pvalue": adf_p,
        "suggestion": "由调用方决定走 predict_by_indicator（指标法）或 predict_by_tree（决策树法）。",
        "series_name": series_name,
    }
    _maybe_report(result, df, output_dir, series_name)
    return result


def plan_markov() -> dict:
    """马尔可夫(HMM)法 —— 计划说明（待 hmmlearn 落地）。"""
    return {
        "branch": "markov", "status": "not_implemented",
        "plan": ("HMM 方案：观测=对数收益与 ATR 标准化；GaussianHMM(n_components=3) 拟合；"
                 "Viterbi 解码逐 bar 隐状态 → 映射「上行趋势/下行趋势/震荡」；与 label_fn 对齐评估。"
                 "依赖 hmmlearn（未安装）。"),
    }


def plan_dl() -> dict:
    """深度学习(LSTM/Transformer)法 —— 计划说明（待 torch 落地）。"""
    return {
        "branch": "dl", "status": "not_implemented",
        "plan": ("LSTM/Transformer 方案：特征序列按 lookback 切窗，监督标签=label_fn；"
                 "LSTM(seq→hidden→3类) 或轻量 Transformer Encoder；walk-forward 训练，"
                 "逐 bar 概率与分类，对齐评估。依赖 PyTorch（未安装）。"),
    }


# ════════════════════════════════════════════════════════════
# metrics / 小工具
# ════════════════════════════════════════════════════════════
def _cls_metrics(y_true, y_pred, classes) -> dict:
    yt, yp = np.asarray(y_true), np.asarray(y_pred)
    if len(classes) < 2:
        return {"accuracy": float(accuracy_score(yt, yp)) if len(yt) else float("nan")}
    p, r, f1, _ = precision_recall_fscore_support(yt, yp, labels=classes, average=None, zero_division=0)
    pw, rw, fw, _ = precision_recall_fscore_support(yt, yp, average="weighted", zero_division=0)
    return {
        "accuracy": float(accuracy_score(yt, yp)),
        "weighted": {"precision": float(pw), "recall": float(rw), "f1": float(fw)},
        "per_class": {str(c): {"precision": float(pi), "recall": float(ri), "f1": float(fi)}
                      for c, pi, ri, fi in zip(classes, p, r, f1)},
        "report_text": classification_report(yt, yp, labels=classes, zero_division=0),
    }


def _reg_metrics(y_true, y_pred) -> dict:
    yt, yp = np.asarray(y_true, float), np.asarray(y_pred, float)
    rmse = float(np.sqrt(mean_squared_error(yt, yp))) if len(yt) else float("nan")
    return {"rmse": rmse, "mae": float(mean_absolute_error(yt, yp)) if len(yt) else float("nan"),
            "r2": float(r2_score(yt, yp)) if len(yt) > 1 else float("nan")}


def _fold_cls(yt, yp) -> dict:
    pw, rw, fw, _ = precision_recall_fscore_support(yt, yp, average="weighted", zero_division=0)
    return {"accuracy": float(accuracy_score(yt, yp)), "f1_weighted": float(fw)}


def _fold_reg(yt, yp) -> dict:
    return {"rmse": float(np.sqrt(mean_squared_error(yt, yp))), "mae": float(mean_absolute_error(yt, yp))}


def _try_source(fn) -> str:
    try:
        import inspect
        return inspect.getsource(fn)
    except Exception:
        return "(无法获取源码)"


def _maybe_report(result: dict, df: pd.DataFrame, output_dir: Optional[str], series_name: str) -> None:
    if output_dir is not None:
        from scripts import reports
        rep = reports.generate_report(result, df, output_dir=output_dir, series_name=series_name)
        result.update(rep)


__all__ = [
    "predict_by_indicator", "predict_by_tree", "describe_data",
    "plan_markov", "plan_dl",
    "standardize", "correlation_filter", "rolling_train",
]
