"""报告脚本：检测 → 建模 → Markdown 报告 + 预测图。

两阶段检测驱动：
  1) ADF(前提) / Ljung-Box / GPH / ARCH-LM / Engle-Ng / ACF-PACF → 均值方程 + 方差方程
  2) 按 flow_a/b/c/d 自动建模（均值×方差 9 种组合全覆盖，常数均值+不变方差也建模）
  3) 最优阶数、参数估计、建模后 Ljung-Box 与结论
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
    idx_name = index_name or (df.index.name if df.index.name else "index")
    header_cols = [str(c) for c in df.columns]
    head = "| " + " | ".join([idx_name, *header_cols]) + " |"
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


def _acfpacf_md(ap: pd.DataFrame, max_lags: int = 15) -> str:
    """ACF/PACF 紧凑表：前 max_lags 阶，带显著性标记（超出 95% CI）。"""
    if ap is None or ap.empty:
        return "_无数据_。"
    df = ap.head(max_lags).copy()
    acf_sig = (df["acf"] < df["acf_lower"]) | (df["acf"] > df["acf_upper"])
    pacf_sig = (df["pacf"] < df["pacf_lower"]) | (df["pacf"] > df["pacf_upper"])
    out = pd.DataFrame(
        {
            "ACF": [_fmt(v) + (" *" if s else "") for v, s in zip(df["acf"], acf_sig)],
            "PACF": [_fmt(v) + (" *" if s else "") for v, s in zip(df["pacf"], pacf_sig)],
        },
        index=df.index,
    )
    out.index.name = "滞后阶"
    return _df_md(out, "滞后阶") + "\n\n> `*` 标记表示超出 95% 置信区间（统计显著）。"


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
    """原始序列 + 样本内拟合 + 向前预测 同图。

    fitted 按原始 index 对齐到位置（ARFIMA/分数差分类的前若干边界点为 NaN，自然只画有效段）。
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y = pd.Series(returns).dropna().astype(float)
    pos = pd.Series(np.arange(len(y)), index=y.index)   # index -> 位置
    fitted = fit.fitted
    fc = fit.forecast_mean.reset_index(drop=True) if len(fit.forecast_mean) else pd.Series(dtype=float)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(pos.values, y.values, label="actual", color="#34495e", linewidth=1.0)
    if fitted is not None and fitted.notna().any():
        fpos = fitted.index.map(pos).to_numpy()
        mask = pd.notna(fpos) & fitted.notna().to_numpy()
        if mask.any():
            ax.plot(np.asarray(fpos[mask], dtype=float), fitted.to_numpy()[mask],
                    label="in-sample fit", color="#27ae60", linewidth=1.0, alpha=0.85)
    if len(fc):
        start = len(y)
        ax.plot(range(start, start + len(fc)), fc.values,
                label=f"forecast ({len(fc)} steps)", color="#e74c3c", linewidth=1.5)
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
        return "建模异常，未能拟合（见下方错误信息）；仅给出检测结果。"
    verdict = "充分" if fit.passed else "尚不充分"
    d_note = f"，分数 d={_fmt(fit.d)}" if fit.d is not None else ""
    return (
        f"流程 `{fit.flow}`：均值方程={fit.mean_equation}、方差方程={fit.variance_equation}"
        f"{d_note}；模型 `{fit.model_type}` 阶数 {_order_str(fit.order)}；拟合{verdict}。"
    )


