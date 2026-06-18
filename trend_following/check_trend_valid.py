"""trend_following.check_trend_valid — 趋势有效性验证。

目标：在全市场品种上实证"趋势是否存在"，用于支撑趋势跟踪策略是否成立。
后续通过各品种、各周期的对数收益率做趋势性 / 自相关 / 动量等检验。

约定
----
- 低流动性品种忽略（见 ``no_use_symbols``）。
- 对数收益率按周期分别落表（见 ``return_tables``），存入
  ``data_cache/returns.db``（SQLite 长表，列：datetime / symbol / category / log_return，
  主键 (datetime, symbol)；category 为品种板块，来自 shared.sector.get_category；
  重跑同品种会覆盖）。

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
from shared.sector import get_category

# 低流动性 / 近僵尸 / 特殊品种忽略（大小写不敏感）：
#   纤维板 / 双胶纸 / 线材 / 胶合板 / 强麦 / 早籼稻 / 普麦 / 粳稻 / 粳米
no_use_symbols = [
    "fb", "op", "wr", "bb", "wh", "ri", "pm", "jr", "rr",
    "rs",       # 油菜籽（流动性低）
    "zc",       # 动力煤（流动性极低）
    "l_f", "pp_f", "v_f",  # 月均价期货（特殊合约，不适合趋势研究）
]

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
        "category": get_category(symbol),
        "log_return": df["log_return"].astype(float),
    })
    _save_returns(out, table)
    print(f"[calc_log_return] {symbol} {period} → {table}: {len(out)} 行 "
          f"({out['datetime'].iloc[0]} ~ {out['datetime'].iloc[-1]})")
    return len(out)


def _save_returns(df: pd.DataFrame, table: str) -> None:
    """把对数收益率写入 SQLite 长表，按 (datetime, symbol) 主键去重覆盖。

    含 category（板块）列，来自 shared.sector.get_category。"""
    RETURNS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ('
            'datetime TEXT, symbol TEXT, category TEXT, log_return REAL,'
            'PRIMARY KEY (datetime, symbol))'
        )
        rows = [tuple(r) for r in df[["datetime", "symbol", "category", "log_return"]].to_numpy()]
        # 用 UPSERT：主键冲突时只更新 category/log_return，保留 volatility 等其它列。
        # （INSERT OR REPLACE 会删整行重建，把 volatility 清成 NULL）
        cur.executemany(
            f'INSERT INTO "{table}" (datetime, symbol, category, log_return) VALUES (?,?,?,?) '
            f'ON CONFLICT(datetime, symbol) DO UPDATE SET '
            f'category=excluded.category, log_return=excluded.log_return',
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# 统计特征表：return_stats
STATS_TABLE = "return_stats"
# period → 收益率表名（与 _PERIOD_MAP 的表名一致）
_STATS_SOURCE = {"1d": "1d_return", "week": "week_return", "mon": "mon_return"}


def calc_return_stats(period="1d", symbol=None):
    """计算各品种指定周期对数收益率的统计特征，存入 return_stats 表。

    从对应的收益率表（1d_return / week_return / mon_return）读取，按 symbol 分组
    计算：count / mean / std / min / 25% / 50% / 75% / max / skew / kurt，
    并附带 start_date / end_date / period / symbol / category。

    Args:
        period: "1d" / "week" / "mon"
        symbol: 仅计算该品种；None 则计算该表内全部品种

    Returns:
        int: 写入的行数（= 计算的品种数）。
    """
    if period not in _STATS_SOURCE:
        raise ValueError(f"period 仅支持 {list(_STATS_SOURCE)}，收到 {period!r}")
    src = _STATS_SOURCE[period]

    if not RETURNS_DB.exists():
        print(f"[calc_return_stats] 无收益率库 {RETURNS_DB}，请先 calc_log_return")
        return 0
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        if symbol:
            df = pd.read_sql(f'SELECT * FROM "{src}" WHERE symbol = ?', conn, params=(symbol,))
        else:
            df = pd.read_sql(f'SELECT * FROM "{src}"', conn)
    finally:
        conn.close()

    if df.empty:
        print(f"[calc_return_stats] {period}({src}) 无数据")
        return 0

    df["datetime"] = pd.to_datetime(df["datetime"])
    rows = []
    for sym, g in df.groupby("symbol"):
        r = g["log_return"].astype(float).dropna()
        if r.empty:
            continue
        q = r.quantile([0.25, 0.5, 0.75])
        rows.append({
            "symbol": sym,
            "category": g["category"].dropna().iloc[0] if g["category"].notna().any() else None,
            "period": period,
            "start_date": g["datetime"].min().strftime("%Y-%m-%d"),
            "end_date": g["datetime"].max().strftime("%Y-%m-%d"),
            "count": int(r.count()),
            "mean": float(r.mean()),
            "std": float(r.std()),
            "min": float(r.min()),
            "q25": float(q.loc[0.25]),
            "q50": float(q.loc[0.50]),
            "q75": float(q.loc[0.75]),
            "max": float(r.max()),
            "skew": float(r.skew()),
            "kurt": float(r.kurt()),  # 超额峰度（Fisher），正态=0
        })
    out = pd.DataFrame(rows)
    if out.empty:
        print(f"[calc_return_stats] {period} 无有效样本")
        return 0
    _save_return_stats(out)
    print(f"[calc_return_stats] {period} → {STATS_TABLE}: {len(out)} 个品种")
    return len(out)


def _save_return_stats(df: pd.DataFrame) -> None:
    """把统计特征写入 return_stats 表，按 (symbol, period) 主键覆盖。"""
    RETURNS_DB.parent.mkdir(parents=True, exist_ok=True)
    cols = ["symbol", "category", "period", "start_date", "end_date",
            "count", "mean", "std", "min", "q25", "q50", "q75", "max", "skew", "kurt"]
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{STATS_TABLE}" ('
            'symbol TEXT, category TEXT, period TEXT, '
            'start_date TEXT, end_date TEXT, '
            'count INTEGER, mean REAL, std REAL, min REAL, '
            'q25 REAL, q50 REAL, q75 REAL, max REAL, skew REAL, kurt REAL, '
            'PRIMARY KEY (symbol, period))'
        )
        ph = ", ".join("?" for _ in cols)
        cn = ", ".join(f'"{c}"' for c in cols)
        rows = [tuple(r) for r in df[cols].to_numpy()]
        cur.executemany(
            f'INSERT OR REPLACE INTO "{STATS_TABLE}" ({cn}) VALUES ({ph})', rows
        )
        conn.commit()
    finally:
        conn.close()


def ema_volatility(returns, delta=None, com=60, annualize=252):
    """指数加权波动率（AQR/Hurst TSMOM 风格，类单变量 GARCH）。

    对【滞后】平方收益做指数加权，估计每个时点的事前年化波动率：

        r̄_t   = Σ_i w_i · r_{t-1-i}                 （指数加权平均收益，滞后）
        s²_t   = annualize · Σ_i w_i · (r_{t-1-i} − r̄_t)²
        s_t    = √s²_t                               （年化波动率）

    权重 w_i = (1−d)·d^i（i=0,1,2,…），归一化；重心 COM = d/(1−d)。
    论文取 COM=60 天、annualize=261；本函数默认 com=60、annualize=252
    （与本项目其他年化口径一致，可改）。

    无前视偏差：σ_t 由 r_{t-1}, r_{t-2}, ... 估计（**不含 r_t**），
    可直接配 r_t 使用。out[0] 因无前期数据为 NaN。

    Args:
        returns:   对数收益率序列（pd.Series 或 1D array，按时间正序）。
        delta:     衰减因子 d。None 时由 com 反推：d = com/(com+1)。
        com:       权重重心（天数），delta=None 时生效。默认 60。
        annualize: 年化系数（一年的观测数）。默认 252。

    Returns:
        pd.Series：与输入等长的事前年化波动率 σ_t（配 r_t 用；前期权重未铺满为 NaN）。
    """
    r = pd.Series(returns, dtype="float64").reset_index(drop=True)
    n = len(r)
    if n == 0:
        return pd.Series(dtype="float64")

    # 由重心推 delta：COM = d/(1−d)  =>  d = COM/(COM+1)
    d = (com / (com + 1)) if delta is None else float(delta)
    if not 0 < d < 1:
        raise ValueError(f"delta 需在 (0,1)，得到 {d}")

    # 权重 (1−d)·d^i，截断到与序列等长（i=0..n-1）；已归一化（Σ=1 当 i→∞）
    i = np.arange(n)
    w = (1 - d) * np.power(d, i)  # shape (n,)

    # 指数加权平均收益 r̄_t（对每个 t，用 t 及之前的收益，权重按 i=0 在 t）
    # 用卷积：r̄_t = Σ_{i=0..t} w_i · r_{t-i}
    # 等价于 pandas ewm(alpha=1-d, adjust=True).mean()，但这里显式按公式实现。
    r_arr = r.to_numpy()
    var_ew = np.full(n, np.nan)
    # out[t] = 事前 σ_t，配 r_t 用；由 r_{t-1}, r_{t-2}, ... 估计（不含 r_t，无前视）
    for t in range(1, n):
        j = t - 1                            # 最新可用收益下标（= t-1）
        wt = w[: j + 1]                      # 权重 i=0..j
        rt = r_arr[j::-1]                    # r_{t-1}, r_{t-2}, ..., r_0
        s = wt.sum()
        if s <= 0:
            continue
        wt = wt / s                          # 归一化（前期权重和<1）
        m = (wt * rt).sum()                  # 指数加权平均收益 r̄_t
        var = (wt * (rt - m) ** 2).sum()     # 加权方差
        var_ew[t] = var

    vol = np.sqrt(var_ew * annualize)
    out = pd.Series(vol, index=r.index, name="ema_vol")

    # 前期权重未铺满（归一化前权重和明显<1）视为不可靠，置 NaN
    # 阈值：权重和达到 ~0.99 对应约 2·COM 个观测
    warmup = int(np.ceil(np.log(1 - 0.99) / np.log(d)))  # Σw≈0.99 所需点数
    if warmup < n:
        out.iloc[:warmup] = np.nan
    return out


def calc_volatility(symbol, period="1d", delta=None, com=60, annualize=252):
    """计算单品种 EMA 事前波动率 σ_t，写回收益表的 volatility 列。

    读取该 symbol 已入库的对数收益（按时间正序），调用 ema_volatility 算 σ_t，
    UPDATE 到对应行的 volatility 列（σ_t 配 r_t）。**不改动 log_return / category**。
    表若无 volatility 列会自动 ALTER 补上（迁移旧表）。

    Args:
        symbol:              品种代码
        period:              "1d" / "week" / "mon" / "1h" / "30m"
        delta/com/annualize: 透传给 ema_volatility

    Returns:
        int: 写入的非空波动率点数；无数据返回 0。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")
    table = _PERIOD_MAP[period][1]

    if not RETURNS_DB.exists():
        print(f"[calc_volatility] 无收益率库 {RETURNS_DB}，请先 calc_log_return")
        return 0
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        _ensure_column(cur, table, "volatility", "REAL")
        rows = cur.execute(
            f'SELECT datetime, log_return FROM "{table}" WHERE symbol = ? ORDER BY datetime',
            (symbol,),
        ).fetchall()
        if not rows:
            print(f"[calc_volatility] {symbol} {period} 无收益数据，跳过")
            return 0
        dts = [r[0] for r in rows]
        rets = pd.Series([r[1] for r in rows], dtype="float64")
        vol = ema_volatility(rets, delta=delta, com=com, annualize=annualize)
        upd = [(None if pd.isna(v) else float(v), dt, symbol) for dt, v in zip(dts, vol)]
        cur.executemany(
            f'UPDATE "{table}" SET volatility = ? WHERE datetime = ? AND symbol = ?', upd
        )
        conn.commit()
    finally:
        conn.close()
    n_valid = int(vol.notna().sum())
    print(f"[calc_volatility] {symbol} {period} → {table}.volatility: {n_valid} 点")
    return n_valid


