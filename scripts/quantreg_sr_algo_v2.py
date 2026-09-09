"""quantreg_sr_algo_v2 — 分位数回归压力/支撑线 v2：动态窗口（LOO 离群截断）。

v1（quantreg_sr_algo.py，冻结不动）用固定 N=120 窗。痛点：窗口横跨 regime 急切换
（如 2016-01 熔断）时，τ=0.9/0.1 线被单一离群转折点钉住（实测一 点使斜率翻号 724%）。

v2 机制（analysis_013 更新四，2026-09-09，用户设计+修正）：
  1) 从当前 t 向前取 ≤N_max=120 根 bar 为基础窗
  2) 因果口径找局部高/低点；对每侧做 **LOO（留一法）离群检测**：
     点 > 其余点 mean + k×σ 判高离群（低点对称：< mean − k×σ）；每侧 ≥5 点才检测
  3) 截断边界 = 最新被标记离群点（高点/低点合并取最近），窗口截到该点之后重拟合
  4) **只向过去截**：截断后窗 < N_min=60 → 放弃截断（回退当前窗）——近期"离群"
     （加速趋势的合法新高）因此不会破坏窗口，由 N_min 天然兜底
  5) ≤2 轮迭代；高低点各自 ≥min_pts=3 即可拟合（两侧数量可不等）
  6) 截断后点数不足 → 回退全窗再试，仍不足 → 当日无线（NaN）

输出在 v1 基础上增加：win_len（实际窗口长度）/ win0（窗口起点收盘价，供线段重建）/
truncated（当日是否发生截断）/ n_hi / n_lo。形态分类复用 v1（斜率阈值可参数化）。
注意：斜率阈值仍为"每日"单位，窗变短后"水平=全窗±6%"的经济语义会随 win_len 收缩
（形态标签分布漂移，见 records 讨论）。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from quantreg_sr_algo import _qr_line, breakout_signals, local_extrema  # noqa: F401  (breakout_signals 再导出)

# v2 默认参数
V2_PARAMS = {
    "N_max": 120,       # 基础窗上限
    "N_min": 60,        # 截断后最小窗长（兜底：只向过去截，不向现在截）
    "w": 5,             # 局部极值半窗
    "tau_r": 0.9,       # 压力线分位值
    "tau_s": 0.1,       # 支撑线分位值
    "min_pts": 3,       # 每侧最少点数（两侧可不等，用户指定 ≥3）
    "det_min": 5,       # 每侧做 LOO 检测的最少点数
    "k_sigma": 2.0,     # LOO 阈值倍数（> LOO mean + k×LOO σ）
    "rounds": 2,        # 截断迭代轮数上限
}


def _loo_flags(vals: np.ndarray, side: str, k: float) -> np.ndarray:
    """LOO 离群标记：对每个点，用其余点的 mean/σ 做阈值（掩蔽免疫）。返回布尔数组。"""
    n = len(vals)
    flags = np.zeros(n, dtype=bool)
    if n < 3:
        return flags
    for i in range(n):
        rest = np.delete(vals, i)
        m, s = rest.mean(), rest.std(ddof=1)
        if not np.isfinite(s) or s == 0:
            continue
        if side == "H":
            flags[i] = vals[i] > m + k * s
        else:
            flags[i] = vals[i] < m - k * s
    return flags


def _detect_boundary(y: np.ndarray, p: dict, causal: bool) -> int | None:
    """返回截断边界（窗口内位置 b：截到 b 之后，即保留 b+1..end）；无离群返回 None。"""
    hi, lo = local_extrema(y, p["w"], causal=causal)
    flagged = []
    if len(hi) >= p["det_min"]:
        flagged += list(hi[_loo_flags(y[hi], "H", p["k_sigma"])])
    if len(lo) >= p["det_min"]:
        flagged += list(lo[_loo_flags(y[lo], "L", p["k_sigma"])])
    return max(flagged) if flagged else None


def fit_window_v2(close_win: np.ndarray, params: dict | None = None, causal: bool = True) -> dict:
    """对一个基础窗（≤N_max 根，原始收盘价）动态拟合压力/支撑线。"""
    p = params or V2_PARAMS
    full = np.asarray(close_win, float)[-p["N_max"]:]
    win, truncated = full.copy(), False
    for _ in range(p["rounds"]):
        y = win / win[0] * 100.0
        b = _detect_boundary(y, p, causal)
        if b is None:
            break
        if len(win) - (b + 1) < p["N_min"]:     # 只向过去截：截完太短 → 放弃（近期离群不破坏窗）
            break
        win, truncated = win[b + 1:], True

    def _fit(w: np.ndarray) -> dict | None:
        y = w / w[0] * 100.0
        hi, lo = local_extrema(y, p["w"], causal=causal)
        if len(hi) < p["min_pts"] or len(lo) < p["min_pts"]:
            return None                          # 某侧点数不足（两侧阈值各自独立）
        out = {}
        out["p1"], r_norm = _qr_line(hi.astype(float), y[hi], p["tau_r"], x_end=len(w) - 1)
        out["p2"], s_norm = _qr_line(lo.astype(float), y[lo], p["tau_s"], x_end=len(w) - 1)
        out["R"] = r_norm / 100.0 * w[0]
        out["S"] = s_norm / 100.0 * w[0]
        yh, yl = local_extrema(y, p["w"], causal=causal)
        out["n_hi"], out["n_lo"] = len(yh), len(yl)
        return out

    res = _fit(win)
    if res is None and truncated:                # 截断后点数不足 → 回退全窗
        res, win, truncated = _fit(full), full, False
    if res is None:
        res = {"p1": np.nan, "p2": np.nan, "R": np.nan, "S": np.nan,
               "n_hi": 0, "n_lo": 0}
    res.update(win_len=len(win), win0=float(win[0]), truncated=truncated)
    return res


def rolling_lines_v2(df: pd.DataFrame, params: dict | None = None, causal: bool = True) -> pd.DataFrame:
    """逐日滚动动态窗口拟合。df: 单标的含 close，index 升序；返回含
    p1/p2/R/S/win_len/win0/truncated/n_hi/n_lo 的 DataFrame（前 N_max−1 日 NaN）。"""
    p = params or V2_PARAMS
    close = df["close"].to_numpy(float)
    rows = []
    for t in range(p["N_max"] - 1, len(close)):
        r = fit_window_v2(close[t - p["N_max"] + 1:t + 1], p, causal)
        r["date"] = df.index[t]
        rows.append(r)
    if not rows:                      # 样本短于 N_max（如次新股）→ 空表（列对齐）
        return pd.DataFrame(columns=["p1", "p2", "R", "S", "win_len", "win0",
                                     "truncated", "n_hi", "n_lo"])
    return pd.DataFrame(rows).set_index("date")


def scan_v2(df: pd.DataFrame, params: dict | None = None, causal: bool = True,
            patterns: dict | None = None, chan_bounds: dict | None = None) -> pd.DataFrame:
    """便捷入口：滚动拟合 + 突破/形态标签（复用 v1 breakout_signals，阈值可参数化）。"""
    return breakout_signals(rolling_lines_v2(df, params, causal), df["close"],
                            patterns=patterns, chan_bounds=chan_bounds)
