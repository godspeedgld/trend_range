"""trend_following.check_trend_valid — 趋势有效性验证。

目标：在全市场品种上实证"趋势是否存在"，用于支撑趋势跟踪策略是否成立。
后续通过各品种、各周期的对数收益率做趋势性 / 自相关 / 动量等检验。

约定
----
- 低流动性品种忽略（见 ``no_use_symbols``）。
- 对数收益率按周期分别落表（见 ``return_tables``），存入
  ``data_cache/returns.db``（SQLite 长表，列：datetime / symbol / log_return，
  主键 (datetime, symbol)，重跑同品种会覆盖）。

周期取数说明
------------
- ``mon`` 月线：ssquant 的 data_server 没有"月"周期代码（``M`` 被当作分钟 1M），
  因此月线由【日线收盘按月重采样（``ME``，取月末）】得到，一个月一条记录。
- ``week`` 周线：同理由日线按自然周重采样（``W-FRI``，周一~周五），一周一条记录。
- ``1d / 1h / 30m``：直接取对应周期 K 线。
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from shared.data_fetcher import fetch_klines

# 低流动性品种忽略：纤维板 / 双胶纸 / 线材 / 胶合板 / 强麦 / 早籼稻 / 普麦 / 粳稻 / 粳米
no_use_symbols = ["fb", "op", "wr", "bb", "wh", "ri", "pm", "jr", "rr"]

# 对数收益率落表名（月 / 周 / 日 / 1小时 / 30分钟）
return_tables = ["mon_return", "week_return", "1d_return", "1h_return", "30m_return"]

# period → (取数用的中文周期, 落表名, 重采样规则)
#   重采样规则为 None 表示直接用该周期 K 线；
#   "mon"/"week" 用日线重采样（data_server 无月/周线代码）。
#   月用 "ME"（pandas 3.0 起 "M" 弃用）；周用 "W-FRI"（周一~周五，标签为周五）。
_PERIOD_MAP = {
    "mon": ("日线", "mon_return", "ME"),
    "week": ("日线", "week_return", "W-FRI"),
    "1d": ("日线", "1d_return", None),
    "1h": ("60分钟", "1h_return", None),
    "30m": ("30分钟", "30m_return", None),
}

# 收益率库：项目根/data_cache/returns.db（与 CWD 无关）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RETURNS_DB = PROJECT_ROOT / "data_cache" / "returns.db"


def calc_log_return(symbol, start_date="1999-01-01", end_date=None, period="1d"):
    """计算单品种指定周期的对数收益率，并存入对应表。

    Args:
        symbol:     品种代码，如 "rb"（内部自动补 888 取主力连续，后复权）
        start_date: 开始日期 "YYYY-MM-DD"（默认 1999-01-01，覆盖上市全历史）
        end_date:   结束日期 "YYYY-MM-DD"（默认今天）
        period:     "mon" / "week" / "1d" / "1h" / "30m"
                    → 分别落 mon_return / week_return / 1d_return / 1h_return / 30m_return
                    （"mon"/"week" 由日线重采样得到：月末 / 周五）

    Returns:
        int: 写入的收益率行数（无数据返回 0）。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")

    cn_period, table, resample_rule = _PERIOD_MAP[period]

    df = fetch_klines(symbol, period=cn_period, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        print(f"[calc_log_return] {symbol} {period} 无数据，跳过")
        return 0

    # 取时间列 + 收盘价
    dt_col = "datetime" if "datetime" in df.columns else "date"
    df = df[[dt_col, "close"]].copy()
    df[dt_col] = pd.to_datetime(df[dt_col])
    df["close"] = df["close"].astype(float)
    df = df.dropna(subset=["close"]).drop_duplicates(subset=[dt_col]).sort_values(dt_col)
    df = df.set_index(dt_col)

    # 月线：日线收盘按月重采样取月末
    if resample_rule:
        df = df[["close"]].resample(resample_rule).last().dropna()

    # 对数收益率：ln(close_t / close_{t-1})
    df["log_return"] = np.log(df["close"]).diff()
    df = df.dropna(subset=["log_return"])
    if df.empty:
        print(f"[calc_log_return] {symbol} {period} 不足两个采样点，无法算收益率")
        return 0

    out = pd.DataFrame({
        "datetime": df.index.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol": symbol,
        "log_return": df["log_return"].astype(float),
    })
    _save_returns(out, table)
    print(f"[calc_log_return] {symbol} {period} → {table}: {len(out)} 行 "
          f"({out['datetime'].iloc[0]} ~ {out['datetime'].iloc[-1]})")
    return len(out)


def _save_returns(df: pd.DataFrame, table: str) -> None:
    """把对数收益率写入 SQLite 长表，按 (datetime, symbol) 主键去重覆盖。"""
    RETURNS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ('
            'datetime TEXT, symbol TEXT, log_return REAL,'
            'PRIMARY KEY (datetime, symbol))'
        )
        rows = [tuple(r) for r in df[["datetime", "symbol", "log_return"]].to_numpy()]
        cur.executemany(
            f'INSERT OR REPLACE INTO "{table}" (datetime, symbol, log_return) VALUES (?,?,?)',
            rows,
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    # 小样本自测：rb 日线 / 周线 / 月线对数收益
    calc_log_return("rb", start_date="2024-01-01", end_date="2024-06-30", period="1d")
    calc_log_return("rb", start_date="2024-01-01", end_date="2024-06-30", period="week")
    calc_log_return("rb", start_date="2024-01-01", end_date="2024-06-30", period="mon")
