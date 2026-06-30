"""时序建模脚本：ARMA、AR + GARCH、ARMA + GARCH。

严格按指定流程：
  ARMA          : AIC/BIC 选阶 → 估计 → 残差 → 残差 Ljung-Box → 判定
  AR + GARCH    : AIC/BIC 选 AR 阶 → 构建 AR+GARCH 并拟合 → 标准化残差
                  → 均值方程 Ljung-Box → 方差方程 Ljung-Box（残差平方）→ 综合判定
  ARMA + GARCH  : 流程同 AR+GARCH，均值方程为 ARMA（两步联合估计）

依赖：statsmodels（ARMA/ARIMA）、arch（GARCH）。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from statsmodels.stats.diagnostic import acorr_ljungbox
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

    model_type: str               # 'ARMA' / 'AR+GARCH' / 'ARMA+GARCH'
    order: tuple                  # ARMA -> (p,q)；GARCH 类 -> ((p,q),(P,Q))
    criterion: str                # 'aic' / 'bic'
    params: dict                  # 参数名 -> 值
    aic: float
    bic: float
    n_obs: int
    resid_lb: pd.DataFrame        # 残差 Ljung-Box（ARMA）/ 均值方程（GARCH 类）
    std_resid_lb: pd.DataFrame | None   # 标准化残差 Ljung-Box（GARCH 类均值方程）
    sq_std_resid_lb: pd.DataFrame | None  # 标准化残差平方 Ljung-Box（GARCH 类方差方程）
    passed: bool                  # 综合判定：残差/标准化残差是否已无自相关
    reason: str
    fitted: pd.Series = None      # in-sample 拟合均值
    forecast_mean: pd.Series = field(default_factory=pd.Series)  # 向前 forecast_mean_steps 的均值预测
    forecast_index: list = field(default_factory=list)
    resid: pd.Series = None       # 残差（用于报告/再检验）


# ════════════════════════════════════════════════════════════
# 公共工具
# ════════════════════════════════════════════════════════════
def _lb(df_lags_result) -> pd.DataFrame:
    """把 acorr_ljungbox 结果规整为 [lb_stat, lb_pvalue] DataFrame。"""
    return df_lags_result.rename(columns={"lb_stat": "lb_stat", "lb_pvalue": "lb_pvalue"})


def _ljung_box(series: pd.Series, lags=LB_LAGS) -> pd.DataFrame:
    s = pd.Series(series).dropna().astype(float)
    lags = [int(l) for l in lags if l < len(s)]
    if not lags:
        return pd.DataFrame(columns=["lb_stat", "lb_pvalue"])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _lb(acorr_ljungbox(s, lags=lags, return_df=True))


def _lb_passed(lb_df: pd.DataFrame, significance: float = SIGNIFICANCE) -> bool:
    """通过 = 所有阶 p 值 > significance（残差无可检测自相关）。"""
    if lb_df is None or lb_df.empty:
        return True
    return bool((lb_df["lb_pvalue"] > significance).all())


# ════════════════════════════════════════════════════════════
# 6. ARMA 建模
# ════════════════════════════════════════════════════════════
def _select_arma_order(s: pd.Series, max_p: int, max_q: int, criterion: str):
    """6.1 用 AIC/BIC 在 (p,q) 网格上选最优阶。"""
    grid = []
    for p in range(max_p + 1):
        for q in range(max_q + 1):
            if p == 0 and q == 0:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    m = ARIMA(s, order=(p, 0, q)).fit()
                ic = m.aic if criterion == "aic" else m.bic
                grid.append((p, q, float(ic), m))
            except Exception:
                continue
    if not grid:
        raise RuntimeError("ARMA 选阶失败：所有阶数拟合均失败")
    grid.sort(key=lambda x: x[2])
    p, q, ic, model = grid[0]
    return (p, q), model


def fit_arma(
    series: Any,
    max_p: int = 5,
    max_q: int = 5,
    criterion: str = "aic",
    forecast_steps: int = 20,
) -> FitSummary:
    """ARMA 建模：选阶 → 估计 → 残差 → 残差 Ljung-Box → 判定。"""
    s = _clean(series, "series")
    (p, q), model = _select_arma_order(s, max_p, max_q, criterion)

    # 6.2 参数估计 / 6.3 残差
    resid = pd.Series(model.resid, index=s.index).dropna()
    fitted = pd.Series(model.fittedvalues, index=s.index).dropna()

    # 6.4 残差 Ljung-Box / 6.5 判定
    resid_lb = _ljung_box(resid)
    passed = _lb_passed(resid_lb)
    reason = (
        "残差在所选阶上无显著自相关，ARMA 拟合充分"
        if passed else
        "残差仍存在自相关，建议提高阶数或引入 GARCH"
    )

    # 预测
    try:
        fc = model.get_forecast(steps=forecast_steps)
        fc_mean = pd.Series(fc.predicted_mean.values, name="forecast")
    except Exception:
        fc_mean = pd.Series(dtype=float)

    params = {k: _safe_float(v) for k, v in model.params.items()}
    return FitSummary(
        model_type="ARMA",
        order=(p, q),
        criterion=criterion,
        params=params,
        aic=_safe_float(model.aic),
        bic=_safe_float(model.bic),
        n_obs=int(len(s)),
        resid_lb=resid_lb,
        std_resid_lb=None,
        sq_std_resid_lb=None,
        passed=passed,
        reason=reason,
        fitted=fitted,
        forecast_mean=fc_mean,
        forecast_index=list(range(len(s), len(s) + len(fc_mean))),
        resid=resid,
    )


# ════════════════════════════════════════════════════════════
# 公共：AR 阶数选择（用于 AR+GARCH）
# ════════════════════════════════════════════════════════════
def _select_ar_order(s: pd.Series, max_ar: int, criterion: str) -> int:
    """7.1 用 AIC/BIC 选 AR 阶（ARIMA(p,0,0)），返回最优 p。"""
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


# ════════════════════════════════════════════════════════════
# 7. AR + GARCH 建模
# ════════════════════════════════════════════════════════════
def fit_ar_garch(
    series: Any,
    max_ar: int = 5,
    criterion: str = "aic",
    garch_p: int = 1,
    garch_q: int = 1,
    forecast_steps: int = 20,
) -> FitSummary:
    """AR + GARCH：选 AR 阶 → 构建 → 拟合 → 标准化残差 → 均值/方差方程 LB → 综合判定。"""
    from arch import arch_model

    s = _clean(series, "series")
    # 7.1 选 AR 阶
    ar_lag = _select_ar_order(s, max_ar, criterion)

    # 7.2 构建 AR(p) + GARCH(p,q) 并拟合
    am = arch_model(
        s, mean="AR", lags=ar_lag, vol="GARCH",
        p=garch_p, q=garch_q, dist="normal", rescale=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = am.fit(disp="off", show_warning=False)

    resid = pd.Series(res.resid, index=s.index)
    cond_vol = pd.Series(res.conditional_volatility, index=s.index)
    fitted = (s - resid).dropna()

    # 7.3 标准化残差
    std_resid = (resid / cond_vol).replace([np.inf, -np.inf], np.nan).dropna()
    sq_std_resid = (std_resid ** 2).dropna()

    # 7.4 均值方程 LB / 7.5 方差方程 LB（标准化残差平方）
    std_lb = _ljung_box(std_resid)
    sq_lb = _ljung_box(sq_std_resid)

    # 7.6 综合判定
    mean_ok = _lb_passed(std_lb)
    var_ok = _lb_passed(sq_lb)
    passed = mean_ok and var_ok
    reason = (
        f"均值方程标准化残差无自相关({mean_ok})；方差方程标准化残差平方无自相关({var_ok})"
        if passed else
        f"均值方程充分={mean_ok}，方差方程充分={var_ok}；仍存在未吸收的序列相关或波动聚集"
    )

    # 预测
    fc_mean = _arch_mean_forecast(res, forecast_steps)
    params = {k: _safe_float(v) for k, v in res.params.items()}

    return FitSummary(
        model_type="AR+GARCH",
        order=((ar_lag, 0), (garch_p, garch_q)),
        criterion=criterion,
        params=params,
        aic=_safe_float(res.aic),
        bic=_safe_float(res.bic),
        n_obs=int(len(s)),
        resid_lb=None,           # ARMA 类用 resid_lb；GARCH 类用 std_resid_lb / sq
        std_resid_lb=std_lb,
        sq_std_resid_lb=sq_lb,
        passed=passed,
        reason=reason,
        fitted=fitted,
        forecast_mean=fc_mean,
        forecast_index=list(range(len(s), len(s) + len(fc_mean))),
        resid=resid,
    )


# ════════════════════════════════════════════════════════════
# 8. ARMA + GARCH 建模（两步联合估计）
# ════════════════════════════════════════════════════════════
def fit_arma_garch(
    series: Any,
    max_p: int = 4,
    max_q: int = 4,
    criterion: str = "aic",
    garch_p: int = 1,
    garch_q: int = 1,
    forecast_steps: int = 20,
) -> FitSummary:
    """ARMA + GARCH：选 ARMA 阶 → ARMA 拟合取残差 → 残差上拟合 GARCH → 标准化残差双 LB。"""
    from arch import arch_model

    s = _clean(series, "series")
    # 7.1 选 ARMA 阶
    (p, q), arma_model = _select_arma_order(s, max_p, max_q, criterion)

    # 7.2 构建 ARMA(p,q) + GARCH(p,q) —— 两步：先 ARMA 拿残差，再 GARCH
    arma_resid = pd.Series(arma_model.resid, index=s.index).dropna()
    am = arch_model(
        arma_resid, mean="Zero", vol="GARCH",
        p=garch_p, q=garch_q, dist="normal", rescale=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = am.fit(disp="off", show_warning=False)

    cond_vol = pd.Series(res.conditional_volatility, index=arma_resid.index)
    fitted = pd.Series(arma_model.fittedvalues, index=s.index).dropna()

    # 7.3 标准化残差
    std_resid = (arma_resid / cond_vol).replace([np.inf, -np.inf], np.nan).dropna()
    sq_std_resid = (std_resid ** 2).dropna()

    # 7.4 / 7.5 双 LB
    std_lb = _ljung_box(std_resid)
    sq_lb = _ljung_box(sq_std_resid)

    # 7.6 综合判定
    mean_ok = _lb_passed(std_lb)
    var_ok = _lb_passed(sq_lb)
    passed = mean_ok and var_ok
    reason = (
        f"均值方程（ARMA({p},{q})）标准化残差无自相关({mean_ok})；"
        f"方差方程标准化残差平方无自相关({var_ok})"
        if passed else
        f"均值方程充分={mean_ok}，方差方程充分={var_ok}；联合模型未完全吸收动态结构"
    )

    # 预测：用 ARMA 做均值预测
    try:
        fc = arma_model.get_forecast(steps=forecast_steps)
        fc_mean = pd.Series(fc.predicted_mean.values, name="forecast")
    except Exception:
        fc_mean = pd.Series(dtype=float)

    params = {f"arma_{k}": _safe_float(v) for k, v in arma_model.params.items()}
    params.update({f"garch_{k}": _safe_float(v) for k, v in res.params.items()})

    return FitSummary(
        model_type="ARMA+GARCH",
        order=((p, q), (garch_p, garch_q)),
        criterion=criterion,
        params=params,
        aic=_safe_float(arma_model.aic),
        bic=_safe_float(arma_model.bic),
        n_obs=int(len(s)),
        resid_lb=None,
        std_resid_lb=std_lb,
        sq_std_resid_lb=sq_lb,
        passed=passed,
        reason=reason,
        fitted=fitted,
        forecast_mean=fc_mean,
        forecast_index=list(range(len(s), len(s) + len(fc_mean))),
        resid=arma_resid,
    )


# ════════════════════════════════════════════════════════════
# 0. 随机游走建模（ARIMA(0,1,0) with drift）
# ════════════════════════════════════════════════════════════
def fit_random_walk(
    series: Any,
    forecast_steps: int = 20,
) -> FitSummary:
    """随机游走（带漂移）建模：在收益率空间即常数均值 μ + 白噪声。

    等价于对价格拟合 ARIMA(0,1,0) with drift：P_t = P_{t-1} + μ + ε_t。
    输入约定为收益率/差分序列（与 fit_arma 等一致）。
    """
    s = _clean(series, "series")
    mu = float(s.mean())
    resid = s - mu
    sigma2 = float((resid ** 2).mean())  # MLE 方差
    n = len(s)

    # 高斯似然下的 AIC/BIC（参数：μ, σ²）
    if sigma2 > 0:
        logl = -0.5 * n * (np.log(2 * np.pi) + np.log(sigma2) + 1.0)
        aic = float(2 * 2 - 2 * logl)
        bic = float(2 * np.log(n) - 2 * logl)
    else:
        aic = bic = float("nan")

    fitted = pd.Series(mu, index=s.index)
    fc = pd.Series(np.full(forecast_steps, mu))

    # 残差 Ljung-Box（随机游走应通过；未通过提示仍有结构）
    resid_lb = _ljung_box(resid)
    passed = _lb_passed(resid_lb)
    reason = (
        "残差（去均值后）无显著自相关，随机游走假设成立"
        if passed else
        "残差仍存在自相关，随机游走可能不充分，建议尝试 ARMA/GARCH"
    )

    return FitSummary(
        model_type="RandomWalk",
        order=(0, 1, 0),
        criterion="-",
        params={"drift(mu)": mu, "sigma2": sigma2},
        aic=aic,
        bic=bic,
        n_obs=int(n),
        resid_lb=resid_lb,
        std_resid_lb=None,
        sq_std_resid_lb=None,
        passed=passed,
        reason=reason,
        fitted=fitted,
        forecast_mean=fc,
        forecast_index=list(range(n, n + len(fc))),
        resid=resid,
    )


# ════════════════════════════════════════════════════════════
# 统一入口：根据检测结果自动建模
# ════════════════════════════════════════════════════════════
def fit_model(model_type: str, series: Any, **kwargs) -> FitSummary | None:
    """按模型类型路由到对应拟合函数；'RandomWalk' 走 ARIMA(0,1,0)。"""
    if model_type in ("none", "RandomWalk"):
        # 兼容旧 'none'：价格序列走 ARIMA(0,1,0)；已是收益率则等价于常数漂移
        return fit_random_walk(series, **kwargs)
    if model_type == "ARMA":
        return fit_arma(series, **kwargs)
    if model_type == "AR+GARCH":
        return fit_ar_garch(series, **kwargs)
    if model_type == "ARMA+GARCH":
        return fit_arma_garch(series, **kwargs)
    raise ValueError(f"unknown model_type: {model_type!r}")


# ════════════════════════════════════════════════════════════
# arch 均值预测辅助
# ════════════════════════════════════════════════════════════
def _arch_mean_forecast(res, steps: int) -> pd.Series:
    try:
        fcast = res.forecast(horizon=steps, reindex=False)
        mean_df = fcast.mean
        row = mean_df.iloc[-1]
        return pd.Series(row.values, name="forecast")
    except Exception:
        return pd.Series(dtype=float)


__all__ = [
    "FitSummary",
    "fit_random_walk",
    "fit_arma",
    "fit_ar_garch",
    "fit_arma_garch",
    "fit_model",
]
