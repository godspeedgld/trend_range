"""时序建模脚本：两阶段检测驱动的四流程建模。

由 diagnostics.DiagnosticReport 的 flow 分支路由（均值×方差 3×3=9 种组合全覆盖）：
  flow_a : 均值方程(ARMA/ARFIMA) + 不变方差      → 原子均值拟合 + 残差 LB
  flow_b : 常数均值 + 方差方程(GARCH/GJR-GARCH)  → 常数均值 + 残差上 GARCH/GJR
  flow_c : 均值方程 + 方差方程                   → 两步：均值取残差 → 残差上 GARCH/GJR
  flow_d : 常数均值 + 不变方差                   → 拟合常数模型(μ, σ²) + 残差 LB

ARFIMA 采用两步法（arch/statsmodels 不支持分数 d）：
  GPH 估 d → 分数差分 (1-L)^d → 对差分序列 fit ARMA；创新即为 ARFIMA 残差。

注：arch 8.0 的 EGARCH 仅含 |z| 幅度项、无符号项，无法刻画杠杆；
非对称情形用 GJR-GARCH（vol='GARCH', o=1，含 gamma 杠杆项）。

依赖：statsmodels（ARMA/ARIMA）、arch（GARCH/GJR-GARCH）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA

from scripts.diagnostics import _clean, _safe_float

LB_LAGS = (10, 15, 20)
SIGNIFICANCE = 0.05


# ════════════════════════════════════════════════════════════
# 结果容器
# ════════════════════════════════════════════════════════════
@dataclass
class FitSummary:
    """模型拟合后的通用结果，供 reporting 使用。"""

    model_type: str               # 'ARMA' / 'ARFIMA' / 'GARCH' / 'GJR' / 'ARMA+GARCH' ...
    order: tuple                  # ARMA->(p,q)；ARFIMA->(p,d,q)；含方差->((均值阶),(P,Q))
    criterion: str                # 'aic' / 'bic'
    params: dict                  # 参数名 -> 值
    aic: float
    bic: float
    n_obs: int
    resid_lb: pd.DataFrame        # 残差 Ljung-Box（flow_a 均值方程）
    std_resid_lb: pd.DataFrame | None   # 标准化残差 Ljung-Box（方差类均值方程）
    sq_std_resid_lb: pd.DataFrame | None  # 标准化残差平方 Ljung-Box（方差类方差方程）
    passed: bool                  # 综合判定：残差/标准化残差是否已无自相关
    reason: str
    fitted: pd.Series = None      # in-sample 拟合（均值），按原始 index 对齐
    forecast_mean: pd.Series = field(default_factory=pd.Series)
    forecast_index: list = field(default_factory=list)
    resid: pd.Series = None       # 残差/创新（用于报告/再检验）
    # ── 两阶段新增 ──
    mean_equation: str = ""       # 'Constant' / 'ARMA' / 'ARFIMA'
    variance_equation: str = ""   # 'Constant' / 'GARCH' / 'GJR'
    flow: str = ""                # 'flow_a' / 'flow_b' / 'flow_c'
    d: float | None = None        # ARFIMA 分数差分参数


# ════════════════════════════════════════════════════════════
# 公共工具
# ════════════════════════════════════════════════════════════
def _ljung_box(series: pd.Series, lags=LB_LAGS) -> pd.DataFrame:
    from statsmodels.stats.diagnostic import acorr_ljungbox

    s = pd.Series(series).dropna().astype(float)
    lags = [int(l) for l in lags if l < len(s)]
    if not lags:
        return pd.DataFrame(columns=["lb_stat", "lb_pvalue"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return acorr_ljungbox(s, lags=lags, return_df=True)


def _lb_passed(lb_df: pd.DataFrame, significance: float = SIGNIFICANCE) -> bool:
    """通过 = 所有阶 p 值 > significance（残差无可检测自相关）。"""
    if lb_df is None or lb_df.empty:
        return True
    return bool((lb_df["lb_pvalue"] > significance).all())


def _select_arma_order(s: pd.Series, max_p: int, max_q: int, criterion: str):
    """用 pmdarima.auto_arima(d=0) 选 ARMA(p,q) 最优阶。返回 ((p,q), None)。

    强制 d=0（平稳序列）；stepwise 搜索；按 aic/bic 选。仅用于选阶——
    实际拟合由 _fit_arma_at 用 statsmodels ARIMA 统一接口完成（保持 flow_a/flow_c 一致）。
    """
    from pmdarima import auto_arima

    ic = "aic" if criterion == "aic" else "bic"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = auto_arima(
            s, d=0, seasonal=False, stepwise=True, suppress_warnings=True,
            max_p=max_p, max_q=max_q, information_criterion=ic,
            error_action="ignore", trace=False,
        )
    p, q = m.order[0], m.order[2]   # d=0 强制，取 p、q
    return (p, q), None


def _select_ar_order(s: pd.Series, max_ar: int, criterion: str) -> int:
    """用 AIC/BIC 选 AR 阶（ARIMA(p,0,0)），返回最优 p。"""
    grid = []
    for p in range(1, max_ar + 1):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                m = ARIMA(s, order=(p, 0, 0)).fit()
            ic = m.aic if criterion == "aic" else m.bic
            grid.append((p, float(ic)))
        except Exception:
            continue
    if not grid:
        return 1
    grid.sort(key=lambda x: x[1])
    return grid[0][0]


def _arch_mean_forecast(res, steps: int) -> pd.Series:
    try:
        fcast = res.forecast(horizon=steps, reindex=False)
        row = fcast.mean.iloc[-1]
        return pd.Series(row.values, name="forecast")
    except Exception:
        return pd.Series(dtype=float)


# ════════════════════════════════════════════════════════════
# 分数差分 / 积分工具（ARFIMA 两步法）
# ════════════════════════════════════════════════════════════
def _fdiff_weights(d: float, k: int) -> np.ndarray:
    """(1-L)^d 的权重 w_0=1, w_j = w_{j-1}*(j-1-d)/j。"""
    w = np.empty(k)
    w[0] = 1.0
    for j in range(1, k):
        w[j] = w[j - 1] * (j - 1 - d) / j
    return w


def _fint_weights(d: float, k: int) -> np.ndarray:
    """(1-L)^(-d) 的权重 g_0=1, g_j = g_{j-1}*(j-1+d)/j。"""
    w = np.empty(k)
    w[0] = 1.0
    for j in range(1, k):
        w[j] = w[j - 1] * (j - 1 + d) / j
    return w


def _fractional_diff(series: pd.Series, d: float, k: int = 1000) -> pd.Series:
    """分数差分 (1-L)^d。d≈0 时原样返回。前 k-1 个边界点置 NaN。"""
    s = pd.Series(series).astype(float)
    if abs(d) < 1e-6:
        return s
    n = len(s)
    k = max(2, min(k, max(2, n // 2)))
    w = _fdiff_weights(d, k)
    conv = np.convolve(s.to_numpy(), w)[:n].astype(float)
    conv[: k - 1] = np.nan
    return pd.Series(conv, index=s.index)


def _fractional_integrate(vals: np.ndarray, d: float, k: int = 2000) -> np.ndarray:
    """分数积分 (1-L)^(-d)（numpy 版，供 ARFIMA 拟合/预测重构用）。前 k-1 点置 NaN。"""
    if abs(d) < 1e-6:
        return vals.astype(float).copy()
    n = len(vals)
    k = max(2, min(k, max(2, n // 2)))
    g = _fint_weights(d, k)
    conv = np.convolve(vals, g)[:n].astype(float)
    conv[: k - 1] = np.nan
    return conv


# ════════════════════════════════════════════════════════════
# 原子均值拟合器
# ════════════════════════════════════════════════════════════
def fit_constant_mean(s: pd.Series) -> dict:
    """常数均值：μ = mean(s)，残差 = s - μ。"""
    mu = float(s.mean())
    resid = s - mu
    n = len(s)
    sigma2 = float((resid ** 2).mean())
    if sigma2 > 0:
        logl = -0.5 * n * (np.log(2 * np.pi) + np.log(sigma2) + 1.0)
        aic = float(2 * 2 - 2 * logl)
        bic = float(2 * np.log(n) - 2 * logl)
    else:
        aic = bic = float("nan")
    return {
        "mu": mu,
        "resid": resid,
        "fitted": pd.Series(mu, index=s.index),
        "params": {"mu": mu, "sigma2": sigma2},
        "aic": aic,
        "bic": bic,
        "forecast": pd.Series(np.full(20, mu)),
    }


def _fit_arma_at(s: pd.Series, p: int, q: int, forecast_steps: int = 0) -> dict:
    """拟合固定阶 ARMA(p,q)（d=0），返回残差/拟合/预测/IC。供选阶与 flow_c 复用。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ARIMA(s, order=(p, 0, q)).fit()
    resid = pd.Series(model.resid, index=s.index).dropna()
    fitted = pd.Series(model.fittedvalues, index=s.index).dropna()
    try:
        fc = model.get_forecast(steps=forecast_steps)
        fc_mean = pd.Series(fc.predicted_mean.values, name="forecast")
    except Exception:
        fc_mean = pd.Series(dtype=float)
    params = {k: _safe_float(v) for k, v in model.params.items()}
    return {
        "order": (p, q),
        "params": params,
        "resid": resid,
        "fitted": fitted,
        "forecast": fc_mean,
        "aic": _safe_float(model.aic),
        "bic": _safe_float(model.bic),
    }