def _ensure_column(cur, table, column, sql_type):
    """若表缺少某列则 ALTER 补上（用于给旧收益表加 volatility 列）。"""
    cols = {row[1] for row in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if column not in cols:
        cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {sql_type}')


def tsmom_regression(period="1d", h=1):
    """面板 TSMOM 回归（Moskowitz-Ooi-Pedersen 2012 风格），返回斜率 β。

        r_{t→t+h} / σ_t  =  α + β · r_{t-h→t}  +  ε

    跨所有品种 × 时间 pooled（重叠观测）：
      - 因变量 y：未来 h 期累计对数收益 ÷ 事前波动率 σ_t（波动率目标化）
      - 自变量 x：过去 h 期累计对数收益（动量信号）
    β>0 且显著 → 趋势（动量）存在；β<0 → 反转。给定 h 全市场只有一个 β。

    标准误优先用 statsmodels 的 HAC（Newey-West，maxlags=h，重叠观测必需）；
    未装 statsmodels 时退化为朴素 OLS SE（β 仍正确，但 t 值偏大）。

    Args:
        period: "1d" / "week" / "mon"
        h:      滞后期数（信号期 = 持有期 = h）

    Returns:
        float：β 的 t 统计量（给定 h 全市场单一值）；无数据返回 NaN。
        β/α/n 见打印。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")
    if h < 1:
        raise ValueError("h 需 >= 1")
    table = _PERIOD_MAP[period][1]

    res = {"beta": np.nan, "alpha": np.nan, "tstat": np.nan, "se": np.nan, "n": 0}
    if not RETURNS_DB.exists():
        print(f"[tsmom_regression] 无收益率库 {RETURNS_DB}")
        return res["tstat"]

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(
            f'SELECT datetime, symbol, log_return, volatility FROM "{table}" '
            f'WHERE log_return IS NOT NULL AND volatility IS NOT NULL', conn)
    finally:
        conn.close()
    if df.empty:
        return res["tstat"]

    df["datetime"] = pd.to_datetime(df["datetime"])
    xs, ys = [], []
    for _, g in df.groupby("symbol"):
        g = g.sort_values("datetime").reset_index(drop=True)
        r = g["log_return"].to_numpy(dtype=float)
        sig = g["volatility"].to_numpy(dtype=float)
        n = len(r)
        if n < 2 * h + 1:
            continue
        cum = np.concatenate(([0.0], np.cumsum(r)))        # cum[k] = Σ r[0..k-1]
        i = np.arange(h - 1, n - h)                          # 同时有过去h与未来h的位置
        past = cum[i + 1] - cum[i + 1 - h]                   # r[t-h+1 .. t]
        fwd = cum[i + 1 + h] - cum[i + 1]                    # r[t+1 .. t+h]
        sigt = sig[i]                                        # σ_t（配 r_t，事前）
        ok = (~np.isnan(past)) & (~np.isnan(fwd)) & (sigt > 0)
        for j in np.where(ok)[0]:
            xs.append(float(past[j]))
            ys.append(float(fwd[j] / sigt[j]))

    res["n"] = len(xs)
    if res["n"] < 5:
        print(f"[tsmom_regression] {period} h={h}: 有效观测不足 ({res['n']})")
        return res["tstat"]

    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    X = np.column_stack([np.ones_like(x), x])

    try:
        import statsmodels.api as sm
        m = sm.OLS(y, X).fit(cov_type="HAC", maxlags=max(1, int(h)))
        res.update(beta=float(m.params[1]), alpha=float(m.params[0]),
                   tstat=float(m.tvalues[1]), se=float(m.bse[1]))
    except Exception:
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ coef
        s2 = float(resid @ resid) / (res["n"] - 2)
        xtx_inv = np.linalg.inv(X.T @ X)
        se = float(np.sqrt(s2 * xtx_inv[1, 1]))
        res.update(beta=float(coef[1]), alpha=float(coef[0]),
                   tstat=float(coef[1] / se), se=se)

    print(f"[tsmom_regression] {period} h={h}: β={res['beta']:.4f} (t={res['tstat']:.2f}), "
          f"α={res['alpha']:.5f}, n={res['n']}")
    return res["tstat"]


if __name__ == "__main__":
    # 自测：日线 TSMOM 面板回归，h=1 / 12 / 60，返回 β 的 t 统计量
    for _h in (1, 12, 60):
        t = tsmom_regression(period="1d", h=_h)
        print(f"  → 返回 t = {t:.3f}")
