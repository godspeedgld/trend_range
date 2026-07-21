"""LSTM 回归预测器（批量训练/预测 + 流式推理）。依赖 torch（GPU 优化）。

GPU 优化：
  - cuDNN benchmark（自动选最快 RNN 算法）
  - TF32 高精度矩阵乘（Blackwell/Ampere+ 硬件加速）
  - bf16 混合精度训练/推理（无需 GradScaler，Blackwell 原生）
  - 数据直接建在 GPU（省 CPU→GPU 拷贝）
  - 可选 torch.compile（JIT 编译，减少 Python 开销）

LSTMPredictor：
  - 输入：特征矩阵 X [n, features] + 目标向量 y [n]（回归）。
  - 批量：fit(X, y) 训练（early stopping）；predict(X) 全序列。
  - 流式：fit 后 update(feature_row) 一步推理（lookback 缓冲 warmstart）。
"""

from __future__ import annotations

from collections import deque
from numpy.lib.stride_tricks import sliding_window_view
from typing import Optional

import numpy as np
import pandas as pd


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


class LSTMPredictor:
    """LSTM 回归预测器（GPU 优化）。批量 fit/predict + 流式 update。

    Args:
        lookback: 序列窗口长度。
        hidden: LSTM 隐藏维度。
        num_layers: LSTM 层数。
        dropout: LSTM dropout（仅 num_layers>1 生效）。
        lr: 学习率。
        device: 'cuda' | 'cpu' | None（None 自动检测）。
        use_amp: 混合精度（bf16 autocast），GPU 时默认 True。
        compile: 是否 torch.compile（首 epoch 慢、后续快）。
    """

    def __init__(
        self,
        lookback: int = 20,
        *,
        hidden: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        lr: float = 1e-3,
        device: Optional[str] = None,
        use_amp: bool = True,
        use_compile: bool = False,
    ):
        self.lookback = lookback
        self.hidden = hidden
        self.num_layers = num_layers
        self.dropout = dropout
        self.lr = lr
        self.device = device or ("cuda" if _cuda_available() else "cpu")
        self.use_amp = use_amp and self.device != "cpu"
        self.use_compile = use_compile
        self.model = None
        self.optimizer = None
        self.criterion = None
        self._scaler_mean = None
        self._scaler_std = None
        self._buf: deque = deque(maxlen=lookback)
        self.n_features: Optional[int] = None

    # ── GPU 初始化 ────────────────────────────────────────
    def _enable_gpu_opt(self):
        """开启 cuDNN autotuner + TF32。"""
        import torch
        if self.device != "cpu":
            torch.backends.cudnn.benchmark = True          # cuDNN 自动选最快算法
            torch.set_float32_matmul_precision("high")     # 允许 TF32（Ampere+）

    def _amp_ctx(self):
        """返回 autocast 上下文管理器（GPU + use_amp 时生效）。"""
        import torch
        if self.use_amp:
            return torch.autocast(device_type=self.device, dtype=torch.bfloat16)
        from contextlib import nullcontext
        return nullcontext()

    # ── 模型构建 ──────────────────────────────────────────
    def _build_model(self):
        import torch
        import torch.nn as nn

        class _Net(nn.Module):
            def __init__(self, input_dim, hidden, num_layers, dropout):
                super().__init__()
                self.lstm = nn.LSTM(
                    input_dim, hidden, num_layers,
                    batch_first=True,
                    dropout=dropout if num_layers > 1 else 0,
                )
                self.fc = nn.Linear(hidden, 1)

            def forward(self, x):
                out, _ = self.lstm(x)
                return self.fc(out[:, -1, :])

        self._enable_gpu_opt()
        self.model = _Net(self.n_features, self.hidden, self.num_layers, self.dropout).to(self.device)
        if self.use_compile:
            self.model = torch.compile(self.model, mode="reduce-overhead")
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=self.lr)
        self.criterion = nn.MSELoss()

    # ── 数据工具 ──────────────────────────────────────────
    def _standardize(self, X):
        return (X - self._scaler_mean) / self._scaler_std

    def _window(self, Xs, y=None):
        """sliding_window_view：O(1) 内存视图 + 一次 copy。"""
        L = self.lookback
        n = len(Xs)
        if n < L:
            shape = (0, L, Xs.shape[1] if Xs.ndim > 1 else 1)
            empty_t = np.empty(0, dtype=np.float32) if y is not None else None
            return np.empty(shape, dtype=np.float32), empty_t
        seqs = np.ascontiguousarray(np.transpose(sliding_window_view(Xs, L, axis=0), (0, 2, 1)))
        targets = y[L - 1:].astype(np.float32) if y is not None else None
        return seqs.astype(np.float32), targets

    def _to_device(self, arr):
        """numpy → GPU/CPU tensor（直接建在目标设备，省 CPU→GPU 拷贝）。"""
        import torch
        return torch.from_numpy(arr).to(self.device, non_blocking=True)

    # ── 批量训练 ──────────────────────────────────────────
    def fit(self, X, y, *, val_split=0.2, epochs=50, batch_size=32, patience=10, verbose=True) -> dict:
        """批量训练。返回 history {train_loss, val_loss}。"""
        import torch

        X = pd.DataFrame(X).astype(float) if not (isinstance(X, np.ndarray) and X.ndim == 1) else pd.DataFrame(X.reshape(1, -1)).astype(float)
        y = pd.Series(y).astype(float)
        mask = X.notna().all(axis=1) & y.notna()
        X = X[mask].to_numpy(dtype=np.float32)
        y = y[mask].to_numpy(dtype=np.float32)
        self.n_features = X.shape[1]

        # 标准化：scaler fit 于训练段，apply 到全量（train+val 统一用 train 统计量，防泄漏）
        split_raw = int(len(X) * (1 - val_split))
        self._scaler_mean = X[:split_raw].mean(axis=0).astype(np.float32)
        self._scaler_std = X[:split_raw].std(axis=0).astype(np.float32)
        self._scaler_std[self._scaler_std == 0] = 1.0
        Xs = self._standardize(X)

        # 滑窗 + 直接建在 device
        seqs, targets = self._window(Xs, y)
        splt = max(0, split_raw - self.lookback + 1)   # 对齐原始 split（按 target 行号）
        Xtr = self._to_device(seqs[:splt])
        ytr = self._to_device(targets[:splt])
        Xval = self._to_device(seqs[splt:])
        yval = self._to_device(targets[splt:])

        # 构建 + GPU 优化
        self._build_model()

        # 训练（bf16 autocast + cuDNN benchmark + TF32）
        history = {"train_loss": [], "val_loss": []}
        best_val = float("inf")
        best_state = None
        wait = 0
        dataset = torch.utils.data.TensorDataset(Xtr, ytr)
        loader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True)

        for epoch in range(epochs):
            self.model.train()
            tloss = 0.0
            for xb, yb in loader:
                self.optimizer.zero_grad()
                with self._amp_ctx():
                    pred = self.model(xb).squeeze(-1)
                    loss = self.criterion(pred, yb)
                loss.backward()
                self.optimizer.step()
                tloss += loss.item() * len(xb)
            tloss /= len(Xtr)

            self.model.eval()
            with torch.no_grad(), self._amp_ctx():
                vpred = self.model(Xval).squeeze(-1)
                vloss = self.criterion(vpred, yval).item()

            history["train_loss"].append(tloss)
            history["val_loss"].append(vloss)
            if verbose and (epoch % 10 == 0 or epoch == epochs - 1):
                print(f"  epoch {epoch}: train={tloss:.6f} val={vloss:.6f}")

            if vloss < best_val:
                best_val = vloss
                best_state = {k: v.clone() for k, v in self.model.state_dict().items()}
                wait = 0
            else:
                wait += 1
                if wait >= patience:
                    if verbose:
                        print(f"  early stop @ epoch {epoch}")
                    break

        if best_state:
            self.model.load_state_dict(best_state)
        self.model.eval()

        # warmstart 流式缓冲（用 train scaler 标准化，与 predict/update 一致）
        if len(X) >= self.lookback:
            self._buf = deque(self._standardize(X[-self.lookback:]).tolist(), maxlen=self.lookback)
        else:
            self._buf = deque(maxlen=self.lookback)   # X 不足 lookback，留空缓冲
        return history

    # ── 批量预测 ──────────────────────────────────────────
    def predict(self, X) -> pd.Series:
        import torch

        if self.model is None:
            raise RuntimeError("LSTMPredictor.predict() 需先调 fit() 训练")
        if isinstance(X, np.ndarray) and X.ndim == 1:
            X = X.reshape(1, -1)
        X = pd.DataFrame(X).astype(float)
        idx = X.index
        X = X.to_numpy(dtype=np.float32)
        Xs = self._standardize(X)
        seqs, _ = self._window(Xs)
        if len(seqs) == 0:
            return pd.Series(np.full(len(X), np.nan), index=idx, name="lstm_pred")
        with torch.no_grad(), self._amp_ctx():
            preds = self.model(self._to_device(seqs)).squeeze(-1).float().cpu().numpy()
        out = np.full(len(X), np.nan, dtype=np.float32)
        out[self.lookback - 1 :] = preds
        return pd.Series(out, index=idx, name="lstm_pred")

    # ── 流式推理 ──────────────────────────────────────────
    def update(self, row) -> float:
        import torch

        if self.model is None:
            raise RuntimeError("LSTMPredictor.update() 需先调 fit() 训练")
        row = np.array(list(row.values()) if isinstance(row, dict) else row, dtype=np.float32)
        rs = self._standardize(row)
        self._buf.append(rs)
        if len(self._buf) < self.lookback:
            return float("nan")
        seq = np.array(list(self._buf), dtype=np.float32)[np.newaxis]
        with torch.no_grad(), self._amp_ctx():
            pred = self.model(self._to_device(seq)).float().item()
        return pred

    def reset_stream(self):
        self._buf = deque(maxlen=self.lookback)


__all__ = ["LSTMPredictor"]
