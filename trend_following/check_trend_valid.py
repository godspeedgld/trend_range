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

# tsmom_regression 各频度用的【事前波动率列】：日频用直接 EMA σ；周/月用「日频σ映射」列
# （论文口径——σ 始终源自日频，避免周/月收益数据太少、warmup 吃光）。须先由
# calc_volatility(1d) + calc_mapped_volatility(week/mon←1d) 算好对应列。
_PERIOD_VOL_COL = {"1d": "volatility", "week": "week_1d_vol", "mon": "mon_1d_vol"}

# 收益率库：项目根/data_cache/returns.db（与 CWD 无关）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RETURNS_DB = PROJECT_ROOT / "data_cache" / "returns.db"
K_DATA_DB = PROJECT_ROOT / "data_cache" / "k_data.db"
_K_DATA_TABLE = {"1d": "1d_k_data", "week": "week_k_data", "mon": "mon_k_data"}


def calc_log_return(symbol, start_date="1999-01-01", end_date=None, period="1d",
                    source="ssquant", persist=True):
    """计算单品种指定周期的对数收益率，并存入对应表。

    Args:
        symbol:     品种代码，如 "rb"（内部自动补 888 取主力连续，后复权）
        start_date: 开始日期 "YYYY-MM-DD"（默认 1999-01-01，覆盖上市全历史）
        end_date:   结束日期 "YYYY-MM-DD"（默认今天）
        period:     "mon" / "week" / "1d" / "1h" / "30m"
                    → 分别落 mon_return / week_return / 1d_return / 1h_return / 30m_return
                    （ssquant 下 "mon"/"week" 由日线重采样得到：月末 / 周五）
        source:     "ssquant"(远程，日线重采样得月/周) 或
                    "local"(本地 k_data.db，直接读该周期表，仅 1d/week/mon)
        persist:    True(默认)写库并返回行数(int)；False 不写库，返回计算结果
                    DataFrame(datetime/symbol/category/log_return) 供校验比对。

    Returns:
        persist=True  → int：写入的收益率行数（无数据返回 0）。
        persist=False → DataFrame：计算结果（无数据返回 0）。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")

    cn_period, table, resample_rule = _PERIOD_MAP[period]

    if source == "local":
        if period not in ("1d", "week", "mon"):
            raise ValueError(f"本地库仅支持 1d/week/mon，收到 {period!r}")
        df = fetch_klines(symbol, period=period, start_date=start_date,
                          end_date=end_date, source="local")
        resample_rule = None  # 本地库已是目标周期，不再重采样
    else:
        df = fetch_klines(symbol, period=cn_period, start_date=start_date,
                          end_date=end_date, source="ssquant")

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
    if not persist:
        return out
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

    对平方收益做指数加权，估计每个时点的年化波动率（**主流约定：σ_t 含 r_t**）：

        r̄_t   = Σ_i w_i · r_{t-i}                    （指数加权平均收益，含 r_t）
        s²_t   = annualize · Σ_i w_i · (r_{t-i} − r̄_t)²
        s_t    = √s²_t                               （年化波动率）

    权重 w_i = (1−d)·d^i（i=0,1,2,…），归一化；重心 COM = d/(1−d)。
    论文取 COM=60 天、annualize=261；本函数默认 com=60、annualize=252
    （与本项目其他年化口径一致，可改）。

    ⚠️ **使用约定（重要）**：本函数输出的 σ_t 由 r_t 及之前数据估计（**含 r_t**），
    因此**带前视**——直接配 r_t 用会泄露当期信息。取事前值需在调用方 shift(1)：
        sigma_exante = ema_volatility(r).shift(1)     # σ_{t-1} 配 r_t，无前视
    例外：若用 σ_t 缩放的是【未来】收益（如 r_{t+1..t+h}），σ_t 在未来窗口前已知，
    无需 shift（tsmom_regression 即此情形）。

    Args:
        returns:   对数收益率序列（pd.Series 或 1D array，按时间正序）。
        delta:     衰减因子 d。None 时由 com 反推：d = com/(com+1)。
        com:       权重重心（天数），delta=None 时生效。默认 60。
        annualize: 年化系数（一年的观测数）。默认 252。

    Returns:
        pd.Series：与输入等长的年化波动率 σ_t（**含 r_t**，使用需 shift(1)；
        前期权重未铺满为 NaN）。
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
    # out[t] = σ_t（含 r_t，主流约定）；配 r_t 用时调用方需 shift(1) 取事前
    for t in range(n):
        wt = w[: t + 1]                      # 权重 i=0..t
        rt = r_arr[t::-1]                    # r_t, r_{t-1}, ..., r_0
        s = wt.sum()
        if s <= 0:
            continue
        wt = wt / s                          # 归一化（前期权重和<1）
        m = (wt * rt).sum()                  # 指数加权平均收益 r̄_t
        var = (wt * (rt - m) ** 2).sum()     # 加权方差
        var_ew[t] = var

    vol = np.sqrt(var_ew * annualize)
    out = pd.Series(vol, index=r.index, name="ema_vol")

    # 前期权重未铺满（归一化前权重和明显<1）视为不可靠，置 NaN（无条件）
    # 阈值：权重和达到 ~0.99 所需点数 = ceil(log(0.01)/log(d))。com=60 → 279 期。
    # 统一规则：任何品种都砍前 warmup 期；数据不足 warmup 的品种（如新上市）全部 NaN
    # ——它们没有可靠的 EMA 波动率，这是诚实而非缺数据。
    warmup = int(np.ceil(np.log(1 - 0.99) / np.log(d)))
    out.iloc[:warmup] = np.nan
    return out


def calc_volatility(symbol, period="1d", delta=None, com=60, annualize=252, persist=True):
    """【计算波动率】给定 period 与 com，按 EMA 在「该频度自身收益」上算 σ_t，存 `volatility` 列。

    读取该 symbol 已入库的对数收益（按时间正序），调用 ema_volatility 算 σ_t，
    UPDATE 到对应行的 `volatility` 列（σ_t 配 r_t）。**不改动 log_return / category**。
    表若无 `volatility` 列会自动 ALTER 补上。写入前先清该品种旧值，避免残留。

    ⚠️ com 是「该频度的 bar 数」。月/周收益数据太少时，直接在本函数算 σ 会不稳、
    warmup 还吃掉前期——此时应改用 calc_mapped_volatility 从更细频度（如日频）的 σ
    映射过来。**上层自行决定是否更新、用哪一级波动率为基础**。

    Args:
        symbol:              品种代码
        period:              "1d" / "week" / "mon" / "1h" / "30m"
        delta/com/annualize: 透传给 ema_volatility
        persist:             True(默认)写库并返回非空点数(int)；False 不写库，
                             返回 DataFrame(datetime/volatility) 供校验比对。

    Returns:
        persist=True  → int：写入 `volatility` 的非空点数；无数据返回 0。
        persist=False → DataFrame：datetime/volatility（与库内 log_return 行对齐）。
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
        if not persist:
            return pd.DataFrame({"datetime": dts, "volatility": vol.to_numpy()})
        # 先清该品种旧值，避免上次计算的非空点残留（参数变更后尤为重要）
        cur.execute(f'UPDATE "{table}" SET volatility = NULL WHERE symbol = ?', (symbol,))
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


