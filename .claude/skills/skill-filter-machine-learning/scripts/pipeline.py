"""Kalman + LSTM 管线 + 模型评估器。

KalmanLSTMPipeliner：
  卡尔曼做线性估计 → 特征工程（log_ret / vol_20 / std_innov）→ LSTM 估计非线性残差
  → Kalman 预测 + LSTM 残差 = 最终预测。支持 k 折 expanding-window 滚动训练（严格无未来数据）。
  批量 fit(data) → OOS 预测；流式 update(bar) → 一步推理。

ModelEvaluator：
  回归指标（MAE / MSE / RMSE / MAPE / R² / 方向准确度）+ plotly 可视化。

依赖：numpy、pandas、torch（间接经 LSTMPredictor）。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

from scripts.filter import AdaptiveKalmanFilter
from scripts.ml import LSTMPredictor


# ════════════════════════════════════════════════════════════
# KalmanLSTMPipeliner
# ════════════════════════════════════════════════════════════
class KalmanLSTMPipeliner:
    """卡尔曼线性估计 + LSTM 非线性残差校正管线。

    流程：
      1. AdaptiveKalmanFilter 在 close 上做线性估计（level/velocity/accel/predict_value/innov/S）。
      2. 残差 = close[t+1] − predict_value[t]（Kalman 一步预测误差）。
      3. 特征 = {log_ret, vol_20, std_innov}（均为 t 时刻已知量，无未来）。
      4. k 折 expanding-window 滚动训练 LSTM：X=特征, y=残差。
      5. 最终预测 = Kalman predict_value + LSTM 残差预测（OOS）。

    批量 fit(data) → dict(oos_pred, oos_kalman, kf_result, fold_results)。
    流式 update(bar) → dict(final, kalman_pred, lstm_residual, ...)。
    """

    def __init__(
        self,
        kalman_win: int = 50,
        kalman_dim: int = 3,
        lstm_lookback: int = 20,
        lstm_hidden: int = 64,
        lstm_layers: int = 2,
        n_folds: int = 5,
        val_split: float = 0.2,
        lstm_epochs: int = 50,
        lstm_batch: int = 64,
        device: str = "cuda",
    ):
        self.kalman_win = kalman_win
        self.kalman_dim = kalman_dim
        self.lstm_lookback = lstm_lookback
        self.lstm_hidden = lstm_hidden
        self.lstm_layers = lstm_layers
        self.n_folds = n_folds
        self.val_split = val_split
        self.lstm_epochs = lstm_epochs
        self.lstm_batch = lstm_batch
        self.device = device

        self._kf: Optional[AdaptiveKalmanFilter] = None
        self._lstm: Optional[LSTMPredictor] = None
        self._prev_close: Optional[float] = None
        self._ret_buf: deque = deque(maxlen=30)

    # ── 批量：k 折滚动训练 ────────────────────────────────
    def fit(self, data: pd.DataFrame, verbose: bool = True) -> dict:
        """批量管线。data 含 close（必需）+ 可选 OHLCV。返回 OOS 预测 + 各折详情。"""
        close = pd.Series(data["close"]).astype(float).dropna()

        # 1. 卡尔曼线性估计
        self._kf = AdaptiveKalmanFilter(win=self.kalman_win, dim=self.kalman_dim)
        kf_result = self._kf.fit(close)

        # 2. 残差（Kalman 一步预测误差）= close[t+1] − predict_value[t]
        #    作为 LSTM 的训练目标：y[t] 对齐特征 X[t]
        residual = close.shift(-1) - kf_result["predict_value"]  # y[t] = close[t+1] − pred_val[t]

        # 3. 特征（t 时刻已知量）
        log_ret = np.log(close).diff()
        vol_20 = log_ret.rolling(20).std()
        std_innov = kf_result["innov"] / np.sqrt(kf_result["S"].clip(lower=1e-12))
        X = pd.DataFrame({"log_ret": log_ret, "vol_20": vol_20, "std_innov": std_innov},
                         index=close.index)
        y = residual

        # 去除 NaN 行（特征 warmup + residual shift 末尾）
        valid = X.notna().all(axis=1) & y.notna()
        X = X[valid]
        y = y[valid]
        n = len(X)
        if n < 100:
            raise ValueError(f"有效数据太少({n}行)，无法 k 折训练")

        # 4. k 折 expanding-window 划分
        indices = np.arange(n)
        blocks = np.array_split(indices, self.n_folds + 1)

        oos_lstm_preds = []      # 每折 OOS LSTM 残差预测
        oos_indices = []          # 对应的原始 index
        fold_results = []

        for fold in range(1, self.n_folds + 1):
            train_idx = np.concatenate(blocks[:fold])
            test_idx = blocks[fold]
            if len(test_idx) < self.lstm_lookback + 1:
                continue

            X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
            X_te = X.iloc[test_idx]

            # 每折独立训练 LSTM
            lstm = LSTMPredictor(
                lookback=self.lstm_lookback, hidden=self.lstm_hidden,
                num_layers=self.lstm_layers, device=self.device,
            )
            lstm.fit(
                X_tr, y_tr,
                val_split=self.val_split, epochs=self.lstm_epochs,
                batch_size=self.lstm_batch, patience=10, verbose=verbose,
            )

            # OOS 预测
            pred = lstm.predict(X_te)
            oos_lstm_preds.append(pred)
            oos_indices.append(X_te.index)

            # 真实残差（test 块上的 actual residual）
            y_te = y.iloc[test_idx]
            corr = pred.corr(y_te) if pred.notna().any() else float("nan")
            fold_results.append({
                "fold": fold,
                "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                "test_start": str(X_te.index[0].date()) if hasattr(X_te.index[0], "date") else str(X_te.index[0]),
                "test_end": str(X_te.index[-1].date()) if hasattr(X_te.index[-1], "date") else str(X_te.index[-1]),
                "residual_corr": float(corr) if np.isfinite(corr) else None,
            })
            self._lstm = lstm  # 保留最后一折模型供流式

            if verbose:
                print(f"  fold {fold}: train={len(train_idx)} test={len(test_idx)} "
                      f"resid_corr={corr:.3f}")

        # 5. 聚合 OOS
        oos_lstm_residual = pd.concat(oos_lstm_preds).sort_index() if oos_lstm_preds else pd.Series(dtype=float)
        oos_idx = oos_lstm_residual.index
        oos_kalman_pred = kf_result["predict_value"].reindex(oos_idx)       # Kalman 预测
        oos_final = oos_kalman_pred + oos_lstm_residual                      # 最终预测
        oos_actual = close.shift(-1).reindex(oos_idx)                        # 实际 close[t+1]

        # warmstart 流式状态
        self._prev_close = float(close.iloc[-1])
        self._ret_buf = deque(log_ret.iloc[-30:].dropna().tolist(), maxlen=30)

        return {
            "oos_final": oos_final,            # Kalman + LSTM（最终预测，预测 close[t+1]）
            "oos_kalman": oos_kalman_pred,      # Kalman 单独预测
            "oos_lstm_residual": oos_lstm_residual,
            "oos_actual": oos_actual,           # 真实 close[t+1]
            "kf_result": kf_result,
            "fold_results": fold_results,
        }

    # ── 流式：一步推理 ────────────────────────────────────
    def update(self, bar: dict) -> dict:
        """流式推理。bar = {close, ...}。返回最终预测 + 各组件。"""
        if self._kf is None or self._lstm is None:
            raise RuntimeError("KalmanLSTMPipeliner.update() 需先调 fit()")

        close = float(bar["close"])
        kf_out = self._kf.update(close)

        # 特征
        log_ret = np.log(close) - np.log(self._prev_close) if self._prev_close and self._prev_close > 0 else 0.0
        self._prev_close = close
        self._ret_buf.append(log_ret)
        vol_20 = float(np.std(list(self._ret_buf)[-20:], ddof=1)) if len(self._ret_buf) >= 20 else float("nan")
        std_innov = kf_out["innov"] / np.sqrt(max(kf_out["S"], 1e-12))
        feat_row = {"log_ret": log_ret, "vol_20": vol_20, "std_innov": std_innov}

        lstm_resid = self._lstm.update(feat_row)

        final = kf_out["predict_value"] + lstm_resid if np.isfinite(lstm_resid) else kf_out["predict_value"]
        return {
            "final": final,               # 最终预测（预测下一根 close）
            "kalman_pred": kf_out["predict_value"],
            "lstm_residual": lstm_resid,
            "level": kf_out["level"],
            "velocity": kf_out["velocity"],
            "acceleration": kf_out.get("acceleration"),
            "innov": kf_out["innov"],
            "S": kf_out["S"],
        }


# ════════════════════════════════════════════════════════════
# ModelEvaluator
# ════════════════════════════════════════════════════════════
class ModelEvaluator:
    """模型评估器：回归指标 + 方向准确度 + plotly 可视化。"""

    def evaluate(self, y_true: pd.Series, y_pred: pd.Series) -> dict:
        """回归指标：MAE, MSE, RMSE, MAPE, R²。"""
        valid = y_true.notna() & y_pred.notna()
        yt = y_true[valid].to_numpy(dtype=float)
        yp = y_pred[valid].to_numpy(dtype=float)
        n = len(yt)
        if n == 0:
            return {"n": 0}
        err = yt - yp
        mae = float(np.mean(np.abs(err)))
        mse = float(np.mean(err ** 2))
        rmse = float(np.sqrt(mse))
        mape = float(np.mean(np.abs(err / yt[np.abs(yt) > 1e-12])) * 100) if np.any(np.abs(yt) > 1e-12) else float("nan")
        ss_res = float(np.sum(err ** 2))
        ss_tot = float(np.sum((yt - yt.mean()) ** 2))
        r2 = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
        return {"MAE": mae, "MSE": mse, "RMSE": rmse, "MAPE": mape, "R2": r2, "n": n}

    def evaluate_direction(self, y_true: pd.Series, y_pred: pd.Series) -> dict:
        """方向准确度：实际变化方向 vs 预测变化方向。"""
        valid = y_true.notna() & y_pred.notna()
        yt = y_true[valid]
        yp = y_pred[valid]
        if len(yt) < 2:
            return {"direction_accuracy": float("nan"), "n": 0}
        actual_dir = np.sign(yt.diff().dropna())
        pred_dir = np.sign(yp.diff().dropna())
        common = actual_dir.index.intersection(pred_dir.index)
        a = actual_dir.reindex(common).fillna(0)
        p = pred_dir.reindex(common).fillna(0)
        acc = float((a == p).mean())
        return {"direction_accuracy": acc, "n": int(len(common))}

    def plot(self, y_true: pd.Series, y_pred: pd.Series, path: str,
             title: str = "actual vs predicted") -> str:
        """plotly 交互图：双线(actual/predicted) + 误差直方图。"""
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go

        valid = y_true.notna() & y_pred.notna()
        yt = y_true[valid]
        yp = y_pred[valid]
        err = (yt - yp).dropna()

        fig = make_subplots(
            rows=2, cols=1, row_heights=[3, 1], shared_xaxes=False,
            vertical_spacing=0.12,
            subplot_titles=[title, "误差分布"],
        )
        fig.add_trace(go.Scatter(x=yt.index, y=yt.values, name="actual",
                                 line=dict(color="#7f8c8d", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=yp.index, y=yp.values, name="predicted",
                                 line=dict(color="#2980b9", width=1.2)), row=1, col=1)
        fig.add_trace(go.Histogram(x=err.values, name="error", marker_color="#e74c3c",
                                   nbinsx=50), row=2, col=1)
        fig.update_layout(hovermode="x unified", template="plotly_white",
                          height=600, margin=dict(l=50, r=30, t=50, b=40),
                          xaxis_rangeslider_visible=False)
        fig.write_html(path, include_plotlyjs="cdn")
        return path

    def compare(self, y_true: pd.Series, models: dict[str, pd.Series]) -> pd.DataFrame:
        """多模型对比。models = {'Kalman': series, 'Kalman+LSTM': series}。"""
        rows = []
        for name, y_pred in models.items():
            m = self.evaluate(y_true, y_pred)
            d = self.evaluate_direction(y_true, y_pred)
            rows.append({"model": name, **m, **d})
        return pd.DataFrame(rows).set_index("model")


__all__ = ["KalmanLSTMPipeliner", "ModelEvaluator"]
