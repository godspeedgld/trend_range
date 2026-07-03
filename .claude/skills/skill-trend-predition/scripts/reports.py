"""按分支组装趋势预测报告（中文，结论先行）+ 出图。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR_DEFAULT = SKILL_ROOT / "reports"


def _fmt(v: Any, n: int = 4) -> str:
    if isinstance(v, float):
        if pd.isna(v):
            return "nan"
        return f"{v:.{n}f}"
    return str(v).replace("|", "\\|").replace("\n", "<br>")


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(name).strip())
    return stem.strip("._-") or "series"


def _md_table(rows: list[list], header: list[str]) -> str:
    out = ["| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in rows:
        out.append("| " + " | ".join(_fmt(x) for x in r) + " |")
    return "\n".join(out)


def _plot(fn, path, **kw) -> Optional[str]:
    try:
        return fn(path=str(path), **kw)
    except Exception as e:  # pragma: no cover - 绘图失败不中断报告
        return f"(绘图失败: {e})"


def generate_report(
    result: dict,
    df: pd.DataFrame,
    *,
    output_dir: Optional[str] = None,
    series_name: str = "series",
) -> dict:
    """根据 result['branch'] 生成对应 Markdown + 图。"""
    out_dir = Path(output_dir) if output_dir else REPORT_DIR_DEFAULT / _safe_stem(series_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(series_name)
    branch = result.get("branch", "default")
    plots: dict[str, Optional[str]] = {}

    if branch == "indicator":
        md, plots = _report_indicator(result, df, out_dir, stem)
    elif branch == "tree":
        md, plots = _report_tree(result, df, out_dir, stem)
    elif branch in ("markov", "dl"):
        md = _report_placeholder(result)
    else:
        md = _report_default(result)

    md_path = out_dir / f"{stem}_trend_report.md"
    md_path.write_text(md, encoding="utf-8")
    return {"markdown": md, "markdown_path": str(md_path),
            "plots": {k: v for k, v in plots.items() if v}}


# ────────────────────────────────────────────────────────────
# 指标法报告
# ────────────────────────────────────────────────────────────
def _report_indicator(result, df, out_dir, stem) -> tuple[str, dict]:
    from scripts import viz
    from scripts import indicator as ind
    close, *_ = ind.extract_ohlcv(df)
    pred = result["pred"]
    metrics = result["metrics"]
    plots: dict[str, Optional[str]] = {}
    p_close = _plot(viz.plot_close_colored, out_dir / f"{stem}_close.png",
                    close=close.reindex(pred.index), labels=pred, title=f"{stem} 指标法判定")
    p_kline = _plot(viz.plot_kline_colored, out_dir / f"{stem}_kline.png",
                    df=df.reindex(pred.index) if df is not None else None, labels=pred,
                    title=f"{stem} K线（近段）")
    cm = result.get("confusion")
    p_cm = _plot(viz.plot_confusion, out_dir / f"{stem}_confusion.png",
                 cm=cm, classes=result.get("classes", [])) if cm is not None else None
    plots = {"close": p_close, "kline": p_kline, "confusion": p_cm}

    acc = metrics.get("accuracy", float("nan"))
    w = metrics.get("weighted", {})
    pc = metrics.get("per_class", {})
    parts = [f"# {stem} 趋势预测报告（指标法）", "",
             "## 一句话结论", "",
             f"基于用户给定的指标评判规则，对 {result.get('n_valid', 0)} 个交易日判定趋势/震荡；"
             f"对齐前瞻标签评估：**准确率 = {_fmt(acc)}**，加权 F1 = {_fmt(w.get('f1'))}。", "",
             "## 1. 评判规则（调用方翻译生成的代码）", "", "```python", result.get("rule_src", "").strip(), "```", "",
             "## 2. 用到的指标", "",
             ", ".join(f"`{k}`" for k in result.get("indicators", {}).keys()) or "_无_", "", ]

    parts += ["## 3. 预测分布", "",
              _md_table([[k, v] for k, v in result.get("distribution", {}).items()], ["预测类别", "数量"]), "",
              "## 4. 评估指标", "",
              _md_table([["accuracy", acc],
                         ["precision (weighted)", w.get("precision")],
                         ["recall (weighted)", w.get("recall")],
                         ["f1 (weighted)", w.get("f1")]], ["指标", "值"]), ""]
    if pc:
        parts += ["### 逐类（per-class）", "",
                  _md_table([[c, m["precision"], m["recall"], m["f1"]] for c, m in pc.items()],
                            ["类别", "precision", "recall", "f1"]), ""]
    parts += ["### 完整 classification_report", "", "```", metrics.get("report_text", ""), "```", ""]
    if p_cm:
        parts += [f"![混淆矩阵]({os.path.basename(p_cm)})", ""]
    if p_close:
        parts += [f"![close 着色]({os.path.basename(p_close)})", ""]
    if p_kline and "(绘图失败" not in str(p_kline):
        parts += [f"![K线着色]({os.path.basename(p_kline)})", ""]
    parts += ["## 5. 注意", "",
              "- 指标/规则/标签均由调用方根据用户输入动态生成；本报告由指标法模板渲染。",
              "- 评估依赖前瞻 ground-truth 标签，仅用于回测，不构成下单依据。", ""]
    return "\n".join(parts), plots


# ────────────────────────────────────────────────────────────
# 决策树法报告
# ────────────────────────────────────────────────────────────
def _report_tree(result, df, out_dir, stem) -> tuple[str, dict]:
    from scripts import viz
    from scripts import indicator as ind
    close, *_ = ind.extract_ohlcv(df)
    pred = result["pred"]
    setup = result["setup"]
    task = result.get("task", "classification")
    plots: dict[str, Optional[str]] = {}
    p_corr = _plot(viz.plot_corr_heatmap, out_dir / f"{stem}_corr.png", corr=result["corr"])
    imp = result.get("importances") or {}
    imp0 = next((v for v in imp.values() if v), {})
    p_imp = _plot(viz.plot_feature_importance, out_dir / f"{stem}_importance.png", importances=imp0) if imp0 else None
    p_close = _plot(viz.plot_close_colored, out_dir / f"{stem}_close.png",
                    close=close.reindex(pred.index), labels=pred, title=f"{stem} 决策树 OOS 判定")
    plots = {"corr": p_corr, "importance": p_imp, "close": p_close}
    cm_plots: dict[str, str] = {}
    if task == "classification":
        for name, cm in result.get("confusion", {}).items():
            if cm is not None:
                p = _plot(viz.plot_confusion, out_dir / f"{stem}_confusion_{name}.png",
                          cm=cm, classes=sorted(set(result["y_true"].unique()) | set(pred.unique())),
                          title=f"混淆矩阵 ({name})")
                if p:
                    cm_plots[name] = p
    plots.update(cm_plots)

    oos = result.get("oos", {})
    if task == "classification":
        oos_rows = [[name, m.get("accuracy"), m.get("weighted", {}).get("precision"),
                     m.get("weighted", {}).get("recall"), m.get("weighted", {}).get("f1")]
                    for name, m in oos.items()]
        oos_header = ["模型", "accuracy", "precision(w)", "recall(w)", "f1(w)"]
    else:
        oos_rows = [[name, m.get("rmse"), m.get("mae"), m.get("r2")] for name, m in oos.items()]
        oos_header = ["模型", "RMSE", "MAE", "R²"]

    fold_rows = []
    folds = result.get("fold_metrics", [])
    for f in folds[-6:]:  # 最近若干折
        row = [f.get("fold"), f.get("train_end"), f.get("test_size")]
        for name in setup["models"]:
            v = f.get(name, {})
            if task == "classification":
                row.append(v.get("accuracy") if isinstance(v, dict) else v)
            else:
                row.append(v.get("rmse") if isinstance(v, dict) else v)
        fold_rows.append(row)
    fold_header = ["fold", "train_end", "test_size"] + [f"{m}({'acc' if task=='classification' else 'rmse'})" for m in setup["models"]]

    parts = [f"# {stem} 趋势预测报告（决策树法·{task}）", "",
             "## 一句话结论", "",
             f"特征 {result.get('n_features')} 个（剔除 {len(result.get('features_dropped', []))} 个高相关）→ "
             f"滚动训练 {setup['models']}，OOS 指标："
             + ("；".join(f"{k}={_fmt(v)}" for k, v in list(oos.items())[0][1].items()) if oos else "—"), "",
             "## 1. 特征工程", "",
             f"**保留特征（{result.get('n_features')}）**：" + ", ".join(f"`{f}`" for f in result.get("features_selected", [])), "",
             "**剔除特征（高相关>0.9）**：",
             _md_table([[d, r] for d, r in result.get("features_dropped", [])], ["被剔除", "原因"]) or "_无_", ""]
    if p_corr:
        parts += [f"![相关性热图]({os.path.basename(p_corr)})", ""]
    if p_imp:
        parts += [f"![特征重要性]({os.path.basename(p_imp)})", ""]

    parts += ["## 2. 滚动训练设置", "",
              _md_table([[setup.get("task"), setup.get("min_train"), setup.get("step"),
                          setup.get("test_block"), ", ".join(setup.get("models", []))]],
                        ["任务", "min_train", "step", "test_block", "models"]), "",
              "### 各折（最近）", "", _md_table(fold_rows, fold_header), "",
              "## 3. 样本外(OOS)汇总", "", _md_table(oos_rows, oos_header), ""]
    for name, p in cm_plots.items():
        parts += [f"![混淆矩阵-{name}]({os.path.basename(p)})", ""]
    if p_close:
        parts += [f"![OOS 判定]({os.path.basename(p_close)})", ""]
    parts += ["## 4. 标签函数（调用方提供）", "", "```python", result.get("label_src", "").strip(), "```", "",
              "## 5. 注意", "",
              "- 特征/标签/模型均由调用方根据用户输入动态生成；本报告由决策树法模板渲染。",
              "- 标准化按折 fit（无泄漏）；相关性筛选用初始训练段。",
              "- 仅用于回测，不构成下单依据。", ""]
    return "\n".join(parts), plots


# ────────────────────────────────────────────────────────────
# 占位 / 默认
# ────────────────────────────────────────────────────────────
def _report_placeholder(result) -> str:
    branch = result.get("branch")
    name = {"markov": "马尔可夫(HMM)", "dl": "深度学习(LSTM/Transformer)"}.get(branch, branch)
    return (f"# 趋势预测报告（{name}法 · 占位）\n\n"
            f"> 状态：`{result.get('status','not_implemented')}`\n\n"
            f"## 计划方案\n\n{result.get('plan','')}\n")


def _report_default(result) -> str:
    cs = result.get("close_summary", {})
    rs = result.get("ret_summary", {})
    parts = [f"# {result.get('series_name','series')} 数据描述报告", "",
             f"> 提示：未匹配到具体预测流程（hint={result.get('hint','')}）。", "",
             "## 基本信息", "",
             _md_table([["列", ", ".join(result.get("columns", []))],
                        ["行数", result.get("n_rows")],
                        ["ADF p值", result.get("adf_pvalue")]], ["项", "值"]), "",
             "## close 摘要", "",
             _md_table([["min", cs.get("min")], ["max", cs.get("max")],
                        ["first", cs.get("first")], ["last", cs.get("last")]], ["项", "值"]), "",
             "## 对数收益摘要", "",
             _md_table([["mean", rs.get("mean")], ["std", rs.get("std")]], ["项", "值"]), "",
             "## 建议", "", result.get("suggestion", ""), ""]
    return "\n".join(parts)


__all__ = ["generate_report"]