def _build_markdown(
    *,
    title: str,
    series_name: str,
    diag: DiagnosticReport,
    fit: FitSummary | None,
    diag_img: str | None,
    pred_img: str | None,
) -> str:
    parts: list[str] = [f"# {title}", "", "## 一句话结论", "", _one_sentence(diag, fit), ""]

    # ── 检测 ──
    parts += [
        "## 1. 检测结果",
        "",
        f"> {diag.reason}",
        "",
        "### 1.1 ADF 平稳性（前提）",
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
        "### 1.2 Ljung-Box 自相关（均值方程·短期）",
        "",
        _df_md(diag.ljung_box.table.rename(columns={"lb_stat": "统计量", "lb_pvalue": "p 值"}), "滞后阶"),
        "",
        f"> 存在自相关：`{diag.ljung_box.has_autocorrelation}`",
        "",
        "### 1.3 GPH 长记忆检验（均值方程·分数积分 d）",
        "",
        _kv_md(
            {
                "d_hat": diag.gph.d_hat,
                "se": diag.gph.se,
                "tstat": diag.gph.tstat,
                "pvalue": diag.gph.pvalue,
                "bandwidth(m)": diag.gph.bandwidth,
                "has_long_memory": diag.gph.has_long_memory,
            }
        ),
        "",
        f"> 长记忆（|d|>0.1 且 p<0.05）：`{diag.gph.has_long_memory}`（d>0 持续性，d<0 反持久）",
        "",
        "### 1.4 ARCH-LM 异方差效应（方差方程·波动聚集）",
        "",
        _df_md(
            pd.DataFrame({"统计量": diag.arch_lm.statistics, "p 值": diag.arch_lm.pvalues},
                         index=pd.Index(diag.arch_lm.lags, name="滞后阶")),
        ),
        "",
        f"> 存在 ARCH 效应：`{diag.arch_lm.has_arch_effect}`",
        "",
        "### 1.5 Engle-Ng 符号偏差检验（方差方程·杠杆/非对称）",
        "",
        _kv_md(
            {
                "sign_p": diag.sign_bias.sign_p,
                "negative_p(杠杆)": diag.sign_bias.negative_p,
                "positive_p": diag.sign_bias.positive_p,
                "joint_p": diag.sign_bias.joint_p,
                "has_asymmetry": diag.sign_bias.has_asymmetry,
            }
        ),
        "",
        f"> 存在非对称（杠杆）：`{diag.sign_bias.has_asymmetry}`（任一项 p<0.05 → 建议 GJR-GARCH）",
        "",
        "### 1.6 ACF / PACF（辅助证据）",
        "",
        _acfpacf_md(diag.acf_pacf),
        "",
        "### 均值方程判定",
        "",
        f"**`{diag.mean_equation}`** — 无自相关(LB)→Constant；否则长记忆(GPH)→ARFIMA；否则→ARMA。",
        "",
        "### 方差方程判定",
        "",
        f"**`{diag.variance_equation}`** — 无ARCH→Constant；有ARCH且有杠杆(Engle-Ng)→GJR-GARCH；有ARCH无杠杆→GARCH。",
        "",
    ]
    if diag_img:
        parts += [f"![检测图]({os.path.basename(diag_img)})", ""]

    # ── 建模 ──
    parts += ["## 2. 建模", ""]
    if fit is None:
        parts += [
            "建模异常，未能拟合（可能因样本过短或数值不收敛）；仅给出上方检测结果。",
            "",
        ]
    else:
        d_line = f"\n- 分数差分参数 d：`{_fmt(fit.d)}`" if fit.d is not None else ""
        parts += [
            f"### 2.1 模型与最优阶数",
            "",
            f"- 流程：`{fit.flow}`（均值方程 `{fit.mean_equation}` + 方差方程 `{fit.variance_equation}`）",
            f"- 模型类型：`{fit.model_type}`",
            f"- 最优阶数：`{_order_str(fit.order)}`（按 `{fit.criterion}` 选取）",
            f"- 样本量：`{fit.n_obs}`；AIC=`{_fmt(fit.aic)}`；BIC=`{_fmt(fit.bic)}`" + d_line,
            "",
            "### 2.2 参数估计",
            "",
            _params_md(fit.params),
            "",
            "### 2.3 建模后 Ljung-Box 检测",
            "",
        ]
        if fit.std_resid_lb is not None:
            # flow_b / flow_c：均值方程 + 方差方程双 LB
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
            # flow_a：均值方程残差单 LB
            parts += [
                "均值方程残差（创新）Ljung-Box：",
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
        "- 检测与建模作用在**收益率/差分序列**上；非平稳价格会触发 NonStationaryError。",
        "- GPH/Engle-Ng/Ljung-Box 对窗口与频率敏感，结论需结合样本长度与业务背景复核。",
        "- ARFIMA 采用两步法（arch/statsmodels 不支持分数 d）；GJR-GARCH（o=1）捕捉 Engle-Ng 杠杆效应。",
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
    max_p: int = 3,
    max_q: int = 3,
    p_max: int = 2,
    q_max: int = 2,
    criterion: str = "aic",
) -> dict:
    """对收益率序列跑「检测 → 自动建模 → 报告」全流程，返回结构化结果。

    Args:
        returns: 收益率或差分序列（pd.Series / array-like），必须平稳。
        series_name: 名称，用于报告标题与文件名。
        output_dir: 报告与图输出目录；默认 skill 的 reports/ 下。
        forecast_steps: 预测步数。
        max_p / max_q: 均值方程 ARMA/AR 阶数搜索上界。
        p_max / q_max: 方差方程 GARCH/GJR 阶数搜索上界。
        criterion: 'aic' / 'bic'。

    Returns:
        dict：含 markdown、markdown_path、diag、fit、plot_paths。
    """
    r = pd.Series(returns).dropna().astype(float)
    out_dir = Path(output_dir) if output_dir else REPORT_DIR_DEFAULT
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = _safe_stem(series_name)

    # 1) 检测（非平稳会抛 NonStationaryError，向上传播）
    diag = run_diagnostics(r)

    # 检测图
    diag_img = out_dir / f"{stem}_diagnostics.png"
    _diag_err = None
    try:
        _plot_diagnostics(r, diag_img)
    except Exception as e:  # pragma: no cover - 图失败不应中断报告
        diag_img = None
        _diag_err = str(e)

    # 2) 建模（按 diag.flow 路由 flow_a/b/c/d；异常时 fit=None 仅出检测报告）
    fit: FitSummary | None = None
    pred_img: str | None = None
    _fit_err = None
    try:
        fit = fit_model(
            diag, r,
            max_p=max_p, max_q=max_q, p_max=p_max, q_max=q_max,
            criterion=criterion, forecast_steps=forecast_steps,
        )
    except Exception as e:  # 建模失败则仅出检测报告
        fit = None
        _fit_err = str(e)
    else:
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
        "fit_error": _fit_err or _diag_err,
    }


__all__ = ["generate_model_report"]
