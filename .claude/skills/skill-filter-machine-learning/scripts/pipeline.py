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

评估器 ModelEvaluator 已拆到 scripts/evaluator.py（回归指标/方向/可视化）。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

import numpy as np
import pandas as pd

from scripts.preprocess import Preprocessor
from scripts.features import DataContext, FeatureEngineer
from scripts.ml import LSTMPredictor, XGBoostPredictor
from scripts.evaluator import ModelEvaluator


# ════════════════════════════════════════════════════════════
# 交叉验证 fold 生成（模块级，供 KalmanLSTMPipeliner / KalmanXGBPipeliner 共用）
# ════════════════════════════════════════════════════════════
def build_cv_folds(
    n: int,
    cv_mode: str = "rolling",
    n_folds: int = 0,
    rolling_train_size: int = 504,
    rolling_test_size: int = 84,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """生成 (train_idx, test_idx) 列表（时序，无重叠/无未来泄漏）。

    expanding: 训练集随 fold 递增（blocks[:fold]），测试集 = 下一 block。n_folds 必填。
    rolling  : 固定训练窗 + 固定测试窗，沿时间轴按 test_size 步长滑动。
               n_folds=0 表示全量滚动（覆盖所有可行 fold）。
    """
    if cv_mode not in ("expanding", "rolling"):
        raise ValueError(f"cv_mode 必须是 'expanding' 或 'rolling'，收到 '{cv_mode}'")
    indices = np.arange(n)
    folds: list[tuple[np.ndarray, np.ndarray]] = []

    if cv_mode == "expanding":
        if not n_folds:
            raise ValueError("expanding 模式需指定 n_folds")
        blocks = np.array_split(indices, n_folds + 1)
        for fold in range(1, n_folds + 1):
            folds.append((np.concatenate(blocks[:fold]), blocks[fold]))

    elif cv_mode == "rolling":
        required = rolling_train_size + rolling_test_size
        if n < required:
            raise ValueError(
                f"数据量({n})不足: rolling_train_size({rolling_train_size}) "
                f"+ rolling_test_size({rolling_test_size}) = {required}"
            )
        start = 0
        while start + required <= n:
            train_end = start + rolling_train_size
            test_end = train_end + rolling_test_size
            folds.append((indices[start:train_end], indices[train_end:test_end]))
            start += rolling_test_size
            if n_folds and len(folds) >= n_folds:
                break

    return folds


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
        """委托模块级 build_cv_folds（expanding / rolling）。"""
        return build_cv_folds(
            n, cv_mode=self.cv_mode, n_folds=self.n_folds,
            rolling_train_size=self.rolling_train_size,
            rolling_test_size=self.rolling_test_size,
        )

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

            # 预测：前面拼 lookback 根做缓冲种子（参数已冻结，纯推理），
            # 使测试窗第一根即可预测，避免每折开头 lookback-1 根 NaN 断点。
            lb = self.lstm_lookback
            pre_start = max(int(test_idx[0]) - lb, 0)
            pre_idx = np.arange(pre_start, int(test_idx[0]))
            ctx_idx = np.concatenate([pre_idx, test_idx])
            pred_full = lstm.predict(X.iloc[ctx_idx])
            pred = pred_full.iloc[-len(test_idx):]
            oos_preds.append(pred)
            oos_indices.append(X_te.index)

            y_te = y.iloc[test_idx]
            corr = pred.corr(y_te) if pred.notna().any() else float("nan")
            # 测试窗 regime 诊断：日期区间 + 已实现波动率（log 收益 std）
            te_close = close.reindex(X_te.index)
            test_vol = float(np.log(te_close / te_close.shift(1)).std())
            fold_results.append({
                "fold": fold_num,
                "test_start": str(X_te.index[0].date()),
                "test_end": str(X_te.index[-1].date()),
                "test_vol": test_vol,
                "train_size": int(len(train_idx)), "test_size": int(len(test_idx)),
                "residual_corr": float(corr) if np.isfinite(corr) else None,
            })
            self._lstm = lstm
            if verbose:
                print(f"  fold {fold_num}: train={len(train_idx)} test={len(test_idx)} "
                      f"vol={test_vol:.4f} corr={corr:.3f}")

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
# KalmanXGBPipeliner（趋势识别器）
# ════════════════════════════════════════════════════════════
class KalmanXGBPipeliner:
    """Kalman 二次特征 → XGBoost 趋势识别器。

    流程：
      1. Kalman 滤波一次特征（level/velocity/accel/p_var_vel/p_var_accel/p_trace/innov/S）。
         一次特征本身不直接喂 XGBoost（见 1.1）。
      2. 二次特征（10 个"趋势识别"指标，_build_secondary）：速度异常/趋势衰竭/爆发/转折、
         P 不确定性、regime 突变、新息持续/可预测性、量价背离、波动扩张。
      3. 标签 = 未来 fwd_horizon 期累计 log 收益 / 同期已实现 std（Sharpe 状）。
      4. walk-forward（build_cv_folds）训练 XGBoostPredictor（lookback=1 纯表格）。
      5. 聚合 OOS + 特征重要度（gain，各折合计归一化）。
    """

    def __init__(
        self,
        kalman_win: int = 50,
        kalman_dim: int = 3,
        N: int = 20,
        fwd_horizon: int = 5,
        # XGBoost
        xgb_n_estimators: int = 300,
        xgb_max_depth: int = 4,
        xgb_learning_rate: float = 0.05,
        xgb_subsample: float = 0.8,
        xgb_colsample: float = 0.8,
        xgb_reg_lambda: float = 1.0,
        xgb_reg_alpha: float = 0.0,
        xgb_min_child: float = 1.0,
        xgb_device: Optional[str] = None,
        xgb_random_state: int = 0,
        # CV
        cv_mode: str = "rolling",
        rolling_train_size: int = 504,
        rolling_test_size: int = 84,
        n_folds: int = 0,
        val_split: float = 0.2,
        early_stopping_rounds: int = 20,
    ):
        if kalman_dim < 3:
            raise ValueError("KalmanXGBPipeliner 需要 kalman_dim>=3（依赖 acceleration）")
        self.kalman_win = kalman_win
        self.kalman_dim = kalman_dim
        self.kf_tag = f"kalman_{kalman_win}_{kalman_dim}"
        self.N = N
        self.fwd_horizon = fwd_horizon
        self.xgb_n_estimators = xgb_n_estimators
        self.xgb_max_depth = xgb_max_depth
        self.xgb_learning_rate = xgb_learning_rate
        self.xgb_subsample = xgb_subsample
        self.xgb_colsample = xgb_colsample
        self.xgb_reg_lambda = xgb_reg_lambda
        self.xgb_reg_alpha = xgb_reg_alpha
        self.xgb_min_child = xgb_min_child
        self.xgb_device = xgb_device
        self.xgb_random_state = xgb_random_state
        self.cv_mode = cv_mode
        self.rolling_train_size = rolling_train_size
        self.rolling_test_size = rolling_test_size
        self.n_folds = n_folds
        self.val_split = val_split
        self.early_stopping_rounds = early_stopping_rounds

        base_config = [f"kalman:{kalman_win},{kalman_dim}", "atr:14", "log_ret_n:5"]
        self._fe = FeatureEngineer(base_config)
        self._preprocessor = Preprocessor()
        self._eval = ModelEvaluator()

    @staticmethod
    def _build_ctx(data: pd.DataFrame) -> DataContext:
        kwargs = {"close": data["close"].astype(float)}
        for col, attr in [("open", "open"), ("high", "high"), ("low", "low"),
                          ("vol", "volume"), ("volume", "volume")]:
            if col in data.columns:
                kwargs[attr] = data[col].astype(float)
        return DataContext(**kwargs)

    # ── 二次特征（10 个趋势识别指标）──────────────────────
    def _build_secondary(self, features: pd.DataFrame, volume: pd.Series) -> pd.DataFrame:
        kf = self.kf_tag
        vel = features[f"{kf}_velocity"]
        accel = features[f"{kf}_acceleration"]
        p_vel = features[f"{kf}_p_var_vel"]
        p_accel = features[f"{kf}_p_var_accel"]
        p_trace = features[f"{kf}_p_trace"]
        innov = features[f"{kf}_innov"]
        S = features[f"{kf}_S"].clip(lower=1e-12)
        std_innov = innov / np.sqrt(S)
        atr = features["atr_14"]
        log_ret_5 = features["log_ret_n_5"]
        vol_chg5 = np.log(volume.replace(0, np.nan)).diff(5)
        N = self.N

        f = pd.DataFrame(index=features.index)
        f["vel_z"] = (vel - vel.rolling(N).mean()) / vel.rolling(N).std()
        f["trend_fatigue"] = (
            (vel.rolling(5).mean() - vel.rolling(15).mean())
            / vel.rolling(15).mean().replace(0, np.nan)
        )
        f["accel_burst"] = accel / (accel.abs().rolling(N).median() + 1e-12)
        f["accel_turn"] = accel.rolling(5).sum() - accel.rolling(N).sum()
        f["trend_conf"] = 1.0 / (1.0 + p_vel + p_accel)
        f["regime_shift"] = p_trace / p_trace.rolling(N).mean().replace(0, np.nan)
        f["innov_cum"] = std_innov.rolling(N).sum()
        f["innov_abs_mean"] = std_innov.abs().rolling(N).mean()
        f["volprice_div"] = log_ret_5 * vol_chg5
        f["atr_exp"] = atr / atr.rolling(20).mean().replace(0, np.nan)
        return f

    # ── 标签：未来 h 期累计收益 / 同期已实现 std ──────────
    def _build_label(self, close: pd.Series, horizon: int) -> pd.Series:
        log_c = np.log(close)
        fwd_ret = log_c.shift(-horizon) - log_c
        daily_ret = log_c.diff()
        future = pd.concat([daily_ret.shift(-k) for k in range(1, horizon + 1)], axis=1)
        fwd_vol = future.std(axis=1)
        return fwd_ret / (fwd_vol + 1e-8)

    # ── 批量：walk-forward 训练 ───────────────────────────
    def fit(self, data: pd.DataFrame, verbose: bool = True) -> dict:
        data = self._preprocessor.preprocess(data)
        close = data["close"].astype(float)
        vol_col = next((c for c in ("vol", "volume") if c in data.columns), None)
        if vol_col is None:
            raise ValueError("数据缺少成交量列 (vol/volume)")
        volume = data[vol_col].astype(float)
        ctx = self._build_ctx(data)

        primary = self._fe.fit(ctx)
        X = self._build_secondary(primary, volume)
        y = self._build_label(close, self.fwd_horizon)

        valid = X.notna().all(axis=1) & y.notna()
        X, y = X[valid], y[valid]
        n = len(X)
        if n < 200:
            raise ValueError(f"有效样本太少({n})")

        folds = build_cv_folds(
            n, cv_mode=self.cv_mode, n_folds=self.n_folds,
            rolling_train_size=self.rolling_train_size,
            rolling_test_size=self.rolling_test_size,
        )
        if verbose:
            print(f"[KalmanXGB cv_mode={self.cv_mode}] folds={len(folds)} "
                  f"n_samples={n} fwd_horizon={self.fwd_horizon} N={self.N}")

        oos_preds, fold_results, importances = [], [], []
        for fold_idx, (train_idx, test_idx) in enumerate(folds):
            fold_num = fold_idx + 1
            X_tr, y_tr = X.iloc[train_idx], y.iloc[train_idx]
            X_te = X.iloc[test_idx]

            xgb = XGBoostPredictor(
                n_estimators=self.xgb_n_estimators, max_depth=self.xgb_max_depth,
                learning_rate=self.xgb_learning_rate, subsample=self.xgb_subsample,
                colsample_bytree=self.xgb_colsample, reg_lambda=self.xgb_reg_lambda,
                reg_alpha=self.xgb_reg_alpha, min_child_weight=self.xgb_min_child,
                device=self.xgb_device, random_state=self.xgb_random_state,
            )
            xgb.fit(X_tr, y_tr, val_split=self.val_split,
                    early_stopping_rounds=self.early_stopping_rounds, verbose=verbose)
            pred = xgb.predict(X_te)
            oos_preds.append(pred)
            importances.append(xgb.feature_importance("gain"))

            y_te = y.iloc[test_idx]
            corr = pred.corr(y_te) if pred.notna().any() else float("nan")
            fold_results.append({
                "fold": fold_num, "train_size": int(len(train_idx)),
                "test_size": int(len(test_idx)),
                "label_corr": float(corr) if np.isfinite(corr) else None,
            })
            if verbose:
                print(f"  fold {fold_num}: train={len(train_idx)} test={len(test_idx)} "
                      f"label_corr={corr:.3f}")

        oos_pred = pd.concat(oos_preds).sort_index() if oos_preds else pd.Series(dtype=float)
        oos_idx = oos_pred.index
        oos_label = y.reindex(oos_idx)
        fwd_ret = (np.log(close).shift(-self.fwd_horizon) - np.log(close)).reindex(oos_idx)

        # 特征重要度：各折 gain 合计后归一化
        agg: dict[str, float] = {}
        for imp in importances:
            for k, v in imp.items():
                agg[k] = agg.get(k, 0.0) + v
        total = sum(agg.values()) or 1.0
        feature_importance = {k: v / total for k, v in sorted(agg.items(), key=lambda x: -x[1])}

        # OOS 指标
        corr_label = oos_pred.corr(oos_label)
        corr_fwdret = oos_pred.corr(fwd_ret)
        dir_mask = oos_pred.notna() & fwd_ret.notna()
        dir_acc = (float((np.sign(oos_pred[dir_mask]) == np.sign(fwd_ret[dir_mask])).mean())
                   if dir_mask.sum() else float("nan"))
        label_metrics = self._eval.evaluate(oos_label, oos_pred)

        if verbose:
            print(f"\n[OOS] label_corr={corr_label:.3f}  fwd_ret_corr={corr_fwdret:.3f}  "
                  f"{self.fwd_horizon}日方向准确度={dir_acc:.3f}  n={int(dir_mask.sum())}")
            print("[feature importance] (gain, 各折合计归一化)")
            for k, v in feature_importance.items():
                print(f"  {k:<16} {v:.3f}")

        return {
            "oos_pred": oos_pred, "oos_label": oos_label, "oos_fwd_ret": fwd_ret,
            "features": X, "fold_results": fold_results,
            "feature_importance": feature_importance,
            "metrics": {
                "label_corr": float(corr_label) if np.isfinite(corr_label) else None,
                "fwd_ret_corr": float(corr_fwdret) if np.isfinite(corr_fwdret) else None,
                "direction_accuracy": dir_acc,
                **{k: v for k, v in label_metrics.items()},
            },
        }


__all__ = ["KalmanLSTMPipeliner", "KalmanXGBPipeliner", "build_cv_folds"]
