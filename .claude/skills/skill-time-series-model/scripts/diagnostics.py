"""时序检测脚本：ADF 平稳性、Ljung-Box 自相关、ARCH-LM 异方差效应。

三个独立检测函数 + 一个汇总推荐函数，由 modeling.reporting 调用，
也可被 agent 单独使用决定走哪种建模路径。

用法:
    from scripts.diagnostics import run_diagnostics
    result = run_diagnostics(returns)  # pd.Series，建议传入收益率/差分序列
    print(result.recommendation)       # 'none' / 'ARMA' / 'AR+GARCH' / 'ARMA+GARCH'
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.tsa.stattools import adfuller

SIGNIFICANCE = 0.05
DEFAULT_LB_LAGS = (10, 15, 20)
DEFAULT_ARCH_LAGS = (5, 10, 20)
DEFAULT_VR_LAGS = (2, 5, 10, 20)


# ────────────────────────────────────────────────────────────
# 工具
# ────────────────────────────────────────────────────────────
def _clean(series: Any, name: str = "series") -> pd.Series:
    s = pd.Series(series).dropna().astype(float)
    if s.empty:
        raise ValueError(f"{name} must contain at least one numeric observation")
    return s


def _safe_float(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


# ────────────────────────────────────────────────────────────
# 1. ADF 平稳性
# ────────────────────────────────────────────────────────────
@dataclass
class ADFResult:
    statistic: float
    pvalue: float
    used_lag: int
    n_obs: int
    critical_values: dict
    is_stationary: bool

    def to_dict(self) -> dict:
        return {
            "statistic": self.statistic,
            "pvalue": self.pvalue,
            "used_lag": self.used_lag,
            "n_obs": self.n_obs,
            "is_stationary": self.is_stationary,
        }

    def to_markdown(self) -> str:
        return _kv_markdown(
            "ADF 检验",
            {
                "statistic": self.statistic,
                "pvalue": self.pvalue,
                "used_lag": self.used_lag,
                "n_obs": self.n_obs,
                "is_stationary (5%)": self.is_stationary,
            },
        )


def adf_test(series: Any, significance: float = SIGNIFICANCE) -> ADFResult:
    """ADF 单位根检验。p < significance 视为平稳。"""
    s = _clean(series, "series")
    if s.nunique(dropna=True) <= 1:
        return ADFResult(float("nan"), 1.0, 0, len(s), {}, False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = adfuller(s, autolag="AIC")
    stat, p, used_lag, nobs = res[0], res[1], res[2], res[3]
    crit = {k: float(v) for k, v in res[4].items()} if len(res) > 4 else {}
    return ADFResult(float(stat), float(p), int(used_lag), int(nobs), crit, p < significance)


# ────────────────────────────────────────────────────────────
# 2. Ljung-Box 自相关
# ────────────────────────────────────────────────────────────
@dataclass
class LjungBoxResult:
    table: pd.DataFrame  # columns: lb_stat, lb_pvalue; index = lags
    significance: float
    has_autocorrelation: bool

    def to_dict(self) -> dict:
        return {
            "lags": list(self.table.index.astype(int)),
            "pvalues": [float(x) for x in self.table["lb_pvalue"].tolist()],
            "has_autocorrelation": self.has_autocorrelation,
        }

    def to_markdown(self) -> str:
        if self.table.empty:
            return "_无数据_。"
        df = self.table.copy()
        df.columns = ["统计量", "p 值"]
        df.index.name = "滞后阶"
        return _frame_markdown(df)


def ljung_box_test(
    series: Any,
    lags: tuple[int, ...] = DEFAULT_LB_LAGS,
    significance: float = SIGNIFICANCE,
) -> LjungBoxResult:
    """Ljung-Box 检验。任一阶 p < significance 即判定存在自相关。"""
    s = _clean(series, "series")
    lags = [int(l) for l in lags if l < len(s)]
    if not lags:
        return LjungBoxResult(pd.DataFrame(columns=["lb_stat", "lb_pvalue"]), significance, False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lb = acorr_ljungbox(s, lags=lags, return_df=True)
    lb = lb.rename(columns={"lb_stat": "lb_stat", "lb_pvalue": "lb_pvalue"})
    has_ac = bool((lb["lb_pvalue"] < significance).any())
    return LjungBoxResult(lb, significance, has_ac)


# ────────────────────────────────────────────────────────────
# 3. ARCH-LM 异方差效应
# ────────────────────────────────────────────────────────────
@dataclass
class ArchLMResult:
    lags: list[int]
    statistics: list[float]
    pvalues: list[float]
    has_arch_effect: bool
    significance: float

    def to_dict(self) -> dict:
        return {
            "lags": self.lags,
            "statistics": self.statistics,
            "pvalues": self.pvalues,
            "has_arch_effect": self.has_arch_effect,
        }

    def to_markdown(self) -> str:
        df = pd.DataFrame(
            {"统计量": self.statistics, "p 值": self.pvalues},
            index=pd.Index(self.lags, name="滞后阶"),
        )
        return _frame_markdown(df)


def arch_lm_test(
    series: Any,
    lags: tuple[int, ...] = DEFAULT_ARCH_LAGS,
    significance: float = SIGNIFICANCE,
) -> ArchLMResult:
    """Engle ARCH-LM 检验（基于 het_arch）。任一阶 p < significance 即存在 ARCH 效应。"""
    s = _clean(series, "series")
    lags = [int(l) for l in lags if l < len(s) - 1]
    if not lags:
        return ArchLMResult([], [], [], False, significance)
    out_stat, out_p = [], []
    has_arch = False
    for lag in lags:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                lm_stat, lm_p, *_ = het_arch(s, nlags=lag)
            out_stat.append(_safe_float(lm_stat))
            out_p.append(_safe_float(lm_p))
            if np.isfinite(lm_p) and lm_p < significance:
                has_arch = True
        except Exception:
            out_stat.append(float("nan"))
            out_p.append(float("nan"))
    return ArchLMResult(lags, out_stat, out_p, has_arch, significance)


# ────────────────────────────────────────────────────────────
# 4. 方差比检验（Lo-MacKinlay，随机游走检验）
# ────────────────────────────────────────────────────────────
@dataclass
class VarianceRatioResult:
    lags: list[int]
    vr: list[float]              # VR(q) 统计量；H0 下 = 1
    z: list[float]               # 标准化 z 统计量
    pvalues: list[float]
    is_random_walk: bool         # 任一阶都不能拒绝 H0 才算"未拒绝随机游走"
    significance: float

    def to_dict(self) -> dict:
        return {
            "lags": self.lags,
            "vr": self.vr,
            "z": self.z,
            "pvalues": self.pvalues,
            "is_random_walk": self.is_random_walk,
        }

    def to_markdown(self) -> str:
        df = pd.DataFrame(
            {"VR(q)": self.vr, "z 统计量": self.z, "p 值": self.pvalues},
            index=pd.Index(self.lags, name="持有期 q"),
        )
        return _frame_markdown(df)


def variance_ratio_test(
    series: Any,
    lags: tuple[int, ...] = DEFAULT_VR_LAGS,
    significance: float = SIGNIFICANCE,
) -> VarianceRatioResult:
    """Lo-MacKinlay 方差比检验。H0：序列服从随机游走（VR(q)=1）。

    VR(q) = Var(q 期收益) / (q · Var(1 期收益))。H0 下 VR(q)=1。
    - VR > 1：正自相关（动量）；VR < 1：负自相关（均值回复）。
    - 任一阶 p < significance → 拒绝随机游走。
    采用同方差版本的标准误（Lo-MacKinlay 1988）。
    """
    from scipy.stats import norm

    s = _clean(series, "series")
    r = s.to_numpy()
    n = len(r)
    mean = r.mean()
    var1 = float(((r - mean) ** 2).sum() / (n - 1)) if n > 1 else float("nan")
    # q 期（重叠）收益 = 累积和之差
    cq = np.concatenate(([0.0], np.cumsum(r)))           # cq[t] = sum(r[:t])
    out_q, out_vr, out_z, out_p = [], [], [], []
    rw = True
    for q in lags:
        q = int(q)
        if q < 2 or q >= n:
            continue
        rq = cq[q:] - cq[:-q]                            # 长度 n-q+1 的重叠 q 期收益
        nq = len(rq)
        varq = float(((rq - q * mean) ** 2).sum() / (nq - 1)) if nq > 1 else float("nan")
        vr = varq / (q * var1) if var1 and var1 > 0 else float("nan")
        phi = (2 * (2 * q - 1) * (q - 1)) / (3 * q * n)   # 同方差渐近方差
        z = (vr - 1) / np.sqrt(phi) if phi > 0 else float("nan")
        p = 2 * (1 - norm.cdf(abs(z))) if np.isfinite(z) else float("nan")
        out_q.append(q)
        out_vr.append(_safe_float(vr))
        out_z.append(_safe_float(z))
        out_p.append(_safe_float(p))
        if np.isfinite(p) and p < significance:
            rw = False
    return VarianceRatioResult(out_q, out_vr, out_z, out_p, rw, significance)


# ────────────────────────────────────────────────────────────
# 5. 汇总 + 模型推荐
# ────────────────────────────────────────────────────────────
MODEL_MAP = {
    "RandomWalk": "随机游走（无自相关、无 ARCH 效应，VR 不拒绝）→ ARIMA(0,1,0)",
    "ARMA": "有自相关、无 ARCH 效应 → ARMA",
    "AR+GARCH": "无自相关、有 ARCH 效应 → AR + GARCH",
    "ARMA+GARCH": "有自相关、有 ARCH 效应 → ARMA + GARCH",
}


@dataclass
class DiagnosticReport:
    adf: ADFResult
    ljung_box: LjungBoxResult
    arch_lm: ArchLMResult
    variance_ratio: VarianceRatioResult
    recommendation: str  # 'RandomWalk' / 'ARMA' / 'AR+GARCH' / 'ARMA+GARCH'
    reason: str

    def to_dict(self) -> dict:
        return {
            "adf": self.adf.to_dict(),
            "ljung_box": self.ljung_box.to_dict(),
            "arch_lm": self.arch_lm.to_dict(),
            "variance_ratio": self.variance_ratio.to_dict(),
            "recommendation": self.recommendation,
            "reason": self.reason,
        }


def recommend_model(
    lb_has_ac: bool,
    arch_has_effect: bool,
    vr_is_random_walk: bool = True,
) -> tuple[str, str]:
    """根据自相关 / ARCH 效应 / 随机游走检验的组合判定建议模型。"""
    if lb_has_ac and arch_has_effect:
        return "ARMA+GARCH", "同时存在自相关与 ARCH 效应，建议 ARMA+GARCH 联合建模"
    if lb_has_ac and not arch_has_effect:
        return "ARMA", "有自相关、无 ARCH 效应，建议 ARMA 建模"
    if not lb_has_ac and arch_has_effect:
        return "AR+GARCH", "无显著自相关但存在 ARCH 效应，建议 AR + GARCH 建模"
    # 无自相关、无 ARCH 效应
    if vr_is_random_walk:
        return "RandomWalk", "无自相关与 ARCH 效应，方差比检验不拒绝随机游走，建议 ARIMA(0,1,0) 漂移模型"
    return "RandomWalk", "未检测到显著自相关/ARCH，但方差比检验拒绝随机游走；按随机游走漂移建模，注意可能存在非线性结构"


def run_diagnostics(
    series: Any,
    *,
    lb_lags: tuple[int, ...] = DEFAULT_LB_LAGS,
    arch_lags: tuple[int, ...] = DEFAULT_ARCH_LAGS,
    vr_lags: tuple[int, ...] = DEFAULT_VR_LAGS,
    significance: float = SIGNIFICANCE,
) -> DiagnosticReport:
    """对序列一次性跑 ADF + Ljung-Box + ARCH-LM + 方差比检验并给出建模建议。

    注意：ARCH-LM / Ljung-Box / 方差比通常作用在收益率或残差上，而不是原始非平稳价格。
    传入前请先做差分/取对数收益率，或在调用了建模后对残差使用。
    """
    adf = adf_test(series, significance)
    lb = ljung_box_test(series, lb_lags, significance)
    arch = arch_lm_test(series, arch_lags, significance)
    vr = variance_ratio_test(series, vr_lags, significance)
    rec, reason = recommend_model(lb.has_autocorrelation, arch.has_arch_effect, vr.is_random_walk)
    return DiagnosticReport(adf, lb, arch, vr, rec, reason)


# ────────────────────────────────────────────────────────────
# Markdown 辅助
# ────────────────────────────────────────────────────────────
def _fmt(v: Any) -> str:
    if isinstance(v, float):
        if pd.isna(v):
            return "nan"
        return f"{v:.4f}"
    return str(v).replace("|", "\\|").replace("\n", "<br>")


def _kv_markdown(title: str, items: dict) -> str:
    lines = [f"### {title}", "", "| 指标 | 值 |", "|---|---:|"]
    for k, v in items.items():
        lines.append(f"| `{k}` | {_fmt(v)} |")
    return "\n".join(lines)


def _frame_markdown(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "_无数据_。"
    header = "| " + " | ".join([str(df.index.name or "index"), *df.columns.astype(str)]) + " |"
    sep = "| " + " | ".join("---" for _ in range(len(df.columns) + 1)) + " |"
    rows = [header, sep]
    for idx, r in df.iterrows():
        rows.append("| " + " | ".join([_fmt(idx), *(_fmt(x) for x in r.values)]) + " |")
    return "\n".join(rows)


__all__ = [
    "ADFResult",
    "LjungBoxResult",
    "ArchLMResult",
    "VarianceRatioResult",
    "DiagnosticReport",
    "MODEL_MAP",
    "adf_test",
    "ljung_box_test",
    "arch_lm_test",
    "variance_ratio_test",
    "recommend_model",
    "run_diagnostics",
]