def fit_arma_mean(
    s: pd.Series,
    max_p: int = 3,
    max_q: int = 3,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> dict:
    """ARMA 均值：AIC/BIC 选阶 → 估计（_fit_arma_at）→ 残差/拟合/预测。"""
    (p, q), _model = _select_arma_order(s, max_p, max_q, criterion)
    return _fit_arma_at(s, p, q, forecast_steps=forecast_steps)


def _arfima_prep(s: pd.Series) -> tuple[float, pd.Series]:
    """ARFIMA 两步法预处理：GPH 估 d → 分数差分 → 返回 (d, 有效差分序列)。"""
    from scripts.diagnostics import gph_test

    d_raw = _safe_float(gph_test(s).d_hat)
    d = 0.0 if (not np.isfinite(d_raw) or abs(d_raw) >= 0.5) else float(d_raw)
    diff_y = _fractional_diff(s, d, k=1000)
    valid = diff_y.dropna()
    if len(valid) < 20:  # 序列过短无法可靠两步法，退化为 ARMA
        d = 0.0
        valid = s.astype(float)
    return d, valid


def _fit_arfima_at(
    s: pd.Series,
    valid: pd.Series,
    p: int,
    q: int,
    d: float,
    forecast_steps: int = 0,
) -> dict:
    """ARFIMA 两步法固定阶拟合：在差分序列 valid 上 fit ARMA(p,q)，重构回原始尺度。

    s: 原始序列（用于 index 对齐与重构）；valid: (1-L)^d s 的有效段。
    resid 为 ARFIMA 创新（=差分序列上的 ARMA 残差）；fitted/forecast 经 (1-L)^(-d) 重构。
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ARIMA(valid, order=(p, 0, q)).fit()
    resid_y = pd.Series(model.resid, index=valid.index)          # ARFIMA 创新

    # 重构原始尺度（可视化用）：fitted_r = r - (1-L)^(-d) resid_y（k=200 换覆盖率）
    resid_r_arr = _fractional_integrate(resid_y.to_numpy(), d, k=200)
    fitted_full = pd.Series(np.nan, index=s.index)
    fitted_full.loc[valid.index] = s.loc[valid.index].to_numpy() - resid_r_arr

    # 预测：ARMA 预测差分序列 → 积分回原始尺度
    try:
        fc_y = np.asarray(model.get_forecast(steps=forecast_steps).predicted_mean.values, dtype=float)
    except Exception:
        fc_y = np.zeros(forecast_steps)
    if abs(d) > 1e-6 and forecast_steps > 0:
        y_ext = np.concatenate([valid.to_numpy(), fc_y])
        r_ext = _fractional_integrate(y_ext, d, k=2000)
        fc_mean = pd.Series(r_ext[len(valid): len(valid) + forecast_steps])
    else:
        fc_mean = pd.Series(fc_y)

    params = {k: _safe_float(v) for k, v in model.params.items()}
    params["d"] = d
    return {
        "order": (p, d, q),
        "d": d,
        "params": params,
        "resid": resid_y,
        "fitted": fitted_full,
        "forecast": fc_mean,
        "aic": _safe_float(model.aic),
        "bic": _safe_float(model.bic),
    }


def fit_arfima_mean(
    s: pd.Series,
    max_p: int = 3,
    max_q: int = 3,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> dict:
    """ARFIMA 均值（两步法）：GPH 估 d → 分数差分 → 差分序列上 AIC/BIC 选 (p,q) → 拟合。

    返回 order=(p,d,q)；resid 为 ARFIMA 创新（=差分序列上的 ARMA 残差）；
    fitted/forecast 经 (1-L)^(-d) 重构回原始尺度（前若干边界点为 NaN）。
    """
    d, valid = _arfima_prep(s)
    (p, q), _model = _select_arma_order(valid, max_p, max_q, criterion)
    return _fit_arfima_at(s, valid, p, q, d, forecast_steps=forecast_steps)


# ════════════════════════════════════════════════════════════
# 原子方差拟合器
# ════════════════════════════════════════════════════════════
def _select_vol_order(resid: pd.Series, vol_kind: str, p_max: int, q_max: int, criterion: str):
    """在 (P,Q) 网格上按 AIC/BIC 选最优方差阶（mean='Zero'）。返回 ((P,Q), arch_result)。

    vol_kind: 'GARCH'（对称，o=0）或 'GJR'（非对称，o=1，含杠杆项 gamma）。
    注：arch 8.0 的 EGARCH 仅含 |z| 幅度项、无符号项，无法刻画杠杆；
    故非对称情形用 GJR-GARCH（vol='GARCH', o=1）。
    """
    from arch import arch_model

    o = 1 if vol_kind == "GJR" else 0
    best = None
    for P in range(1, p_max + 1):
        for Q in range(0, q_max + 1):
            try:
                am = arch_model(resid, mean="Zero", vol="GARCH", p=P, o=o, q=Q,
                                dist="normal", rescale=False)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    res = am.fit(disp="off", show_warning=False)
                ic = res.aic if criterion == "aic" else res.bic
                if best is None or ic < best[0]:
                    best = (ic, (P, Q), res)
            except Exception:
                continue
    if best is None:
        # 兜底：GARCH(1,1)（GJR 收敛失败时退化为对称 GARCH）
        am = arch_model(resid, mean="Zero", vol="GARCH", p=1, o=0, q=1, dist="normal", rescale=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = am.fit(disp="off", show_warning=False)
        best = (res.aic, (1, 1), res)
    return best[1], best[2]


def _fit_vol(resid: pd.Series, vol_kind: str, p_max: int, q_max: int, criterion: str) -> dict:
    vol_order, res = _select_vol_order(resid, vol_kind, p_max, q_max, criterion)
    cond_vol = pd.Series(res.conditional_volatility, index=resid.index)
    std_resid = (resid / cond_vol).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "vol_order": vol_order,
        "arch_res": res,
        "std_resid": std_resid,
        "cond_vol": cond_vol,
        "aic": _safe_float(res.aic),
        "bic": _safe_float(res.bic),
    }


def _fit_vol_at_order(resid: pd.Series, vol_kind: str, P: int, Q: int) -> dict:
    """按固定方差阶 (P,Q) 拟合（mean='Zero'），返回 arch result + 标准化残差 + IC。

    供 flow_c 迭代中「固定方差阶」使用（不做网格搜索）。
    """
    from arch import arch_model

    o = 1 if vol_kind == "GJR" else 0
    am = arch_model(resid, mean="Zero", vol="GARCH", p=P, o=o, q=Q,
                    dist="normal", rescale=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = am.fit(disp="off", show_warning=False)
    cond_vol = pd.Series(res.conditional_volatility, index=resid.index)
    std_resid = (resid / cond_vol).replace([np.inf, -np.inf], np.nan).dropna()
    return {
        "vol_order": (P, Q),
        "arch_res": res,
        "std_resid": std_resid,
        "aic": _safe_float(res.aic),
        "bic": _safe_float(res.bic),
    }


def fit_garch_var(resid: Any, p_max: int = 2, q_max: int = 2, criterion: str = "aic") -> dict:
    """对称 GARCH 方程：输入残差，返回方差阶 + arch result + 标准化残差。"""
    return _fit_vol(_clean(resid, "resid"), "GARCH", p_max, q_max, criterion)


def fit_gjr_var(resid: Any, p_max: int = 2, q_max: int = 2, criterion: str = "aic") -> dict:
    """GJR-GARCH 方程（vol='GARCH', o=1，含杠杆项 gamma，捕捉 Engle-Ng 符号偏差）。

    输入残差，返回方差阶 + arch result + 标准化残差。
    """
    return _fit_vol(_clean(resid, "resid"), "GJR", p_max, q_max, criterion)


# ════════════════════════════════════════════════════════════
# 三流程编排器
# ════════════════════════════════════════════════════════════
def flow_a(
    s: pd.Series,
    mean_eq: str,
    *,
    max_p: int = 3,
    max_q: int = 3,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> FitSummary:
    """均值方程(ARMA/ARFIMA) + 不变方差。残差 LB 判定。"""
    if mean_eq == "ARFIMA":
        m = fit_arfima_mean(s, max_p, max_q, criterion, forecast_steps)
        order, d, model_type = m["order"], m["d"], "ARFIMA"
    else:
        m = fit_arma_mean(s, max_p, max_q, criterion, forecast_steps)
        order, d, model_type = m["order"], None, "ARMA"

    resid_lb = _ljung_box(m["resid"])
    passed = _lb_passed(resid_lb)
    reason = (
        "残差（创新）无显著自相关，均值方程拟合充分"
        if passed else
        "残差仍存在自相关，建议提高阶数或引入方差方程"
    )
    fc = m["forecast"]
    return FitSummary(
        model_type=model_type,
        order=order,
        criterion=criterion,
        params=m["params"],
        aic=m["aic"],
        bic=m["bic"],
        n_obs=int(len(s)),
        resid_lb=resid_lb,
        std_resid_lb=None,
        sq_std_resid_lb=None,
        passed=passed,
        reason=reason,
        fitted=m["fitted"],
        forecast_mean=fc,
        forecast_index=list(range(len(s), len(s) + len(fc))),
        resid=m["resid"],
        mean_equation=mean_eq,
        variance_equation="Constant",
        flow="flow_a",
        d=d,
    )


def flow_b(
    s: pd.Series,
    var_eq: str,
    *,
    p_max: int = 2,
    q_max: int = 2,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> FitSummary:
    """常数均值 + 方差方程(GARCH/GJR)。标准化残差双 LB 判定。"""
    cm = fit_constant_mean(s)
    vf = fit_garch_var(cm["resid"], p_max, q_max, criterion) if var_eq == "GARCH" \
        else fit_gjr_var(cm["resid"], p_max, q_max, criterion)

    std_resid = vf["std_resid"]
    sq_std_resid = (std_resid ** 2).dropna()
    std_lb = _ljung_box(std_resid)
    sq_lb = _ljung_box(sq_std_resid)
    mean_ok = _lb_passed(std_lb)
    var_ok = _lb_passed(sq_lb)
    passed = mean_ok and var_ok
    reason = (
        f"均值方程(常数)标准化残差无自相关({mean_ok})；"
        f"方差方程({var_eq})标准化残差平方无自相关({var_ok})"
        if passed else
        f"均值充分={mean_ok}，方差充分={var_ok}；仍存在未吸收的序列相关或波动聚集"
    )

    fc = pd.Series(np.full(forecast_steps, cm["mu"]))
    params = {"mu": cm["mu"]}
    params.update({f"vol_{k}": _safe_float(v) for k, v in vf["arch_res"].params.items()})
    return FitSummary(
        model_type=var_eq,
        order=((0, 0), vf["vol_order"]),
        criterion=criterion,
        params=params,
        aic=vf["aic"],
        bic=vf["bic"],
        n_obs=int(len(s)),
        resid_lb=None,
        std_resid_lb=std_lb,
        sq_std_resid_lb=sq_lb,
        passed=passed,
        reason=reason,
        fitted=cm["fitted"],
        forecast_mean=fc,
        forecast_index=list(range(len(s), len(s) + len(fc))),
        resid=cm["resid"],
        mean_equation="Constant",
        variance_equation=var_eq,
        flow="flow_b",
        d=None,
    )


def flow_c(
    s: pd.Series,
    mean_eq: str,
    var_eq: str,
    *,
    max_p: int = 3,
    max_q: int = 3,
    p_max: int = 2,
    q_max: int = 2,
    criterion: str = "aic",
    forecast_steps: int = 20,
    max_iter: int = 3,
) -> FitSummary:
    """均值方程 + 方差方程（迭代两步法）。

    严格五步：
      1. 先定均值方程 (p,q)（假设常方差）→ 计算初始残差
      2. 在初始残差上定方差方程 (P,Q)
      3. 固定 (P,Q)，按 `mean_AIC + var_AIC` 重选均值 (p,q)（迭代至稳定或 max_iter）
      4. 用最佳 (p,q)+(P,Q) 最终拟合（均值取残差 → 残差上 GARCH/GJR）
      5. 标准化残差双 LB 验证

    注：两步法无精确联合似然，步骤 3 的 `mean_AIC+var_AIC` 为联合选阶启发式
    （真联合 MLE 仅 arch 的 AR-GARCH 支持，不含 MA 项，故 ARMA 均值仍走两步）。
    """
    vol_kind = "GJR" if var_eq == "GJR" else "GARCH"

    # 均值方程的工作序列与逐阶拟合器：ARFIMA 在差分序列上、ARMA 在原序列上
    if mean_eq == "ARFIMA":
        d, valid = _arfima_prep(s)
        base = valid

        def fit_mean(p, q, fs=0):
            return _fit_arfima_at(s, valid, p, q, d, forecast_steps=fs)

        def make_order(p, q):
            return (p, d, q)
    else:
        d = None
        base = s

        def fit_mean(p, q, fs=0):
            return _fit_arma_at(s, p, q, forecast_steps=fs)

        def make_order(p, q):
            return (p, q)

    # 1. 初始均值阶 (p,q)（在 base 上 AIC 选）+ 初始残差
    (ip, iq), _ = _select_arma_order(base, max_p, max_q, criterion)
    pq = (ip, iq)
    mm0 = fit_mean(ip, iq)
    # 2. 初始残差上定方差阶 (P,Q)
    vol_order, _ = _select_vol_order(mm0["resid"], vol_kind, p_max, q_max, criterion)
    P, Q = vol_order

    # 3. 固定 (P,Q)，迭代重选均值 (p,q)
    for _ in range(max_iter):
        best = None  # (metric, (p,q))
        for p in range(max_p + 1):
            for q in range(max_q + 1):
                if p == 0 and q == 0:
                    continue
                try:
                    mm_c = fit_mean(p, q)
                    vf_c = _fit_vol_at_order(mm_c["resid"], vol_kind, P, Q)
                except Exception:
                    continue
                metric = mm_c["aic"] + vf_c["aic"]
                if best is None or metric < best[0]:
                    best = (metric, (p, q))
        if best is None or best[1] == pq:
            break  # 收敛（最优均值阶不再变化）或无法拟合
        pq = best[1]

    # 4. 最佳 (p,q)+(P,Q) 最终拟合（带预测）
    mm = fit_mean(pq[0], pq[1], forecast_steps)
    vf = _fit_vol_at_order(mm["resid"], vol_kind, P, Q)

    # 5. 标准化残差双 LB 验证
    std_resid = vf["std_resid"]
    sq_std_resid = (std_resid ** 2).dropna()
    std_lb = _ljung_box(std_resid)
    sq_lb = _ljung_box(sq_std_resid)
    mean_ok = _lb_passed(std_lb)
    var_ok = _lb_passed(sq_lb)
    passed = mean_ok and var_ok
    reason = (
        f"均值方程({mean_eq}{make_order(pq[0], pq[1])})标准化残差无自相关({mean_ok})；"
        f"方差方程({var_eq}{(P, Q)})标准化残差平方无自相关({var_ok})"
        if passed else
        f"均值充分={mean_ok}，方差充分={var_ok}；联合模型未完全吸收动态结构"
    )

    fc = mm["forecast"]
    params = dict(mm["params"])
    params.update({f"vol_{k}": _safe_float(v) for k, v in vf["arch_res"].params.items()})
    return FitSummary(
        model_type=f"{mean_eq}+{var_eq}",
        order=(make_order(pq[0], pq[1]), (P, Q)),
        criterion=criterion,
        params=params,
        aic=mm["aic"],
        bic=mm["bic"],
        n_obs=int(len(s)),
        resid_lb=None,
        std_resid_lb=std_lb,
        sq_std_resid_lb=sq_lb,
        passed=passed,
        reason=reason,
        fitted=mm["fitted"],
        forecast_mean=fc,
        forecast_index=list(range(len(s), len(s) + len(fc))),
        resid=mm["resid"],
        mean_equation=mean_eq,
        variance_equation=var_eq,
        flow="flow_c",
        d=d,
    )


# ════════════════════════════════════════════════════════════
# flow_d：常数均值 + 不变方差（常数模型 / 随机游走漂移）
# ════════════════════════════════════════════════════════════
def flow_d(
    s: pd.Series,
    *,
    forecast_steps: int = 20,
) -> FitSummary:
    """常数均值 + 不变方差：拟合 μ 与 σ²（等价于价格的随机游走带漂移）。

    不再当作"白噪声跳过"——μ 即趋势 drift、σ² 即波动水平，是最朴素但完整的基线模型。
    残差 = r - μ；残差 Ljung-Box 判定常数模型是否充分（残差无自相关 → 通过）。
    """
    cm = fit_constant_mean(s)
    resid_lb = _ljung_box(cm["resid"])
    passed = _lb_passed(resid_lb)
    reason = (
        "残差（去均值）无显著自相关，常数均值+常数方差模型充分"
        if passed else
        "残差仍存在自相关，常数模型不充分，可能存在未捕捉的均值/方差动态结构"
    )
    fc = pd.Series(np.full(forecast_steps, cm["mu"]))
    return FitSummary(
        model_type="Constant",
        order=((0, 0), (0, 0)),
        criterion="-",
        params=cm["params"],
        aic=cm["aic"],
        bic=cm["bic"],
        n_obs=int(len(s)),
        resid_lb=resid_lb,
        std_resid_lb=None,
        sq_std_resid_lb=None,
        passed=passed,
        reason=reason,
        fitted=cm["fitted"],
        forecast_mean=fc,
        forecast_index=list(range(len(s), len(s) + len(fc))),
        resid=cm["resid"],
        mean_equation="Constant",
        variance_equation="Constant",
        flow="flow_d",
        d=None,
    )


# ════════════════════════════════════════════════════════════
# 统一入口：按 DiagnosticReport 的 flow 路由
# ════════════════════════════════════════════════════════════
def fit_model(
    diag,
    series: Any,
    *,
    max_p: int = 3,
    max_q: int = 3,
    p_max: int = 2,
    q_max: int = 2,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> FitSummary:
    """按 DiagnosticReport.flow 路由到对应流程（均值×方差 9 种组合全覆盖）。"""
    s = _clean(series, "series")
    flow = getattr(diag, "flow", None)
    if flow == "flow_d":
        return flow_d(s, forecast_steps=forecast_steps)
    if flow == "flow_a":
        return flow_a(s, diag.mean_equation, max_p=max_p, max_q=max_q,
                      criterion=criterion, forecast_steps=forecast_steps)
    if flow == "flow_b":
        return flow_b(s, diag.variance_equation, p_max=p_max, q_max=q_max,
                      criterion=criterion, forecast_steps=forecast_steps)
    if flow == "flow_c":
        return flow_c(s, diag.mean_equation, diag.variance_equation,
                      max_p=max_p, max_q=max_q, p_max=p_max, q_max=q_max,
                      criterion=criterion, forecast_steps=forecast_steps)
    raise ValueError(f"unknown flow: {flow!r}")


__all__ = [
    "FitSummary",
    "fit_constant_mean",
    "fit_arma_mean",
    "fit_arfima_mean",
    "fit_garch_var",
    "fit_gjr_var",
    "flow_a",
    "flow_b",
    "flow_c",
    "flow_d",
    "fit_model",
]
