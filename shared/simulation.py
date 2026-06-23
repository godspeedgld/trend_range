"""shared.simulation — 数据模拟：AR(1) 收益率序列。

    b_0   ~ N(0, σ_b²)         初始值（平稳分布方差）
    e_t   ~ N(0, δ²)           白噪声
    b_t   = ρ·b_{t-1} + e_t    AR(1) 过程
    r_t   = b_t − μ_b + μ      去均值后加回长期均值 → 收益率序列

    参数 μ（长期均值）、ρ（自相关系数）、δ（白噪声标准差）。
    默认 μ=0.0001, ρ=0.01, δ=0.01，模拟典型的弱自相关收益序列。
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def simulate_ar1_returns(n=2520, mu=0.0001, rho=0.01, delta=0.01, seed=None):
    """生成 AR(1) 对数收益率序列。

    Args:
        n:     序列长度（默认 2520 ≈ 10 年日频）
        mu:    长期均值（默认 0.0001）
        rho:   自相关系数（默认 0.01）
        delta: 白噪声标准差（默认 0.01）
        seed:  随机种子，None 则不固定

    Returns:
        DataFrame: t / b / r / price, 其中 price = 1000 × exp(cumsum(r))
    """
    rng = np.random.default_rng(seed)
    # 平稳分布方差：AR(1) 的平稳方差 = δ²/(1−ρ²)
    sigma_b = delta / np.sqrt(1 - rho ** 2)

    e = rng.normal(0, delta, n)                 # 白噪声
    b0 = rng.normal(0, sigma_b)                  # 初始值（平稳分布）

    b = np.empty(n)
    b[0] = rho * b0 + e[0]
    for t in range(1, n):
        b[t] = rho * b[t - 1] + e[t]

    mu_b = b.mean()
    r = b - mu_b + mu                             # 去均值 + 长期均值

    price = 1000.0 * np.exp(np.cumsum(r))

    return pd.DataFrame({"t": range(1, n + 1), "b": b, "r": r, "price": price})


def plot_simulated(df, mu=None, rho=None, delta=None, out_name=None):
    """可视化模拟数据：价格曲线 + 收益曲线 + ACF。

    Args:
        df:        simulate_ar1_returns 的输出
        mu/rho/delta: 参数（仅用于标题）
        out_name:  输出文件名（写到 results/），None 则 "simulation.html"

    Returns:
        生成的 HTML 文件路径。
    """
    n = len(df)
    params = []
    if mu is not None: params.append(f"μ={mu}")
    if rho is not None: params.append(f"ρ={rho}")
    if delta is not None: params.append(f"δ={delta}")
    param_str = "  |  ".join(params) if params else ""

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.45, 0.30, 0.25],
        subplot_titles=("价格曲线（首日=1000）", "对数收益率 r_t", "ACF 自相关图"),
        vertical_spacing=0.06,
    )

    # ① 价格
    fig.add_trace(go.Scatter(x=df["t"], y=df["price"], mode="lines",
                             name="price", line=dict(width=1)), row=1, col=1)

    # ② 收益率
    fig.add_trace(go.Scatter(x=df["t"], y=df["r"], mode="lines",
                             name="r_t", line=dict(width=0.5)),
                  row=2, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=1, row=2, col=1)

    # ③ ACF (lag 1..60)
    r = df["r"].to_numpy()
    max_lag = min(60, n - 1)
    acf = []
    for lag in range(1, max_lag + 1):
        corr = np.corrcoef(r[lag:], r[:-lag])[0, 1] if lag < n else np.nan
        acf.append(corr)
    fig.add_trace(go.Bar(x=list(range(1, max_lag + 1)), y=acf,
                         marker_color="steelblue", name="ACF"),
                  row=3, col=1)

    fig.update_layout(
        title=f"模拟 AR(1) 收益率序列  {param_str}  (n={n})",
        template="plotly_white", height=800, showlegend=False,
    )
    fig.update_xaxes(title_text="t", row=3, col=1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / (out_name or "simulation.html")
    fig.write_html(str(out))
    return str(out)


def plot_simulated_with_tsmom(df, rho=None, delta=None,
                               h_scan=range(1, 61), out_name="simulation_tsmom.html"):
    """模拟数据 + TSMOM 回归验证：对已知 ρ 的序列，看单滞后回归能否检出 ρ。

    对每个 h，做 r_t ~ r_{t-h} 回归，画 t 统计量的 h-scan。若模拟的 ρ>0，
    预期在 h 较小时 t 显著为正（动量）。也画 ±2 参考线。
    """
    import statsmodels.api as sm

    r = df["r"].to_numpy()
    n = len(r)

    hs, tstats = [], []
    for h in h_scan:
        if h >= n:
            continue
        y = r[h:]
        x = r[:-h]
        m = sm.OLS(y, sm.add_constant(x)).fit(cov_type="HAC",
                                                cov_kwds={"maxlags": max(1, int(h))})
        hs.append(h)
        tstats.append(float(m.tvalues[1]))

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        row_heights=[0.55, 0.45],
                        subplot_titles=("收益率 r_t", "TSMOM 单滞后回归 t(h)"),
                        vertical_spacing=0.08)

    fig.add_trace(go.Scatter(x=df["t"], y=df["r"], mode="lines",
                             line=dict(width=0.5)), row=1, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=1, row=1, col=1)

    colors = ["crimson" if t < 0 else "steelblue" for t in tstats]
    fig.add_trace(go.Bar(x=hs, y=tstats, marker_color=colors), row=2, col=1)
    fig.add_hline(y=2, line_dash="dash", line_color="gray", row=2, col=1)
    fig.add_hline(y=-2, line_dash="dash", line_color="gray", row=2, col=1)
    fig.add_hline(y=0, line_color="black", line_width=1, row=2, col=1)

    params = []
    if rho is not None: params.append(f"ρ={rho}")
    if delta is not None: params.append(f"δ={delta}")
    fig.update_layout(
        title=f"模拟数据 TSMOM 验证  {' | '.join(params)}  n={n}",
        template="plotly_white", height=700, showlegend=False,
    )
    fig.update_xaxes(title_text="h", row=2, col=1)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / out_name
    fig.write_html(str(out))
    return str(out)


if __name__ == "__main__":
    df = simulate_ar1_returns(n=2520, mu=0.0001, rho=0.01, delta=0.01, seed=42)
    plot_simulated(df, mu=0.0001, rho=0.01, delta=0.01)
    plot_simulated_with_tsmom(df, rho=0.01, delta=0.01)
    print(f"模拟完成: n={len(df)}")
    print(f"  r sample mean={df['r'].mean():.6f}  (should be ~0.0001)")
    print(f"  r sample std={df['r'].std():.6f}")
    print(f"  price 终值: {df['price'].iloc[-1]:.2f}")
