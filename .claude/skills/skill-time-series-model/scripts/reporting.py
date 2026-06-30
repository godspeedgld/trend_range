"""报告脚本：检测 → 建模 → Markdown 报告 + 预测图。

主入口 generate_model_report(returns)：
  1) ADF / Ljung-Box / ARCH-LM 三项检测（结果 + ACF/平方收益图）
  2) 根据检测结果选模型并拟合（ARMA / AR+GARCH / ARMA+GARCH / 无需建模）
  3) 最优阶数、参数估计、建模后 Ljung-Box 检测结果与结论
  4) 原始数据 + 样本内拟合 + 向前预测 同图，写入报告
报告与图落到 skill 的 reports/ 子目录。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.diagnostics import DiagnosticReport, run_diagnostics
from scripts.modeling import FitSummary, fit_model

SKILL_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR_DEFAULT = SKILL_ROOT / "reports"


# ────────────────────────────────────────────────────────────
# 文本辅助
# ────────────────────────────────────────────────────────────
def _fmt(v: Any) -> str:
    if isinstance(v, float):
        if pd.isna(v):
            return "nan"
        return f"{v:.4f}"
    return str(v).replace("|", "\\|").replace("\n", "<br>")


def _df_md(df: pd.DataFrame, index_name: str = "") -> str:
    if df is None or df.empty:
        return "_无数据_。"
    header_cols = [str(c) for c in df.columns]
    head = "| " + " | ".join([index_name or "index", *header_cols]) + " |"
    sep = "| " + " | ".join("---" for _ in range(len(header_cols) + 1)) + " |"
    lines = [head, sep]
    for idx, row in df.iterrows():
        lines.append("| " + " | ".join([_fmt(idx), *(_fmt(x) for x in row.values)]) + " |")
    return "\n".join(lines)


def _kv_md(items: dict) -> str:
    lines = ["| 指标 | 值 |", "|---|---:|"]
    for k, v in items.items():
        lines.append(f"| `{k}` | {_fmt(v)} |")
    return "\n".join(lines)


def _params_md(params: dict) -> str:
    if not params:
        return "_无参数_。"
    return _df_md(pd.DataFrame({"参数值": list(params.values())}, index=list(params.keys())), "参数")


def _order_str(order) -> str:
    return str(order)


def _safe_stem(name: str) -> str:
    stem = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(name).strip())
    return stem.strip("._-") or "series"


# ────────────────────────────────────────────────────────────
# 绘图：检测图 + 预测图
# ────────────────────────────────────────────────────────────
def _plot_diagnostics(returns: pd.Series, path: Path) -> str:
    """ACF + 收益率平方 收益率走势三联图（直观展示自相关与波动聚集）。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from statsmodels.graphics.tsaplots import plot_acf

    r = pd.Series(returns).dropna().astype(float)
    fig, axes = plt.subplots(3, 1, figsize=(11, 9))
    axes[0].plot(r.values, color="#2c3e50", linewidth=0.7)
    axes[0].set_title("returns (input series)")
    axes[0].grid(alpha=0.3)

    plot_acf(r, lags=30, ax=axes[1], title="ACF (autocorrelation)")
    axes[1].grid(alpha=0.3)

    axes[2].plot((r ** 2).values, color="#c0392b", linewidth=0.7)
    axes[2].set_title("squared returns (volatility clustering / ARCH effect)")
    axes[2].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def _plot_prediction(returns: pd.Series, fit: FitSummary, path: Path) -> str:
    """原始序列 + 样本内拟合 + 向前预测 同图。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y = pd.Series(returns).dropna().astype(float).reset_index(drop=True)
    fitted = fit.fitted.dropna().reset_index(drop=True) if fit.fitted is not None else pd.Series(dtype=float)
    fc = fit.forecast_mean.reset_index(drop=True) if len(fit.forecast_mean) else pd.Series(dtype=float)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(y.index, y.values, label="actual", color="#34495e", linewidth=1.0)
    if len(fitted):
        ax.plot(fitted.index, fitted.values, label="in-sample fit", color="#27ae60", linewidth=1.0, alpha=0.85)
    if len(fc):
        start = len(y)
        ax.plot(range(start, start + len(fc)), fc.values, label=f"forecast ({len(fc)} steps)", color="#e74c3c", linewidth=1.5)
    ax.set_title(f"{fit.model_type} {_order_str(fit.order)}  fit & forecast")
    ax.legend(fontsize="small")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return str(path)


# ────────────────────────────────────────────────────────────
# 报告组装
# ────────────────────────────────────────────────────────────
def _one_sentence(diag: DiagnosticReport, fit: FitSummary | None) -> str:
    if fit is None:
        return "该收益率序列无可检测的自相关与波动聚集，未建模拟合。"
    verdict = "充分" if fit.passed else "尚不充分"
    return f"检测建议 `{fit.model_type}`；最优阶数 {_order_str(fit.order)}；建模拟合{verdict}（{fit.reason}）。"


def _build_markdown(
    *,
    title: str,
    series_name: str,
    diag: DiagnosticReport,
    fit: FitSummary | None,
    diag_img: str,
    pred_img: str | None,
) -> str:
    parts: list[str] = [f"# {title}", "", "## 一句话结论", "", _one_sentence(diag, fit), ""]

    # ── 三项检测 ──
    parts += [
        "## 1. 检测结果",
        "",
        f"- **建议模型**：`{diag.recommendation}` — {diag.reason}",
        "",
        "### 1.1 ADF 平稳性",
        "",
        _kv_md(
            {
                "statistic": diag.adf.statistic,
                "pvalue": diag.adf.pvalue,
                "used_lag": diag.adf.used_lag,
                "is_stationary (5%)": diag.adf.is_stationary,
            }
        ),
        "",
        "### 1.2 Ljung-Box 自相关",
        "",
        _df_md(diag.ljung_box.table.rename(columns={"lb_stat": "统计量", "lb_pvalue": "p 值"}), "滞后阶"),
        "",
        f"> 存在自相关：`{diag.ljung_box.has_autocorrelation}`",
        "",
        "### 1.3 ARCH-LM 异方差效应",
        "",
        _df_md(
            pd.DataFrame({"统计量": diag.arch_lm.statistics, "p 值": diag.arch_lm.pvalues},
                         index=pd.Index(diag.arch_lm.lags, name="滞后阶")),
        ),
        "",
        f"> 存在 ARCH 效应：`{diag.arch_lm.has_arch_effect}`",
        "",
        "### 1.4 方差比检验（随机游走，Lo-MacKinlay）",
        "",
        _df_md(
            pd.DataFrame({"VR(q)": diag.variance_ratio.vr, "z 统计量": diag.variance_ratio.z,
                          "p 值": diag.variance_ratio.pvalues},
                         index=pd.Index(diag.variance_ratio.lags, name="持有期 q")),
        ),
        "",
        f"> 未拒绝随机游走：`{diag.variance_ratio.is_random_walk}`（VR(q)=1 即随机游走；<1 均值回复，>1 动量）",
        "",
        f"![检测图]({os.path.basename(diag_img)})",
        "",
    ]

    # ── 建模 ──
    if fit is None:
        parts += ["## 2. 建模", "", "未检测到可建模结构，未进行拟合。", ""]
    else:
        parts += [
            "## 2. 建模",
            "",
            f"### 2.1 模型与最优阶数",
            "",
            f"- 模型类型：`{fit.model_type}`",
            f"- 最优阶数：`{_order_str(fit.order)}`（按 `{fit.criterion}` 选取）",
            f"- 样本量：`{fit.n_obs}`；AIC=`{_fmt(fit.aic)}`；BIC=`{_fmt(fit.bic)}`",
            "",
            "### 2.2 参数估计",
            "",
            _params_md(fit.params),
            "",
            "### 2.3 建模后 Ljung-Box 检测",
            "",
        ]
        # GARCH 类（有标准化残差）走均值/方差方程双 LB；其余（ARMA / RandomWalk）走残差 LB
        if fit.std_resid_lb is not None:
            parts += [
                "均值方程 — 标准化残差 Ljung-Box：",
                "",
                _df_md(fit.std_resid_lb.rename(columns={"lb_stat": "统计量", "lb_pvalue": "p 值"}), "滞后阶"),
                "",
                "方差方程 — 标准化残差平方 Ljung-Box：",
                "",
                _df_md(fit.sq_std_resid_lb.rename(columns={"lb_stat": "统计量", "lb_pvalue": "p 值"}), "滞后阶"),
                "",
            ]
        else:
            parts += [
                "残差 Ljung-Box（判定拟合是否充分）：",
                "",
                _df_md(fit.resid_lb.rename(columns={"lb_stat": "统计量", "lb_pvalue": "p 值"}), "滞后阶"),
                "",
            ]
        parts += [
            f"### 2.4 结论",
            "",
            f"- 综合判定：`{'通过' if fit.passed else '未通过'}`",
            f"- 说明：{fit.reason}",
            "",
        ]
        if pred_img:
            parts += [f"![预测图]({os.path.basename(pred_img)})", ""]

    # ── 注意 ──
    parts += [
        "## 3. 注意事项",
        "",
        "- 检测与建模作用在**收益率/差分序列**上，不要直接对非平稳价格建模。",
        "- ARCH-LM、Ljung-Box 对窗口与频率敏感，结论需结合样本长度与业务背景复核。",
        "- 输出仅用于研究方向判断，不构成任何下单依据。",
        "",
    ]
    return "\n".join(parts)


# ────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────
def generate_model_report(
    returns: Any,
    *,
    series_name: str = "series",
    title: str | None = None,
    output_dir: str | Path | None = None,
    forecast_steps: int = 20,
    max_p: int = 5,
    max_q: int = 5,
    criterion: str = "aic",
) -> dict:
    """对收益率序列跑「检测 → 自动建模 → 报告」全流程，返回结构化结果。

    Args:
        returns: 收益率或差分序列（pd.Series / array-like）。
        series_name: 名称，用于报告标题与文件名。
        output_dir: 报告与图输出目录；默认 skill 的 reports/ 下。
        forecast_steps: 预测步数。
        max_p / max_q: ARMA/AR 阶数搜索上界。
        criterion: 'aic' / 'bic'。

    Returns:
        dict：含 markdown、markdown_path、diag、fit、plot_paths。
    """
    r = pd.Series(returns).dropna().astype(float)
    out_dir = Path(output_dir) if output_dir else REPORT_DIR_DEFAULT
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = _safe_stem(series_name)

    # 1) 检测
    diag = run_diagnostics(r)

    # 检测图
    diag_img = out_dir / f"{stem}_diagnostics.png"
    try:
        _plot_diagnostics(r, diag_img)
    except Exception as e:  # pragma: no cover - 图失败不应中断报告
        diag_img = None
        _diag_err = str(e)
    else:
        _diag_err = None

    # 2) 建模（推荐 RandomWalk 时也会拟合 ARIMA(0,1,0) 漂移）
    fit: FitSummary | None = None
    pred_img: str | None = None
    try:
        fit = fit_model(
            diag.recommendation, r,
            max_p=max_p, max_q=max_q, criterion=criterion,
            forecast_steps=forecast_steps,
        )
    except Exception as e:  # 建模失败则仅出检测报告
        fit = None
        _fit_err = str(e)
    else:
        _fit_err = None
        if fit is not None:
            try:
                pred_img = out_dir / f"{stem}_prediction.png"
                _plot_prediction(r, fit, pred_img)
            except Exception as e:
                pred_img = None
                _fit_err = f"绘图失败: {e}"

    # 3) 报告
    md = _build_markdown(
        title=title or f"{series_name} 时序建模报告",
        series_name=series_name,
        diag=diag,
        fit=fit,
        diag_img=diag_img,
        pred_img=pred_img,
    )
    md_path = out_dir / f"{stem}_model_report.md"
    md_path.write_text(md, encoding="utf-8")

    return {
        "markdown": md,
        "markdown_path": str(md_path),
        "diag": diag,
        "fit": fit,
        "diag_plot": str(diag_img) if diag_img else None,
        "pred_plot": str(pred_img) if pred_img else None,
        "fit_error": _fit_err,
    }


__all__ = ["generate_model_report"]