def calc_mapped_volatility(symbol, updateperiod="mon", baseperiod="1d",
                           vol_name=None, persist=True):
    """【映射波动率】把 baseperiod 的波动率对齐到 updateperiod，存 `vol_name` 列。

    典型：updateperiod="mon", baseperiod="1d" → 月度波动率 = 每月最后一个交易日的
    日频 σ（论文口径）。读取 baseperiod 表里已算好的 `volatility` 列，按 updateperiod 的
    重采样规则（mon→ME / week→W-FRI）取 .last()，对齐到周末/月末，写入
    updateperiod_return 表的 `vol_name` 列。

    回归里该列 shift(1) 即「上一周期末 baseperiod σ」= 当期收益事前波动率（无前视）。
    标签对齐：updateperiod 表的 datetime 由 calc_log_return 用同规则 resample 日线
    得到，故此处对 baseperiod σ 用同规则 resample，标签逐行一致。

    ⚠️ 前置：baseperiod 的波动率必须已由 calc_volatility 算好（存于 `volatility` 列）。
    **上层自行决定是否更新、以及用哪一级波动率为基础**。

    Args:
        symbol:       品种代码
        updateperiod: 要写入的目标频度 "week" / "mon"
        baseperiod:   取基础波动率的源频度（须更细，如 "1d"）
        vol_name:     写入 updateperiod 表的列名；None 则自动
                      f"{updateperiod}_{baseperiod}_vol"（如 mon_1d_vol）
        persist:      True(默认)写库并返回非空点数(int)；False 不写库返回 DataFrame。

    Returns:
        persist=True  → int：写入的非空点数；无数据返回 0。
        persist=False → DataFrame(datetime/<vol_name>)。
    """
    if updateperiod not in _PERIOD_MAP:
        raise ValueError(f"updateperiod 仅支持 {list(_PERIOD_MAP)}，收到 {updateperiod!r}")
    if baseperiod not in _PERIOD_MAP:
        raise ValueError(f"baseperiod 仅支持 {list(_PERIOD_MAP)}，收到 {baseperiod!r}")
    rule = _PERIOD_MAP[updateperiod][2]
    if rule is None:
        raise ValueError(f"updateperiod={updateperiod!r} 无重采样规则（仅 week/mon 可作为映射目标）")
    if vol_name is None:
        vol_name = f"{updateperiod}_{baseperiod}_vol"
    base_table, upd_table = _PERIOD_MAP[baseperiod][1], _PERIOD_MAP[updateperiod][1]

    if not RETURNS_DB.exists():
        print(f"[calc_mapped_volatility] 无收益率库 {RETURNS_DB}")
        return 0
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        base_cols = {r[1] for r in cur.execute(f'PRAGMA table_info("{base_table}")').fetchall()}
        if "volatility" not in base_cols:
            print(f"[calc_mapped_volatility] {symbol}: {base_table} 无 volatility 列，"
                  f"请先 calc_volatility period={baseperiod!r}")
            return 0
        rows = cur.execute(
            f'SELECT datetime, volatility FROM "{base_table}" '
            f'WHERE symbol = ? AND volatility IS NOT NULL ORDER BY datetime',
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print(f"[calc_mapped_volatility] {symbol}: {base_table}.volatility 无数据，"
              f"请先 calc_volatility period={baseperiod!r}")
        return 0

    s = pd.Series([float(v) for _, v in rows],
                  index=pd.to_datetime([d for d, _ in rows]))
    aligned = s.resample(rule).last().dropna()
    if aligned.empty:
        print(f"[calc_mapped_volatility] {symbol}: {baseperiod}→{updateperiod} 对齐后为空，跳过")
        return 0
    out = pd.DataFrame({
        "datetime": aligned.index.strftime("%Y-%m-%d %H:%M:%S"),
        vol_name: aligned.to_numpy(dtype=float),
    })
    if not persist:
        return out

    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        _ensure_column(cur, upd_table, vol_name, "REAL")
        # 先清该品种旧值（避免残留），再按 (datetime, symbol) 写入
        cur.execute(f'UPDATE "{upd_table}" SET "{vol_name}" = NULL WHERE symbol = ?', (symbol,))
        upd = [(float(v), dt, symbol) for dt, v in zip(out["datetime"], out[vol_name])]
        cur.executemany(
            f'UPDATE "{upd_table}" SET "{vol_name}" = ? WHERE datetime = ? AND symbol = ?', upd
        )
        conn.commit()
    finally:
        conn.close()
    n_valid = int(out[vol_name].notna().sum())
    print(f"[calc_mapped_volatility] {symbol} {baseperiod}→{updateperiod} → "
          f"{upd_table}.{vol_name}: {n_valid} 点")
    return n_valid


def _ensure_column(cur, table, column, sql_type):
    """若表缺少某列则 ALTER 补上（用于给旧收益表加 volatility 列）。"""
    cols = {row[1] for row in cur.execute(f'PRAGMA table_info("{table}")').fetchall()}
    if column not in cols:
        cur.execute(f'ALTER TABLE "{table}" ADD COLUMN {column} {sql_type}')


def calc_ret_index(symbol, period="1d", base=1000.0, persist=True):
    """【累计收益指数】从 k_data 读 close，首日归一 base，几何累积，存 `ret_index` 列。

        index_0 = base（首条 close 归一为 base）
        index_t = index_{t-1} × close_t/close_{t-1} = base × close_t/close_0

    直接取 k_data.<频度> 的 close 计算（原始价格，不经过 log_return）。收益表首行是
    第 2 个 bar（首日无 diff 被丢），故首行 index = base × close_1/close_0；base 对应
    首日 close（不在收益表内）。仅支持 1d/week/mon（k_data 仅此三表）。

    Args:
        symbol:  品种代码
        period:  "1d" / "week" / "mon"
        base:    首日基准值（默认 1000）
        persist: True(默认)写库并返回非空点数(int)；False 不写库返回 DataFrame。

    Returns:
        persist=True  → int：写入的非空点数；无数据返回 0。
        persist=False → DataFrame(datetime/ret_index)。
    """
    if period not in _K_DATA_TABLE:
        raise ValueError(f"period 仅支持 {list(_K_DATA_TABLE)}（k_data 仅此三表），收到 {period!r}")
    table, ktable = _PERIOD_MAP[period][1], _K_DATA_TABLE[period]

    if not K_DATA_DB.exists():
        print(f"[calc_ret_index] 无 K 线库 {K_DATA_DB}")
        return 0
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        rows = conn.execute(
            f'SELECT date, close FROM "{ktable}" WHERE symbol = ? AND close IS NOT NULL ORDER BY date',
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        print(f"[calc_ret_index] {symbol} {period}: {ktable} 无 close，跳过")
        return 0
    dates = [r[0] for r in rows]
    closes = np.array([float(r[1]) for r in rows], dtype=float)
    idx = base * closes / closes[0]                       # index_t = base × close_t/close_0
    # 收益表首行对应第 2 个 bar（首日 base 不在表内），故写 idx[1:]
    out_dates, out_idx = dates[1:], idx[1:]
    if not persist:
        return pd.DataFrame({"datetime": [f"{d} 00:00:00" for d in out_dates],
                             "ret_index": out_idx})

    if not RETURNS_DB.exists():
        print(f"[calc_ret_index] 无收益率库 {RETURNS_DB}")
        return 0
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        cur = conn.cursor()
        _ensure_column(cur, table, "ret_index", "REAL")
        cur.execute(f'UPDATE "{table}" SET ret_index = NULL WHERE symbol = ?', (symbol,))
        upd = [(float(v), f"{d} 00:00:00", symbol) for d, v in zip(out_dates, out_idx)]
        cur.executemany(
            f'UPDATE "{table}" SET ret_index = ? WHERE datetime = ? AND symbol = ?', upd
        )
        conn.commit()
    finally:
        conn.close()
    n_valid = int(np.isfinite(out_idx).sum())
    print(f"[calc_ret_index] {symbol} {period} → {table}.ret_index: {n_valid} 点 (base={base}, 源 {ktable})")
    return n_valid


def tsmom_regression(period="1d", h=1, start_date=None, end_date=None, symbols=None,
                     min_years=2.0):
    """单期波动率目标化收益的滞后 h 自相关回归（面板 pooled），返回 β 的 t 统计量。

        z_t   = r_t / σ_{t-1}            （单期对数收益 ÷ 前一期事前波动率）
        z_t   = α + β · z_{t-h}  +  ε

    跨所有品种 × 时间 pooled（矩阵视角：z 为 时间×品种，含 NaN——早期品种/波动率
    warmup 处为空；逐 t 取 z_t 对 z_{t-h} 的非空配对进入回归）。
      - β>0 且显著 → 滞后 h 处正自相关（动量）
      - β<0 且显著 → 反转
    给定 h 全市场只有一个 β。

    σ_{t-1} = <vol 列>.shift(1)，vol 列按频度取（_PERIOD_VOL_COL）：日频=volatility
    （EMA 直接估），周/月=week_1d_vol/mon_1d_vol（日频σ映射到周末/月末，论文口径）。
    shift(1) 后即为上一周期末的事前 σ，配当期 r 无前视。标准误按时间聚类（论文口径）。

    Args:
        period:     "1d" / "week" / "mon"
        h:          滞后阶数（z_t 对 z_{t-h} 回归）
        start_date: 样本起始日 "YYYY-MM-DD"（含），None 则不限
        end_date:   样本结束日 "YYYY-MM-DD"（含），None 则不限；用于分段子样本检验
        symbols:    指定品种集合（iterable），None 则全部；用于固定品种集使跨 h 可比
        min_years:  上市不足此年数的品种剔除（默认 2.0）。按频度折算 bar 数
                    （日 252/周 52/月 12 ×年数）取该表行数门槛；None 则不限制。

    Returns:
        float：β 的 t 统计量（给定 h 全市场单一值）；无数据返回 NaN。β/α/n 见打印。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")
    if h < 1:
        raise ValueError("h 需 >= 1")
    table = _PERIOD_MAP[period][1]
    vol_col = _PERIOD_VOL_COL[period]

    res = {"beta": np.nan, "alpha": np.nan, "tstat": np.nan, "se": np.nan, "n": 0}
    if not RETURNS_DB.exists():
        print(f"[tsmom_regression] 无收益率库 {RETURNS_DB}")
        return res["tstat"]

    sql = (f'SELECT datetime, symbol, log_return, "{vol_col}" AS vol FROM "{table}" '
           f'WHERE log_return IS NOT NULL AND "{vol_col}" IS NOT NULL')
    params = []
    if start_date:
        sql += " AND datetime >= ?"; params.append(f"{start_date} 00:00:00")
    if end_date:
        sql += " AND datetime <= ?"; params.append(f"{end_date} 23:59:59")
    if symbols is not None:
        syms = list(symbols)
        if not syms:
            return res["tstat"]
        ph = ",".join("?" * len(syms))
        sql += f" AND symbol IN ({ph})"; params.extend(str(s) for s in syms)
    if min_years is not None:
        bpy = {"1d": 252, "week": 52, "mon": 12}[period]
        min_bars = int(min_years * bpy)
        sql += (f' AND symbol IN (SELECT symbol FROM "{table}" '
                f'GROUP BY symbol HAVING COUNT(*) >= {min_bars})')
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return res["tstat"]

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values(["symbol", "datetime"]).reset_index(drop=True)
    # eq(2)：z_t = r_t/σ_{t-1}（事前缩放，σ 来自对应频度的 vol 列），x = z_{t-h}
    df["z"] = (df["log_return"].astype(float)
               / df.groupby("symbol")["vol"].shift(1))
    df["z"] = df["z"].replace([np.inf, -np.inf], np.nan)
    df["x"] = df.groupby("symbol")["z"].shift(h)
    v = df.dropna(subset=["z", "x"])
    v = v[np.isfinite(v["z"]) & np.isfinite(v["x"])]
    res["n"] = len(v)
    if res["n"] < 5:
        print(f"[tsmom_regression] {period} h={h}: 有效观测不足 ({res['n']})")
        return res["tstat"]

    # 面板 pooled OLS；标准误按时间聚类（论文口径：group-wise clustering by time）
    y = v["z"].to_numpy(float)
    X = np.column_stack([np.ones(res["n"]), v["x"].to_numpy(float)])
    clst_freq = {"1d": "D", "week": "W", "mon": "M"}[period]
    clusters = pd.factorize(v["datetime"].dt.to_period(clst_freq))[0]
    try:
        import statsmodels.api as sm
        m = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": clusters})
        res.update(beta=float(m.params[1]), alpha=float(m.params[0]),
                   tstat=float(m.tvalues[1]), se=float(m.bse[1]))
    except Exception:
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = y - X @ c
        s2 = float(r @ r) / (res["n"] - 2)
        se = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1]))
        res.update(beta=float(c[1]), alpha=float(c[0]), tstat=float(c[1] / se), se=se)

    print(f"[tsmom_regression] {period} h={h}: β={res['beta']:.4f} (t={res['tstat']:.2f}), "
          f"α={res['alpha']:.5f}, n={res['n']} (时间聚类SE)")
    return res["tstat"]


def tsmom_regression_raw(period="1d", h=1, start_date=None, end_date=None, symbols=None,
                         min_years=2.0):
    """【原始收益版】滞后 h 自相关回归——只用对数收益，不除波动率。

        r_t   = α + β · r_{t-h}  +  ε

    与 tsmom_regression 的区别：因变量/自变量都是原始 r（不做 r/σ 波动率目标化）。
    用于对照「波动率缩放前」的收益自相关结构——不跨品种按波动率归一，高波动品种
    权重更大。数据读取、频度、日期/品种/上市年限过滤、时间聚类标准误均与
    tsmom_regression 一致（仅不读、不用 vol 列）。

    Args:
        period:     "1d" / "week" / "mon"
        h:          滞后阶数（r_t 对 r_{t-h} 回归）
        start_date: 样本起始日 "YYYY-MM-DD"（含），None 则不限
        end_date:   样本结束日 "YYYY-MM-DD"（含），None 则不限
        symbols:    指定品种集合（iterable），None 则全部
        min_years:  上市不足此年数的品种剔除（默认 2.0）；None 则不限制

    Returns:
        float：β 的 t 统计量（给定 h 全市场单一值）；无数据返回 NaN。β/α/n 见打印。
    """
    if period not in _PERIOD_MAP:
        raise ValueError(f"period 仅支持 {list(_PERIOD_MAP)}，收到 {period!r}")
    if h < 1:
        raise ValueError("h 需 >= 1")
    table = _PERIOD_MAP[period][1]

    res = {"beta": np.nan, "alpha": np.nan, "tstat": np.nan, "se": np.nan, "n": 0}
    if not RETURNS_DB.exists():
        print(f"[tsmom_regression_raw] 无收益率库 {RETURNS_DB}")
        return res["tstat"]

    sql = (f'SELECT datetime, symbol, log_return FROM "{table}" '
           f'WHERE log_return IS NOT NULL')
    params = []
    if start_date:
        sql += " AND datetime >= ?"; params.append(f"{start_date} 00:00:00")
    if end_date:
        sql += " AND datetime <= ?"; params.append(f"{end_date} 23:59:59")
    if symbols is not None:
        syms = list(symbols)
        if not syms:
            return res["tstat"]
        ph = ",".join("?" * len(syms))
        sql += f" AND symbol IN ({ph})"; params.extend(str(s) for s in syms)
    if min_years is not None:
        bpy = {"1d": 252, "week": 52, "mon": 12}[period]
        min_bars = int(min_years * bpy)
        sql += (f' AND symbol IN (SELECT symbol FROM "{table}" '
                f'GROUP BY symbol HAVING COUNT(*) >= {min_bars})')
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
    if df.empty:
        return res["tstat"]

    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values(["symbol", "datetime"]).reset_index(drop=True)
    # 原始收益自相关：z_t = r_t（不除 σ），x = r_{t-h}
    df["z"] = df["log_return"].astype(float)
    df["x"] = df.groupby("symbol")["z"].shift(h)
    v = df.dropna(subset=["z", "x"])
    v = v[np.isfinite(v["z"]) & np.isfinite(v["x"])]
    res["n"] = len(v)
    if res["n"] < 5:
        print(f"[tsmom_regression_raw] {period} h={h}: 有效观测不足 ({res['n']})")
        return res["tstat"]

    # 面板 pooled OLS；标准误按时间聚类
    y = v["z"].to_numpy(float)
    X = np.column_stack([np.ones(res["n"]), v["x"].to_numpy(float)])
    clst_freq = {"1d": "D", "week": "W", "mon": "M"}[period]
    clusters = pd.factorize(v["datetime"].dt.to_period(clst_freq))[0]
    try:
        import statsmodels.api as sm
        m = sm.OLS(y, X).fit(cov_type="cluster", cov_kwds={"groups": clusters})
        res.update(beta=float(m.params[1]), alpha=float(m.params[0]),
                   tstat=float(m.tvalues[1]), se=float(m.bse[1]))
    except Exception:
        c, *_ = np.linalg.lstsq(X, y, rcond=None)
        r = y - X @ c
        s2 = float(r @ r) / (res["n"] - 2)
        se = float(np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1]))
        res.update(beta=float(c[1]), alpha=float(c[0]), tstat=float(c[1] / se), se=se)

    print(f"[tsmom_regression_raw] {period} h={h}: β={res['beta']:.4f} (t={res['tstat']:.2f}), "
          f"α={res['alpha']:.5f}, n={res['n']} (时间聚类SE, 原始收益)")
    return res["tstat"]


if __name__ == "__main__":
    # 自测：日线 TSMOM 面板回归，h=1 / 12 / 60，返回 β 的 t 统计量
    for _h in (1, 12, 60):
        t = tsmom_regression(period="1d", h=_h)
        print(f"  → 返回 t = {t:.3f}")
