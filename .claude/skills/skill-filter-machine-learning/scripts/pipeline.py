"""Kalman + LSTM 管线 + 模型评估器。

架构分层：
  一次特征（FeatureEngineer）：log_ret / vol / kalman / MA / MACD / ... → 从 OHLCV + ctx 计算
  二次特征（pipeline 直接拼）：std_innov / residual / ... → 从一次特征输出再计算
  LSTM：X=特征, y=Kalman 残差 → k 折交叉验证滚动训练（expanding / rolling）

交叉验证模式：
  - expanding：训练集随 fold 递增（blocks[:fold]），测试集=下一 block。
    适合数据量较少、希望充分利用历史数据的场景。
  - rolling ：固定训练窗口 + 固定测试窗口，沿时间轴滑动。
    适合数据量充足、希望避免过时数据干扰的场景。
    参数 rolling_train_size / rolling_test_size 控制窗口大小（bar 数）。

KalmanLSTMPipeliner：
  批量 fit(data) → OOS 预测（k 折滚动）；流式 update(bar) → 一步推理。
ModelEvaluator：回归指标 + 方向准确度 + plotly 可视化。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

from scripts.preprocess import Preprocessor
from scripts.features import DataContext, FeatureEngineer
from scripts.ml import LSTMPredictor


# ════════════════════════════════════════════════════════════
# KalmanLSTMPipeliner
# ════════════════════════════════════════════════════════════
class KalmanLSTMPipeliner:
    """Kalman(一次特征) + LSTM(非线性残差校正) 管线。

    流程：
      1. FeatureEngineer 算一次特征（含 kalman → level/velocity/accel/predict_value/innov/S）。
      2. pipeline 拼二次特征（std_innov = innov/√S 等）。
      3. 残差 = close[t+1] − predict_value[t]（Kalman 一步预测误差）。
      4. k 折交叉验证滚动训练 LSTM（expanding / rolling）：X=特征, y=残差。
      5. 最终预测 = predict_value + LSTM 残差预测。
    """

    def __init__(
        self,
        kalman_win: int = 50,
        kalman_dim: int = 3,
        lstm_lookback: int = 20,
        lstm_hidden: int = 64,
        lstm_layers: int = 2,
        feature_config: Optional[list] = None,
        n_folds: int = 5,
        val_split: float = 0.2,
        lstm_epochs: int = 50,
        lstm_batch: int = 64,
        device: str = "cuda",
        cv_mode: str = "rolling",
        rolling_train_size: int = 504,
        rolling_test_size: int = 84,
        target_mode: str = "return",
        lstm_features: Optional[list[str]] = None,
    ):
        if cv_mode not in ("expanding", "rolling"):
            raise ValueError(f"cv_mode 必须是 'expanding' 或 'rolling'，收到 '{cv_mode}'")
        if target_mode not in ("price", "return"):
            raise ValueError(f"target_mode 必须是 'price' 或 'return'，收到 '{target_mode}'")
        self.kalman_win = kalman_win
        self.kalman_dim = kalman_dim
        self.kf_tag = f"kalman_{kalman_win}_{kalman_dim}"
        self.vol_tag = "vol_20"
        self.lstm_lookback = lstm_lookback
        self.lstm_hidden = lstm_hidden
        self.lstm_layers = lstm_layers
        self.n_folds = n_folds
        self.val_split = val_split
        self.lstm_epochs = lstm_epochs
        self.lstm_batch = lstm_batch
        self.device = device
        self.cv_mode = cv_mode
        self.rolling_train_size = rolling_train_size
        self.rolling_test_size = rolling_test_size
        # target 口径：'return'=残差收益率(close 归一化，平稳) | 'price'=绝对价格残差(旧)
        self.target_mode = target_mode

        # 一次特征配置（含 kalman）；用户可通过 feature_config 追加/覆盖
        base_config = [
            "log_ret", "log_ret_n:5", "log_ret_n:10",
            "vol:20", "vol_log_ret", "vol_ratio:20", "vwap_dev:20",
            "range_pct", "close_pos", "atr:14",
            f"kalman:{kalman_win},{kalman_dim}",
        ]
        if feature_config:
            base_config += list(feature_config)
        self._fe = FeatureEngineer(base_config)
        self._preprocessor = Preprocessor()

        self._lstm: Optional[LSTMPredictor] = None
        # LSTM 输入列：用户可通过 lstm_features 精简（std_innov 在 fit 里自动追加）
        if lstm_features is not None:
            self._feature_cols = [c for c in lstm_features if c != "std_innov"]
        else:
            self._feature_cols = [
                "log_ret", "log_ret_n_5", "log_ret_n_10",
                "vol_20", "vol_log_ret", "vol_ratio_20", "vwap_dev_20",
                "range_pct", "close_pos",
            ]

    # ── 交叉验证 fold 生成 ────────────────────────────────
    def _build_folds(self, n: int) -> list[tuple[np.ndarray, np.ndarray]]:
        """根据 cv_mode 生成 (train_idx, test_idx) 列表。

        expanding: 训练集随 fold 递增（blocks[:fold]），测试集 = 下一 block。
        rolling  : 固定训练窗口 + 固定测试窗口，沿时间轴从前向后滑动。
        """
        indices = np.arange(n)
        folds: list[tuple[np.ndarray, np.ndarray]] = []

        if self.cv_mode == "expanding":
            blocks = np.array_split(indices, self.n_folds + 1)
            for fold in range(1, self.n_folds + 1):
                train_idx = np.concatenate(blocks[:fold])
                test_idx = blocks[fold]
                folds.append((train_idx, test_idx))

        elif self.cv_mode == "rolling":
            train_size = self.rolling_train_size
            test_size = self.rolling_test_size
            required = train_size + test_size
            if n < required:
                raise ValueError(
                    f"数据量({n})不足: rolling_train_size({train_size}) "
                    f"+ rolling_test_size({test_size}) = {required}"
                )
            start = 0
            while start + required <= n:
                train_end = start + train_size
                test_end = train_end + test_size
                train_idx = indices[start:train_end]
                test_idx = indices[train_end:test_end]
                folds.append((train_idx, test_idx))
                start += test_size  # 按测试窗口步长滑动
                if self.n_folds and len(folds) >= self.n_folds:
                    break

        return folds

    # ── 二次特征 ──────────────────────────────────────────
    def _add_secondary(self, features: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
        """在一次特征基础上拼二次特征（std_innov 等）。"""
        kf = self.kf_tag
        innov = features[f"{kf}_innov"]
        S = features[f"{kf}_S"].clip(lower=1e-12)
        features["std_innov"] = innov / np.sqrt(S)
        return features

    @staticmethod
    def _build_ctx(data: pd.DataFrame) -> DataContext:
        """从 OHLCV DataFrame 构建 DataContext。"""
        kwargs = {"close": data["close"].astype(float)}
        for col, attr in [("open", "open"), ("high", "high"), ("low", "low"), ("vol", "volume"), ("volume", "volume")]:
            if col in data.columns:
                kwargs[attr] = data[col].astype(float)
        return DataContext(**kwargs)

    # ── 批量：k 折滚动训练 ────────────────────────────────
    def fit(self, data: pd.DataFrame, verbose: bool = True) -> dict:
        """批量管线。返回 OOS 预测 + 各折详情。"""
        # 0. 数据预处理（排序 + 缺失值 + 去重）
        data = self._preprocessor.preprocess(data)
        close = data["close"].astype(float)
        ctx = self._build_ctx(data)

        # 1. 一次特征（FeatureEngineer，含 Kalman）
        primary = self._fe.fit(ctx)

        # 2. 二次特征（pipeline 直接拼）
        features = self._add_secondary(primary, close)

        # 3. 残差 = close[t+1] − predict_value[t]（price 口径）或收益率化（return 口径，平稳）
        predict_value = features[f"{self.kf_tag}_predict_value"]
        if self.target_mode == "return":
            residual = (close.shift(-1) - predict_value) / close
        else:
            residual = close.shift(-1) - predict_value

        # 4. X / y 对齐
        x_cols = self._feature_cols + ["std_innov"]
        X = features[x_cols].copy()
        y = residual
        valid = X.notna().all(axis=1) & y.notna()
        X, y = X[valid], y[valid]
        n = len(X)
        if n < 100:
            raise ValueError(f"有效数据太少({n}行)")

        # 5. k 折交叉验证 (expanding / rolling)
        folds = self._build_folds(n)
        if verbose:
            mode_desc = (f"expanding (folds={len(folds)})" if self.cv_mode == "expanding"
                         else f"rolling (train={self.rolling_train_size}, test={self.rolling_test_size}, folds={len(folds)})")
            print(f"[cv_mode={self.cv_mode}] {mode_desc}, n_samples={n}")

        oos_preds, oos_indices, fold_results = [], [], []
        for fold_idx, (train_idx, test_idx) in enumerate(folds):
            fold_num = fold_idx + 1
            if len(test_idx) < self.lstm_lookback + 1:
                continue

            X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
            X_te = X.iloc[test_idx]

            lstm = LSTMPredictor(
                lookback=self.lstm_lookback, hidden=self.lstm_hidden,
                num_layers=self.lstm_layers, device=self.device,
            )
            lstm.fit(X_tr, y_tr, val_split=self.val_split,
                     epochs=self.lstm_epochs, batch_size=self.lstm_batch,
                     patience=10, verbose=verbose)

            pred = lstm.predict(X_te)
            oos_preds.append(pred)
            oos_indices.append(X_te.index)

            y_te = y.iloc[test_idx]
            corr = pred.corr(y_te) if pred.notna().any() else float("nan")
            fold_results.append({
                "fold": fold_num, "train_size": int(len(train_idx)), "test_size": int(len(test_idx)),
                "residual_corr": float(corr) if np.isfinite(corr) else None,
            })
            self._lstm = lstm
            if verbose:
                print(f"  fold {fold_num}: train={len(train_idx)} test={len(test_idx)} corr={corr:.3f}")

        # 6. 聚合 OOS（return 口径需 ×close[t] 还原为价格）
        oos_lstm = pd.concat(oos_preds).sort_index() if oos_preds else pd.Series(dtype=float)
        oos_idx = oos_lstm.index
        oos_kalman = predict_value.reindex(oos_idx)
        if self.target_mode == "return":
            oos_final = oos_kalman + oos_lstm * close.reindex(oos_idx)
        else:
            oos_final = oos_kalman + oos_lstm
        oos_actual = close.shift(-1).reindex(oos_idx)

        return {
            "oos_final": oos_final,
            "oos_kalman": oos_kalman,
            "oos_lstm_residual": oos_lstm,
            "oos_actual": oos_actual,
            "features": features,
            "fold_results": fold_results,
        }

    # ── 流式：一步推理 ────────────────────────────────────
    def update(self, bar: dict) -> dict:
        """流式推理。bar = {close, ...}。返回最终预测 + 各组件。"""
        if self._lstm is None:
            raise RuntimeError("KalmanLSTMPipeliner.update() 需先调 fit()")

        # 1. 一次特征（FE 含 Kalman）
        fe_out = self._fe.update(bar)

        # 2. 二次特征
        kf = self.kf_tag
        innov = fe_out[f"{kf}_innov"]
        S = max(fe_out[f"{kf}_S"], 1e-12)
        std_innov = innov / np.sqrt(S)

        # 3. LSTM 预测残差
        feat_row = {col: fe_out[col] for col in self._feature_cols}
        feat_row["std_innov"] = std_innov
        lstm_resid = self._lstm.update(feat_row)

        # 4. 最终 = Kalman 预测 + LSTM 残差（return 口径需 ×close[t] 还原价格）
        kalman_pred = fe_out[f"{kf}_predict_value"]
        if self.target_mode == "return":
            adj = lstm_resid * float(bar["close"]) if np.isfinite(lstm_resid) else 0.0
        else:
            adj = lstm_resid if np.isfinite(lstm_resid) else 0.0
        final = kalman_pred + adj
        return {
            "final": final,
            "kalman_pred": kalman_pred,
            "lstm_residual": lstm_resid,
            "level": fe_out[f"{kf}_level"],
            "velocity": fe_out[f"{kf}_velocity"],
            "acceleration": fe_out.get(f"{kf}_acceleration"),
            "innov": innov,
            "S": fe_out[f"{kf}_S"],
        }


# ════════════════════════════════════════════════════════════
# ModelEvaluator
# ════════════════════════════════════════════════════════════
class ModelEvaluator:
    """模型评估器：回归指标 + 方向准确度 + plotly 可视化。"""

    def evaluate(self, y_true: pd.Series, y_pred: pd.Series) -> dict:
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
        nonzero = np.abs(yt) > 1e-12
        mape = float(np.mean(np.abs(err[nonzero] / yt[nonzero])) * 100) if nonzero.any() else float("nan")
        ss_tot = float(np.sum((yt - yt.mean()) ** 2))
        r2 = float(1 - np.sum(err ** 2) / ss_tot) if ss_tot > 0 else float("nan")
        return {"MAE": mae, "MSE": mse, "RMSE": rmse, "MAPE": mape, "R2": r2, "n": n}

    def evaluate_direction(self, y_true: pd.Series, y_pred: pd.Series) -> dict:
        valid = y_true.notna() & y_pred.notna()
        yt, yp = y_true[valid], y_pred[valid]
        if len(yt) < 2:
            return {"direction_accuracy": float("nan"), "n": 0}
        actual_dir = np.sign(yt.diff().dropna())
        pred_dir = np.sign(yp.diff().dropna())
        common = actual_dir.index.intersection(pred_dir.index)
        acc = float((actual_dir.reindex(common).fillna(0) == pred_dir.reindex(common).fillna(0)).mean())
        return {"direction_accuracy": acc, "n": int(len(common))}

    def plot(self, y_true: pd.Series, y_pred: pd.Series, path: str,
             title: str = "actual vs predicted") -> str:
        from plotly.subplots import make_subplots
        import plotly.graph_objects as go

        valid = y_true.notna() & y_pred.notna()
        yt, yp = y_true[valid], y_pred[valid]
        err = (yt - yp).dropna()

        fig = make_subplots(rows=2, cols=1, row_heights=[3, 1], vertical_spacing=0.12,
                            subplot_titles=[title, "误差分布"])
        fig.add_trace(go.Scatter(x=yt.index, y=yt.values, name="actual",
                                 line=dict(color="#7f8c8d", width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=yp.index, y=yp.values, name="predicted",
                                 line=dict(color="#2980b9", width=1.2)), row=1, col=1)
        fig.add_trace(go.Histogram(x=err.values, name="error", marker_color="#e74c3c",
                                   nbinsx=50), row=2, col=1)
        fig.update_layout(hovermode="x unified", template="plotly_white", height=600,
                          xaxis_rangeslider_visible=False, margin=dict(l=50, r=30, t=50, b=40))
        fig.write_html(path, include_plotlyjs="cdn")
        return path

    def compare(self, y_true: pd.Series, models: dict[str, pd.Series]) -> pd.DataFrame:
        rows = []
        for name, y_pred in models.items():
            m = self.evaluate(y_true, y_pred)
            d = self.evaluate_direction(y_true, y_pred)
            rows.append({"model": name, **m, **d})
        return pd.DataFrame(rows).set_index("model")


__all__ = ["KalmanLSTMPipeliner", "ModelEvaluator"]
