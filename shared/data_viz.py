"""shared.data_viz — 数据可视化工具。

从 ``data_cache/returns.db`` 的各周期收益率表读取数据，画折线图，输出 HTML 到
``results/``。跨策略复用（趋势 / 震荡 / 综合）。

周期表名约定与 ``trend_following.check_trend_valid.return_tables`` 一致：
    mon → mon_return / 1d → 1d_return / 1h → 1h_return / 30m → 30m_return
"""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# 项目根（shared 的上一级），保证路径与 CWD 无关
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RETURNS_DB = PROJECT_ROOT / "data_cache" / "returns.db"
RESULTS_DIR = PROJECT_ROOT / "results"

# period → 收益率表名
_PERIOD_TABLE = {
    "mon": "mon_return",
    "1d": "1d_return",
    "1h": "1h_return",
    "30m": "30m_return",
}

# feature → 中文显示名
_FEATURE_LABEL = {
    "log_return": "对数收益率",
}


def plot_feature(symbol, start_date=None, end_date=None, feature="log_return", period="1d"):
    """读取 symbol 在指定 period 表里的 feature，画折线，输出 HTML 到 results/。

    Args:
        symbol:     品种代码，如 "rb"
        start_date: 开始日期 "YYYY-MM-DD"（含），可选
        end_date:   结束日期 "YYYY-MM-DD"（含），可选
        feature:    要画的列，目前表里只有 "log_return"
        period:     "mon" / "1d" / "1h" / "30m" → 对应表

    Returns:
        生成的 HTML 文件路径；无数据返回 None。
    """
    if period not in _PERIOD_TABLE:
        raise ValueError(f"period 仅支持 {list(_PERIOD_TABLE)}，收到 {period!r}")
    # feature 作为列名拼进 SQL，做安全标识符校验防注入
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", str(feature)):
        raise ValueError(f"feature 不是合法列名: {feature!r}")

    table = _PERIOD_TABLE[period]

    if not RETURNS_DB.exists():
        print(f"[data_viz] 收益率库不存在: {RETURNS_DB}，请先运行 calc_log_return")
        return None

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        sql = f'SELECT datetime, "{feature}" FROM "{table}" WHERE symbol = ?'
        params = [symbol]
        if start_date:
            sql += " AND datetime >= ?"
            params.append(f"{start_date} 00:00:00")
        if end_date:
            sql += " AND datetime <= ?"
            params.append(f"{end_date} 23:59:59")
        sql += " ORDER BY datetime"
        df = pd.read_sql(sql, conn, params=params)
    except sqlite3.OperationalError as e:
        print(f"[data_viz] 读取失败（表/列可能不存在）: {e}")
        return None
    finally:
        conn.close()

    if df.empty:
        print(f"[data_viz] {symbol} {period} {feature} 无数据，请先 calc_log_result")
        return None

    df["datetime"] = pd.to_datetime(df["datetime"])
    label = _FEATURE_LABEL.get(feature, feature)
    title = f"{symbol} · {period} · {label}"

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["datetime"], y=df[feature], mode="lines", name=label))
    fig.update_layout(
        title=title,
        xaxis_title="时间",
        yaxis_title=label,
        template="plotly_white",
        hovermode="x unified",
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{symbol}_{period}_{feature}.html"
    fig.write_html(str(out))
    print(f"[data_viz] 已输出: {out}  ({len(df)} 点, {df['datetime'].iloc[0]} ~ {df['datetime'].iloc[-1]})")
    return out


if __name__ == "__main__":
    # 自测：rb 日线对数收益折线
    plot_feature("rb", start_date="2024-01-01", end_date="2024-06-30",
                 feature="log_return", period="1d")
