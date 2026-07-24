"""自适应卡尔曼滤波（纯 numpy）—— AdaptiveKalmanFilter 类。

F/H/G 时不变；Q/R 由 Myers-Tapley 滑动窗口自适应；Joseph 形式协方差更新（保 PSD）；
warmup 门控；Q 对称化 + jitter 防奇异。默认 3 阶（dim=3，状态 [level, velocity, accel]）。

两种模式：
  批量 fit(series)  —— 整段序列滚动估计，返回每点 DataFrame（回测/训练）。
  流量 update(z)    —— 逐个最新价更新，类持有状态，返回当步 dict（实盘）。

输出字段：level, velocity[, acceleration], predict_value(下一时刻预测), innov(新息), S(新息协方差)
         另含 R, q11..（内部噪声），p_var_level/p_var_vel/p_var_accel/p_trace（P 状态协方差诊断）。
依赖：numpy、pandas。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd


def _F(dt: float, dim: int) -> np.ndarray:
    """状态转移矩阵（运动学积分）。"""
    if dim == 2:
        return np.array([[1.0, dt], [0.0, 1.0]])
    return np.array([[1.0, dt, 0.5 * dt * dt],
                     [0.0, 1.0, dt],
                     [0.0, 0.0, 1.0]])


class AdaptiveKalmanFilter:
    """自适应卡尔曼滤波（F/H/G 时不变，Q/R 滑窗 Myers-Tapley 自适应）。

    两种使用模式：
      批量：kf.fit(series) → DataFrame（每点 level/velocity/accel/predict_value/innov/S/...）
      流量：kf = AdaptiveKalmanFilter(win=50); for p in live: out = kf.update(p)
            （类持有 x/P/Q/R 与窗口，逐点更新；首次 update 用 init_var 或价格量级启发式初始化）

    predict_value = 下一时刻价格预测 (H@F@x⁺)；innov = 本步新息 (z − H@x⁻)；S = 新息协方差。
    """

    def __init__(
        self,
        win: int = 50,
        *,
        dim: int = 3,
        g=(1.0, 1.0, 1.0),
        dt: float = 1.0,
        r_min: Optional[float] = None,
        p0_scale: float = 10.0,
        q_init_scale: float = 1e-3,
        init_var: Optional[float] = None,
    ):
        if dim not in (2, 3):
            raise ValueError("dim must be 2 or 3")
        self.dim = dim
        self.win = max(int(win), 3)
        self.dt = float(dt)
        self.warmup = min(self.win // 2, 20)
        self.F = _F(self.dt, dim)
        self.H = np.zeros((1, dim)); self.H[0, 0] = 1.0
        gs = np.array(g[:dim], dtype=float)
        gs = np.where(np.abs(gs) > 1e-12, gs, 1e-12)
        self.gs = gs
        self.G = np.diag(gs)
        self.I = np.eye(dim)
        self.p0_scale = p0_scale
        self.q_init_scale = q_init_scale
        self.init_var = init_var
        self._rmin = r_min
        self._reset()

    # ── 状态容器 ──────────────────────────────────────────
    def _reset(self) -> None:
        self.x: Optional[np.ndarray] = None
        self.P: Optional[np.ndarray] = None
        self.Q: Optional[np.ndarray] = None
        self.R: Optional[float] = None
        self.var0: Optional[float] = None
        self.rmin: Optional[float] = None
        self.innov_win = deque(maxlen=self.win)
        self.q_win = deque(maxlen=self.win)
        self.x_post = deque(maxlen=self.win)
        self.t = 0
        self._initialized = False

    @property
    def state_names(self) -> list[str]:
        return ["level", "velocity"] if self.dim == 2 else ["level", "velocity", "acceleration"]

    def _init_state(self, z0: float, var0: float) -> None:
        self.var0 = var0
        self.rmin = self._rmin if self._rmin is not None else max(var0 * 1e-8, 1e-12)
        self.x = np.zeros(self.dim); self.x[0] = float(z0)
        self.P = np.diag([var0 * self.p0_scale] * self.dim)
        self.R = var0
        self.Q = np.diag([var0 * self.q_init_scale] * self.dim)
        self._initialized = True

    # ── 流量模式：处理一个新观测 ─────────────────────────
    def update(self, z: float) -> dict:
        """处理最新价 z，更新内部状态，返回当步估计 dict。

        首次调用自动初始化（用 init_var 或价格量级启发式）；后续逐点滤波。
        """
        z = float(z)
        if not self._initialized:
            var0 = self.init_var if self.init_var is not None else max((z * 0.01) ** 2, 1e-6)
            self._init_state(z, var0)
            self.x_post.append(self.x.copy()); self.t += 1
            return self._outputs(predict_value=z, innov=0.0, S=self.R)

        # —— predict ——
        xm = self.F @ self.x
        Pm = self.F @ self.P @ self.F.T + self.G @ self.Q @ self.G.T
        pred_now = (self.H @ xm)[0]                       # 本步对当前价的预测
        innov = z - pred_now
        self.innov_win.append(innov)
        if len(self.innov_win) > self.warmup:             # 自适应 R（warmup 后）
            self.R = max(float(np.var(np.array(self.innov_win), ddof=1)), self.rmin)
        S = (self.H @ Pm @ self.H.T)[0, 0] + self.R

        # —— 增益 + Joseph 更新 ——
        K = (Pm @ self.H.T).ravel() / S
        self.x = xm + K * innov
        KH = np.outer(K, self.H.ravel())
        self.P = (self.I - KH) @ Pm @ (self.I - KH).T + np.outer(K, K) * self.R
        self.x_post.append(self.x.copy())

        # —— 自适应 Q（warmup 后；对称化 + jitter 防奇异）——
        if len(self.x_post) >= 2:
            qv = self.x_post[-1] - self.F @ self.x_post[-2]
            self.q_win.append(qv / self.gs)
        if len(self.q_win) > self.warmup:
            Qc = np.cov(np.array(self.q_win).T, ddof=1)
            if Qc.shape == (self.dim, self.dim) and np.all(np.isfinite(Qc)):
                self.Q = (Qc + Qc.T) / 2.0 + np.eye(self.dim) * 1e-8

        self.t += 1
        predict_value = (self.H @ (self.F @ self.x))[0]   # 下一时刻预测
        return self._outputs(predict_value=float(predict_value), innov=float(innov), S=float(S))

    def _outputs(self, predict_value: float, innov: float, S: float) -> dict:
        d = {n: float(self.x[i]) for i, n in enumerate(self.state_names)}
        d["predict_value"] = predict_value
        d["innov"] = innov
        d["S"] = S
        d["R"] = float(self.R)
        for i in range(self.dim):                          # Q 上三角（含对角）
            for j in range(i, self.dim):
                d[f"q{i+1}{j+1}"] = float(self.Q[i, j])
        # P 状态协方差诊断：对角 = 各状态方差，trace = 总不确定性
        d["p_var_level"] = float(self.P[0, 0])
        d["p_var_vel"] = float(self.P[1, 1])
        if self.dim >= 3:
            d["p_var_accel"] = float(self.P[2, 2])
        d["p_trace"] = float(np.trace(self.P))
        return d

    # ── 批量模式：整段序列滚动估计 ───────────────────────
    def fit(self, series) -> pd.DataFrame:
        """对整段序列逐点 update，返回 DataFrame（index 对齐输入）。

        每次调用重新初始化（_reset）。var0 默认用全序列方差；可用 init_var 覆盖。
        """
        s = pd.Series(series).astype(float).dropna()
        self._reset()
        if len(s) == 0:
            return pd.DataFrame()
        var0 = self.init_var if self.init_var is not None else (float(np.var(s.to_numpy())) or 1.0)
        self._init_state(float(s.iloc[0]), var0)
        self.x_post.append(self.x.copy()); self.t += 1
        rows = [self._outputs(predict_value=float(s.iloc[0]), innov=0.0, S=self.R)]
        for z in s.iloc[1:].to_numpy():
            rows.append(self.update(z))
        return pd.DataFrame(rows, index=s.index)


__all__ = ["AdaptiveKalmanFilter"]
