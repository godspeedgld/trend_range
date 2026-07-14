"""自适应卡尔曼滤波（纯 numpy）—— 二阶(2态)与三阶(3态)，Myers-Tapley 滑动窗口噪声自适应。

模型族（F/H/G 时不变，噪声 Q/R 自适应）：
  二阶 kalman_filter_adaptive_2：状态 [level, velocity]            （一阶 Taylor：价格+速度）
  三阶 kalman_filter_adaptive_3：状态 [level, velocity, accel]     （二阶 Taylor：价格+速度+加速度）

噪声自适应（Myers-Tapley，长度 win 的滑动窗口；二阶/三阶方法相同，只是维数）：
    新息 ν_t = z_t − H·x⁻_t                       → R = Var_win(ν)        (标量)
    过程噪声样本 q_t = x⁺_t − F·x⁺_{t-1}，
        qq_i = q_t[i] / g_i                       → Q = Cov_win(qq)       (n×n)

每步：predict → 新息 → 自适应 Q,R → 增益 → 更新，逐点输出各状态 + R + Q。
依赖：numpy、pandas。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd


# ════════════════════════════════════════════════════════════
# 二阶（2 态：[level, velocity]）
# ════════════════════════════════════════════════════════════
def kalman_filter_adaptive_2(
    series: pd.Series,
    win: int,
    *,
    g1: float = 1.0,
    g2: float = 1.0,
    dt: float = 1.0,
    r_min: Optional[float] = None,
    p0_scale: float = 10.0,
    q_init_scale: float = 1e-3,
) -> pd.DataFrame:
    """二阶自适应卡尔曼：状态 [level, velocity]，diag(g1,g2) 噪声分布。

    Returns: DataFrame[level, velocity, R, q11, q12, q22]（index 对齐输入）。
    """
    return _run(series, win, dim=2, gs=(g1, g2), dt=dt, r_min=r_min,
                p0_scale=p0_scale, q_init_scale=q_init_scale)


# ════════════════════════════════════════════════════════════
# 三阶（3 态：[level, velocity, accel]）
# ════════════════════════════════════════════════════════════
def kalman_filter_adaptive_3(
    series: pd.Series,
    win: int,
    *,
    g1: float = 1.0,
    g2: float = 1.0,
    g3: float = 1.0,
    dt: float = 1.0,
    r_min: Optional[float] = None,
    p0_scale: float = 10.0,
    q_init_scale: float = 1e-3,
) -> pd.DataFrame:
    """三阶自适应卡尔曼：状态 [level, velocity, accel]，diag(g1,g2,g3) 噪声分布。

    模型（匀加速）：level_k=level+vel·dt+½·acc·dt²；vel_k=vel+acc·dt；acc_k=acc。
    二阶 Taylor 预测：p(t+h)=level+vel·h·dt+½·acc·(h·dt)²。

    Returns: DataFrame[level, velocity, acceleration, R, q11,q12,q13,q22,q23,q33]。
    """
    return _run(series, win, dim=3, gs=(g1, g2, g3), dt=dt, r_min=r_min,
                p0_scale=p0_scale, q_init_scale=q_init_scale)


# ════════════════════════════════════════════════════════════
# 通用实现（dim=2 或 3）
# ════════════════════════════════════════════════════════════
def _F(dt: float, dim: int) -> np.ndarray:
    """状态转移矩阵（运动学积分）。"""
    if dim == 2:
        return np.array([[1.0, dt], [0.0, 1.0]])
    # dim == 3：匀加速，含 ½·acc·dt²
    return np.array([[1.0, dt, 0.5 * dt * dt],
                     [0.0, 1.0, dt],
                     [0.0, 0.0, 1.0]])


def _run(series, win, *, dim, gs, dt, r_min, p0_scale, q_init_scale) -> pd.DataFrame:
    s = pd.Series(series).astype(float).dropna()
    z = s.to_numpy(dtype=float)
    n = len(z)
    state_names = ["level", "velocity"] if dim == 2 else ["level", "velocity", "acceleration"]
    qcols = [f"q{i+1}{j+1}" for i in range(dim) for j in range(i, dim)]  # 上三角（含对角）
    cols = state_names + ["R"] + qcols
    if n == 0:
        return pd.DataFrame({c: pd.Series(dtype=float) for c in cols})

    F = _F(dt, dim)
    H = np.zeros((1, dim)); H[0, 0] = 1.0                       # 只观测 level
    gs = np.array(gs[:dim], dtype=float)
    gs = np.where(np.abs(gs) > 1e-12, gs, 1e-12)                # 防 0 除
    G = np.diag(gs)
    I = np.eye(dim)

    var0 = float(np.var(z)) or 1.0
    rmin = r_min if r_min is not None else max(var0 * 1e-8, 1e-12)
    win = max(int(win), 3)
    warmup = min(win // 2, 20)   # 噪声自适应启用门槛（窗口半满，至多 20）

    x = np.zeros(dim); x[0] = z[0]                              # x⁺(0) = [z0, 0, 0...]
    P = np.diag([var0 * p0_scale] * dim)
    R = var0
    Q = np.diag([var0 * q_init_scale] * dim)

    out = {c: np.full(n, np.nan) for c in cols}
    innov_win = deque(maxlen=win)
    q_win = deque(maxlen=win)
    x_post = deque(maxlen=win)

    for t in range(n):
        if t > 0:                                                # predict
            x = F @ x
            P = F @ P @ F.T + G @ Q @ G.T
        nu = z[t] - (H @ x)[0]                                   # 新息
        innov_win.append(nu)
        if len(innov_win) > warmup:                              # 自适应 R（warmup 后启用）
            R = max(float(np.var(np.array(innov_win), ddof=1)), rmin)
        S = (H @ P @ H.T)[0, 0] + R
        K = (P @ H.T).ravel() / S
        x = x + K * nu                                           # update
        KH = np.outer(K, H.ravel())                              # Joseph 形式协方差更新（数值稳定、保 PSD）
        P = (I - KH) @ P @ (I - KH).T + np.outer(K, K) * R
        x_post.append(x.copy())
        if len(x_post) >= 2:                                     # 过程噪声样本（与 x_post 同步）
            qv = x_post[-1] - F @ x_post[-2]
            q_win.append(qv / gs)
        if len(q_win) > warmup:                                  # 自适应 Q（warmup 后；对称化+jitter 防奇异）
            Qc = np.cov(np.array(q_win).T, ddof=1)
            if Qc.shape == (dim, dim) and np.all(np.isfinite(Qc)):
                Q = (Qc + Qc.T) / 2.0 + np.eye(dim) * 1e-8
        # 输出
        for i, name in enumerate(state_names):
            out[name][t] = x[i]
        out["R"][t] = R
        k = 0
        for i in range(dim):                                     # Q 上三角（含对角）
            for j in range(i, dim):
                out[qcols[k]][t] = Q[i, j]
                k += 1

    return pd.DataFrame(out, index=s.index)


# 兼容旧名（已弃用，建议用 kalman_filter_adaptive_2）
def kalman_filter_adaptive(*args, **kwargs):
    """已弃用别名 → kalman_filter_adaptive_2。"""
    return kalman_filter_adaptive_2(*args, **kwargs)


__all__ = ["kalman_filter_adaptive_2", "kalman_filter_adaptive_3", "kalman_filter_adaptive"]
