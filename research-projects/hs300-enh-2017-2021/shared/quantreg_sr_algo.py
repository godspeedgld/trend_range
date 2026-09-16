"""quantreg_sr_algo — 分位数回归压力/支撑线算法（Lang et al. 2012 路线）。

来源：渤海证券《压力线与支撑线的识别算法及应用——指数技术择时系列之一》(2022-09-29, 祝涛)
对其引用的 Lang 等（2012）《Pattern recognition and prediction in equity market》方法的实现；
完整复现包：replication/渤海证券-指数技术择时之一-压力线与支撑线的识别算法及应用/
（2026-09-08 复现，含实证：倒U/形态分层/忠实vs因果对照）。

与 plateau_algo_v1~v4（水平带聚集范式）是完全不同的阻力/支撑算法：
  plateau 家族 = 转折点价格聚集成分位数带（水平线，无方向）；
  本模块     = 局部极值点集上的分位数回归（有斜率的趋势线，可升可降）。

算法四步（研报 §4.1）：
  1) 局部极值：w=5，t 为 [t-w,t+w] 内最大（小）值 → 局部高（低）点（中心窗口）
  2) 分位数回归：回溯窗 N=120，窗口首日归一 100；高点 τ=0.9 → 压力线（斜率 p1），
     低点 τ=0.1 → 支撑线（斜率 p2）；线值取窗口末端 x=N-1
  3) 形态分类（渤海研报表1/表2）：(p1,p2) 斜率区间 → 6 持续形态 + 5 通道形态
     （斜率单位 = 初始价 %/日；横盘与通道重叠处取通道优先）
  4) 突破事件：close[t] > R_t 且 close[t-1] <= R_{t-1}（上穿，两日各自滚动拟合）

两种口径（重要）：
  faithful=False → causal=False：窗口内全部中心化极值（对齐研报统计；
                    ⚠️ 末端 w 日内的极值用了未来确认，含前视，只用于统计复现）
  causal=True：仅用已确认极值（u+w <= 窗口末端），实盘/回测可用口径。
  （复现实测：研报窗 20 日突破收益 忠实 +0.63% vs 因果 -0.17%，前视效应显著）

用法：
  from quantreg_sr_algo import rolling_lines, breakout_signals, DEFAULT_PARAMS
  lines = rolling_lines(df, causal=True)          # df: 单标的，index 任意，含 close
  sig   = breakout_signals(lines, df["close"])    # 含 breakout / dur_pattern / chan_pattern
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.regression.quantile_regression import QuantReg

# ── 默认参数（研报 §4.1）──
DEFAULT_PARAMS = {
    "N": 120,          # 回溯期（交易日）
    "w": 5,            # 局部极值半窗口
    "tau_r": 0.9,      # 压力线分位值
    "tau_s": 0.1,      # 支撑线分位值
    "min_pts": 4,      # 每侧极值最少点数（低于则当日无线；Lang 原文 10、研报示例 6，此处取 4）
}

# 表1 持续形态（互斥）：形态名 -> (p1_lo, p1_hi, p2_lo, p2_hi)。
# 斜率阈值可整体作为参数替换（classify_duration(patterns=...)），默认=研报表1。
DURATION_PATTERNS = {
    "上升三角形": (-0.05, 0.05, 0.05, 0.15),
    "对称三角形": (-0.15, -0.05, 0.05, 0.15),
    "下降三角形": (-0.05, 0.05, -0.15, -0.05),
    "矩形":       (-0.05, 0.05, -0.05, 0.05),
    "旗形":       (-0.15, -0.05, -0.15, -0.05),
    "喇叭形":     (0.05, np.inf, -np.inf, -0.05),
}

# 表2 通道形态的可调阈值（默认=研报）：横盘区间双斜率 ∈ [flat_lo, flat_hi)；
# 四类通道仅由符号与 p1/p2 相对大小决定，无可调阈值。
DEFAULT_CHAN_BOUNDS = {"flat_lo": -0.15, "flat_hi": 0.05}


def local_extrema(y: np.ndarray, w: int, causal: bool = False):
    """窗口内局部高/低点位置（中心 [u-w, u+w] 极值）。

    causal=True 时只保留 u + w <= 窗口末端 的已确认极值；False = 全部中心化极值（忠实口径，
    末端极值含未来确认）。相等极值只取最左一个（平台不重复计点）。
    返回 (high_pos, low_pos)，均为 0..N-1。
    """
    n = len(y)
    hi, lo = [], []
    for u in range(n):
        if causal and u + w > n - 1:
            break
        a, b = max(0, u - w), min(n - 1, u + w)
        seg = y[a:b + 1]
        if y[u] == seg.max() and (u == a or y[u] > y[a:u].max()):
            hi.append(u)
        if y[u] == seg.min() and (u == a or y[u] < y[a:u].min()):
            lo.append(u)
    return np.array(hi), np.array(lo)


def _qr_line(x: np.ndarray, y: np.ndarray, tau: float, x_end: float):
    """分位数回归 y ~ x（含截距）。返回 (斜率, 线在 x_end 处的取值)。"""
    X = np.column_stack([np.ones(len(x)), x])
    res = QuantReg(y, X).fit(q=tau, max_iter=200)
    b0, b1 = res.params
    return float(b1), float(b0 + b1 * x_end)


def fit_window(close_win: np.ndarray, params: dict | None = None, causal: bool = False) -> dict:
    """对一个窗口（原始收盘价，长度 N）拟合压力/支撑线。

    返回 dict(p1, p2, R, S)：p1/p2 斜率（初始价 %/日），R/S 线在窗口末端（=当日）
    的取值（原始价格单位）。极值点不足 min_pts → 全 NaN。
    """
    p = params or DEFAULT_PARAMS
    N = len(close_win)
    y_all = close_win / close_win[0] * 100.0            # 首日归一 100（消量纲）
    hi, lo = local_extrema(y_all, p["w"], causal=causal)
    out = {"p1": np.nan, "p2": np.nan, "R": np.nan, "S": np.nan}
    if len(hi) >= p["min_pts"] and len(lo) >= p["min_pts"]:
        p1, r_norm = _qr_line(hi.astype(float), y_all[hi], p["tau_r"], x_end=N - 1)
        p2, s_norm = _qr_line(lo.astype(float), y_all[lo], p["tau_s"], x_end=N - 1)
        out.update(p1=p1, p2=p2,
                   R=r_norm / 100.0 * close_win[0],
                   S=s_norm / 100.0 * close_win[0])
    return out


def classify_duration(p1: float, p2: float, patterns: dict | None = None) -> str:
    """(p1,p2) → 表1 六种持续形态之一；不落任何区间返回 '未分类'。

    patterns: 可选自定义斜率阈值 {形态名: (p1_lo, p1_hi, p2_lo, p2_hi)}，默认研报表1。
    """
    if not (np.isfinite(p1) and np.isfinite(p2)):
        return "未分类"
    for name, (a, b, c, d) in (patterns if patterns is not None else DURATION_PATTERNS).items():
        if (a <= p1 < b) and (c <= p2 < d):
            return name
    return "未分类"


def classify_channel(p1: float, p2: float, bounds: dict | None = None) -> str:
    """(p1,p2) → 表2 五种通道形态；先判四类通道，剩余且双斜率入横盘区记横盘。

    bounds: 可选 {"flat_lo": -0.15, "flat_hi": 0.05}（默认研报表2 的横盘区间）。
    """
    if not (np.isfinite(p1) and np.isfinite(p2)):
        return "未分类"
    b = bounds if bounds is not None else DEFAULT_CHAN_BOUNDS
    if p1 > 0 and p2 > 0:
        return "上升通道收敛" if p1 < p2 else "上升通道发散"
    if p1 < 0 and p2 < 0:
        return "下降通道收敛" if p1 < p2 else "下降通道发散"
    if b["flat_lo"] < p1 < b["flat_hi"] and b["flat_lo"] < p2 < b["flat_hi"]:
        return "横盘"
    return "未分类"


def rolling_lines(df: pd.DataFrame, params: dict | None = None, causal: bool = False) -> pd.DataFrame:
    """逐日滚动拟合（窗口 = 截至 t 的 N 根 bar）。

    df: 单标的 OHLC（或至少含 close），index 升序。
    返回 DataFrame(index 同 df, columns=[p1,p2,R,S])，前 N-1 日为 NaN。
    """
    p = params or DEFAULT_PARAMS
    N, close = p["N"], df["close"].to_numpy(float)
    rows = []
    for t in range(N - 1, len(close)):
        r = fit_window(close[t - N + 1:t + 1], p, causal)
        rows.append(r)
    return pd.DataFrame(rows, index=df.index[N - 1:])


def breakout_signals(lines: pd.DataFrame, close: pd.Series,
                     patterns: dict | None = None, chan_bounds: dict | None = None) -> pd.DataFrame:
    """在 rolling_lines 结果上判突破事件 + 形态标签。

    突破（上穿）：close[t] > R_t 且 close[t-1] <= R_{t-1}（两日各自的滚动拟合线值）。
    patterns / chan_bounds：可选自定义斜率阈值（透传给 classify_*，默认研报表1/表2）。
    返回列：p1,p2,R,S,close,breakout,dur_pattern,chan_pattern。
    """
    out = lines.copy()
    out["close"] = close.reindex(lines.index)
    out["breakout"] = (out["close"] > out["R"]) & (out["close"].shift(1) <= out["R"].shift(1))
    out["dur_pattern"] = [classify_duration(a, b, patterns) for a, b in zip(out["p1"], out["p2"])]
    out["chan_pattern"] = [classify_channel(a, b, chan_bounds) for a, b in zip(out["p1"], out["p2"])]
    return out


def scan(df: pd.DataFrame, params: dict | None = None, causal: bool = False) -> pd.DataFrame:
    """便捷入口：rolling_lines + breakout_signals 一步到位。"""
    return breakout_signals(rolling_lines(df, params, causal), df["close"])
