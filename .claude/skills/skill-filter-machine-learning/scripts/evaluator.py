"""模型评估器：回归指标 + 方向准确度 + plotly 可视化。

从 pipeline.py 拆出，独立模块。不依赖 pipeline 内部状态，纯函数式工具：
  evaluate()          → MAE/MSE/RMSE/MAPE/R²/n
  evaluate_direction()→ 方向准确度（连续两根 sign 一致率）
  plot()              → actual vs predicted + 误差分布 HTML
  compare()           → 多模型对比表
"""
from __future__ import annotations

import numpy as np
import pandas as pd


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


__all__ = ["ModelEvaluator"]
