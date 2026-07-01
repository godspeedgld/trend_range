"""时序检测脚本：两阶段检测驱动建模。

**前提**：ADF 平稳。非平稳序列直接抛 NonStationaryError（应传入收益率/差分）。

均值方程（Constant / ARMA / ARFIMA）由：
  - Ljung-Box（短期自相关）
  - GPH（长记忆 / 分数积分）
  - ACF/PACF（辅助证据）
共同判定。

方差方程（Constant / GARCH / GJR）由：
  - ARCH-LM（异方差效应）
  - Engle-Ng 符号偏差（杠杆 / 非对称）
共同判定。

白噪声（常数均值 + 不变方差）→ 不建模。

用法:
    from scripts.diagnostics import run_diagnostics
    result = run_diagnostics(returns)   # pd.Series，必须传入收益率/差分序列
    print(result.flow)                  # 'white_noise' / 'flow_a' / 'flow_b' / 'flow_c'
    print(result.mean_equation, result.variance_equation)
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

SIGNIFICANCE = 0.05
DEFAULT_LB_LAGS = (10, 15, 20)
DEFAULT_ARCH_LAGS = (5, 10, 20)
DEFAULT_ACFPACF_NLAGS = 30


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


class NonStationaryError(Exception):
    """ADF 判定非平稳时抛出。本流程仅作用于平稳序列（收益率/差分）。"""


# ────────────────────────────────────────────────────────────
# 1. ADF 平稳性（前提）
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
    from statsmodels.stats.diagnostic import acorr_ljungbox

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
    from statsmodels.stats.diagnostic import het_arch

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
# 4. GPH 长记忆检验（分数积分参数 d）
# ────────────────────────────────────────────────────────────
@dataclass
class GPHResult:
    d_hat: float               # 分数差分参数估计
    se: float                  # 标准误（OLS）
    tstat: float               # H0: d=0 的 t 统计量
    pvalue: float
    bandwidth: int             # 使用的低频点数 m
    has_long_memory: bool      # |d|>0.1 且 p<significance
    significance: float

    def to_dict(self) -> dict:
        return {
            "d_hat": self.d_hat,
            "se": self.se,
            "tstat": self.tstat,
            "pvalue": self.pvalue,
            "bandwidth": self.bandwidth,
            "has_long_memory": self.has_long_memory,
        }

    def to_markdown(self) -> str:
        return _kv_markdown(
            "GPH 长记忆检验",
            {
                "d_hat": self.d_hat,
                "se": self.se,
                "tstat": self.tstat,
                "pvalue": self.pvalue,
                "bandwidth(m)": self.bandwidth,
                "has_long_memory": self.has_long_memory,
            },
        )


def gph_test(
    series: Any,
    bandwidth: int | None = None,
    significance: float = SIGNIFICANCE,
) -> GPHResult:
    """Geweke-Porter-Hudak 分数积分参数 d 估计。

    对周期图低频点做 OLS：log I(ω_j) ~ log[4·sin²(π f_j)]，斜率 = -d，故 d = -slope。
    - d=0：短记忆；d∈(0,0.5)：长记忆（持续性）；d∈(-0.5,0)：反持久。
    - 取 m=int(sqrt(n)) 个最低频点（不含零频）。
    """
    from scipy.signal import periodogram
    from scipy.stats import norm

    s = _clean(series, "series")
    n = len(s)
    f, pxx = periodogram(s.to_numpy(), window="boxcar", detrend="constant")

    # 默认带宽 m = floor(sqrt(n))，至少 5，至多 n//2 - 1
    if bandwidth is None:
        m = int(np.floor(n ** 0.5))
    else:
        m = int(bandwidth)
    m = max(5, min(m, (len(f) // 2) - 1))

    # 取 j=1..m 个最低频点（跳过零频），剔除非正功率点（log 未定义）
    f_j = f[1 : m + 1]
    p_j = pxx[1 : m + 1]
    mask = (f_j > 0) & (p_j > 0)
    f_j, p_j = f_j[mask], p_j[mask]
    if len(f_j) < 5:
        return GPHResult(float("nan"), float("nan"), float("nan"), 1.0, int(len(f_j)), False, significance)

    x = np.log(4.0 * np.sin(np.pi * f_j) ** 2)   # 回归变量
    y = np.log(p_j)                              # 周期图对数

    # OLS: y = a + b*x；d = -b
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    slope = float(beta[1])
    d_hat = -slope
    resid = y - X @ beta
    dof = max(len(y) - 2, 1)
    sigma2 = float((resid ** 2).sum() / dof)
    sxx = float(((x - x.mean()) ** 2).sum())
    se = float(np.sqrt(sigma2 / sxx)) if sxx > 0 else float("nan")
    tstat = float(d_hat / se) if se and np.isfinite(se) and se > 0 else float("nan")
    pvalue = float(2 * (1 - norm.cdf(abs(tstat)))) if np.isfinite(tstat) else float("nan")

    has_lm = bool(np.isfinite(d_hat) and abs(d_hat) > 0.1 and np.isfinite(pvalue) and pvalue < significance)
    return GPHResult(d_hat, se, tstat, pvalue, int(len(f_j)), has_lm, significance)


# ────────────────────────────────────────────────────────────
# 5. Engle-Ng 符号偏差检验（杠杆 / 非对称波动）
# ────────────────────────────────────────────────────────────
@dataclass
class SignBiasResult:
    sign_p: float          # 符号偏差（负冲击哑变量）p 值
    negative_p: float      # 负向尺寸偏差 p 值（经典杠杆信号）
    positive_p: float      # 正向尺寸偏差 p 值
    joint_p: float         # 三项联合检验 p 值
    has_asymmetry: bool    # 任一 p < significance
    significance: float

    def to_dict(self) -> dict:
        return {
            "sign_p": self.sign_p,
            "negative_p": self.negative_p,
            "positive_p": self.positive_p,
            "joint_p": self.joint_p,
            "has_asymmetry": self.has_asymmetry,
        }

    def to_markdown(self) -> str:
        return _kv_markdown(
            "Engle-Ng 符号偏差检验",
            {
                "sign_p": self.sign_p,
                "negative_p(杠杆)": self.negative_p,
                "positive_p": self.positive_p,
                "joint_p": self.joint_p,
                "has_asymmetry": self.has_asymmetry,
            },
        )


def engle_ng_sign_bias_test(
    residuals: Any,
    significance: float = SIGNIFICANCE,
) -> SignBiasResult:
    """Engle-Ng (1993) 符号/尺寸偏差检验：检验条件方差是否受过去冲击符号与幅度非对称影响。

    回归： ε_t² = c + b1·S⁻_{t-1} + b2·(S⁻_{t-1}·ε_{t-1}) + b3·((1−S⁻_{t-1})·ε_{t-1}) + u_t
      S⁻ = 1 若 ε_{t-1}<0 否则 0。
      b1=符号偏差；b2=负向尺寸偏差（杠杆）；b3=正向尺寸偏差；联合检验 b1=b2=b3=0。

    输入为残差序列；**检测阶段尚未建模时，传入去均值序列 r-mean(r) 作为 ε 近似**。
    """
    import statsmodels.api as sm

    e = _clean(residuals, "residuals")
    if len(e) < 10:
        return SignBiasResult(1.0, 1.0, 1.0, 1.0, False, significance)

    e_lag = e.shift(1)
    df = pd.DataFrame({"e2": (e ** 2).values, "e_lag": e_lag.values}).dropna()
    if len(df) < 8:
        return SignBiasResult(1.0, 1.0, 1.0, 1.0, False, significance)

    s_neg = (df["e_lag"] < 0).astype(float)
    neg_size = s_neg * df["e_lag"]
    pos_size = (1.0 - s_neg) * df["e_lag"]
    X = sm.add_constant(
        pd.DataFrame({"S_neg": s_neg.values, "neg_size": neg_size.values, "pos_size": pos_size.values}),
        has_constant="add",
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = sm.OLS(df["e2"].values, X).fit()
    except Exception:
        return SignBiasResult(1.0, 1.0, 1.0, 1.0, False, significance)

    sign_p = _safe_float(model.pvalues.get("S_neg", float("nan")))
    negative_p = _safe_float(model.pvalues.get("neg_size", float("nan")))
    positive_p = _safe_float(model.pvalues.get("pos_size", float("nan")))
    try:
        joint_p = _safe_float(model.f_test("S_neg = 0, neg_size = 0, pos_size = 0").pvalue)
    except Exception:
        joint_p = float("nan")

    pvals = [p for p in (sign_p, negative_p, positive_p, joint_p) if np.isfinite(p)]
    has_asym = bool(any(p < significance for p in pvals)) if pvals else False
    return SignBiasResult(sign_p, negative_p, positive_p, joint_p, has_asym, significance)


# ────────────────────────────────────────────────────────────
# 6. ACF / PACF（辅助证据）
# ────────────────────────────────────────────────────────────
def acf_pacf(series: Any, nlags: int = DEFAULT_ACFPACF_NLAGS) -> pd.DataFrame:
    """返回 ACF/PACF 及 95% 置信区间，供报告展示（辅助判定 AR/MA 阶数）。"""
    from statsmodels.tsa.stattools import acf, pacf

    s = _clean(series, "series")
    nlags = max(1, min(int(nlags), (len(s) // 2) - 1))
    acf_vals, acf_ci = acf(s.to_numpy(), nlags=nlags, fft=True, alpha=0.05)
    pacf_vals, pacf_ci = pacf(s.to_numpy(), nlags=nlags, alpha=0.05)
    idx = pd.Index(range(nlags + 1), name="lag")
    return pd.DataFrame(
        {
            "acf": acf_vals,
            "acf_lower": acf_ci[:, 0],
            "acf_upper": acf_ci[:, 1],
            "pacf": pacf_vals,
            "pacf_lower": pacf_ci[:, 0],
            "pacf_upper": pacf_ci[:, 1],
        },
        index=idx,
    )


# ────────────────────────────────────────────────────────────
# 7. 两阶段模型判定
# ────────────────────────────────────────────────────────────
def recommend_mean_equation(lb_has_ac: bool, gph_has_lm: bool) -> str:
    """均值方程：无自相关 → Constant；否则长记忆 → ARFIMA；否则 → ARMA。

    顺序：先以 Ljung-Box 作为「有无均值结构」的总闸——无自相关即判 Constant；
    只有存在自相关时，再用 GPH 区分长记忆(ARFIMA)与短记忆(ARMA)。
    """
    if not lb_has_ac:
        return "Constant"
    if gph_has_lm:
        return "ARFIMA"
    return "ARMA"


def recommend_variance_equation(arch_has: bool, engle_has_asym: bool) -> str:
    """方差方程：无 ARCH → Constant；有 ARCH 且有杠杆 → GJR（非对称 GARCH）；有 ARCH 无杠杆 → GARCH。"""
    if not arch_has:
        return "Constant"
    if engle_has_asym:
        return "GJR"
    return "GARCH"


def classify_model(mean_eq: str, var_eq: str) -> tuple[str, str]:
    """由均值/方差方程组合判定流程分支与模型类型。

    返回 (flow, model_type)：
      white_noise : 常数均值 + 不变方差（不建模）
      flow_a      : 均值方程(ARMA/ARFIMA) + 不变方差
      flow_b      : 常数均值 + 方差方程(GARCH/GJR)
      flow_c      : 均值方程 + 方差方程
    """
    mean_struct = mean_eq != "Constant"
    var_struct = var_eq != "Constant"
    if not mean_struct and not var_struct:
        return "white_noise", "WhiteNoise"
    if mean_struct and not var_struct:
        return "flow_a", mean_eq
    if not mean_struct and var_struct:
        return "flow_b", var_eq
    return "flow_c", f"{mean_eq}+{var_eq}"


# ────────────────────────────────────────────────────────────
# 8. 汇总报告
# ────────────────────────────────────────────────────────────
@dataclass
class DiagnosticReport:
    adf: ADFResult
    ljung_box: LjungBoxResult
    arch_lm: ArchLMResult
    gph: GPHResult
    sign_bias: SignBiasResult
    acf_pacf: pd.DataFrame
    mean_equation: str          # 'Constant' / 'ARMA' / 'ARFIMA'
    variance_equation: str      # 'Constant' / 'GARCH' / 'GJR'
    flow: str                   # 'white_noise' / 'flow_a' / 'flow_b' / 'flow_c'
    recommendation: str         # 模型类型字符串（兼容旧命名）
    reason: str

    def to_dict(self) -> dict:
        return {
            "adf": self.adf.to_dict(),
            "ljung_box": self.ljung_box.to_dict(),
            "arch_lm": self.arch_lm.to_dict(),
            "gph": self.gph.to_dict(),
            "sign_bias": self.sign_bias.to_dict(),
            "mean_equation": self.mean_equation,
            "variance_equation": self.variance_equation,
            "flow": self.flow,
            "recommendation": self.recommendation,
            "reason": self.reason,
        }


def run_diagnostics(
    series: Any,
    *,
    lb_lags: tuple[int, ...] = DEFAULT_LB_LAGS,
    arch_lags: tuple[int, ...] = DEFAULT_ARCH_LAGS,
    gph_bandwidth: int | None = None,
    acfpacf_nlags: int = DEFAULT_ACFPACF_NLAGS,
    significance: float = SIGNIFICANCE,
) -> DiagnosticReport:
    """两阶段检测驱动建模的汇总诊断。

    流程：
      1. ADF → 非平稳直接抛 NonStationaryError（应传入收益率/差分）。
      2. 均值检测：Ljung-Box + GPH → mean_equation。
      3. 方差检测：ARCH-LM + Engle-Ng（用 r-mean(r) 近似残差）→ variance_equation。
      4. classify_model → flow + 模型类型。

    注意：所有检验作用在收益率或残差上，而不是原始非平稳价格。
    """
    s = _clean(series, "series")
    adf = adf_test(s, significance)
    if not adf.is_stationary:
        raise NonStationaryError(
            f"ADF 检验判定序列非平稳（p={adf.pvalue:.4f}）。本流程仅作用于平稳序列，"
            "请先对价格做对数收益率或差分后再传入。"
        )

    lb = ljung_box_test(s, lb_lags, significance)
    gph = gph_test(s, gph_bandwidth, significance)
    arch = arch_lm_test(s, arch_lags, significance)
    sign_bias = engle_ng_sign_bias_test(s - float(s.mean()), significance)
    acf_df = acf_pacf(s, acfpacf_nlags)

    mean_eq = recommend_mean_equation(lb.has_autocorrelation, gph.has_long_memory)
    var_eq = recommend_variance_equation(arch.has_arch_effect, sign_bias.has_asymmetry)
    flow, model_type = classify_model(mean_eq, var_eq)

    reason = (
        f"均值方程={mean_eq}（LB自相关={lb.has_autocorrelation}, "
        f"GPH长记忆={gph.has_long_memory}(d={gph.d_hat:.3f})）；"
        f"方差方程={var_eq}（ARCH效应={arch.has_arch_effect}, "
        f"Engle-Ng杠杆={sign_bias.has_asymmetry}）"
    )
    return DiagnosticReport(
        adf=adf,
        ljung_box=lb,
        arch_lm=arch,
        gph=gph,
        sign_bias=sign_bias,
        acf_pacf=acf_df,
        mean_equation=mean_eq,
        variance_equation=var_eq,
        flow=flow,
        recommendation=model_type,
        reason=reason,
    )


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
    "NonStationaryError",
    "ADFResult",
    "LjungBoxResult",
    "ArchLMResult",
    "GPHResult",
    "SignBiasResult",
    "DiagnosticReport",
    "adf_test",
    "ljung_box_test",
    "arch_lm_test",
    "gph_test",
    "engle_ng_sign_bias_test",
    "acf_pacf",
    "recommend_mean_equation",
    "recommend_variance_equation",
    "classify_model",
    "run_diagnostics",
]
