"""共享数据获取工具 — K 线 OHLCV 数据。

独立于任何 Skill，供 indicator_calc、agent 等统一调用。
依赖 ssquant 的 get_futures_data。

用法:
    from shared.data_fetcher import fetch_klines

    df = fetch_klines("rb", period="日线", start_date="2025-01-01", end_date="2025-03-31")
    # 返回 DataFrame: date, open, high, low, close, volume, symbol, ...
"""

import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# 项目根（shared 的上一级），保证路径与 CWD 无关
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# K 线周期映射：中文 → ssquant 格式
# 注：不含"月线"——data_server 的 M 被当作分钟(1M)，月线需由日线重采样得到。
PERIOD_MAP = {
    "日线": "1d",
    "60分钟": "1h",
    "30分钟": "30m",
    "15分钟": "15m",
    "5分钟": "5m",
}


def list_varieties(refresh: bool = False) -> pd.DataFrame:
    """获取全部期货品种清单（品种代码 rb/hc/au，非具体合约 rb888/rb2609）。

    数据来自 ssquant 合约信息服务（kanpan789 合约信息接口）。
    品种代码即 fetch_klines() 接受的 symbol（会自动补 888 取主力连续）。

    Args:
        refresh: True 时强制刷新合约信息缓存。

    Returns:
        DataFrame，列：
          variety              品种代码，如 'rb'/'hc'/'au'
          variety_name         品种名称，如 '螺纹钢'/'热轧卷板'/'黄金'
          exchange             交易所，如 'SHFE'/'DCE'/'CFFEX'
          main_contract        当前主力合约，如 'rb2510'
          contract_multiplier  合约乘数
          price_tick           最小变动价位
    """
    from ssquant.data.contract_info import get_contract_service

    svc = get_contract_service()
    if refresh:
        svc.refresh()
    rows = svc.list_varieties()
    return pd.DataFrame(rows)


def fetch_klines(
    symbol: str,
    period: str = "日线",
    start_date: str = None,
    end_date: str = None,
) -> pd.DataFrame:
    """获取期货品种 K 线数据。

    使用 ssquant 的 get_futures_data 接口获取 OHLCV 数据。
    品种代码自动补 888 后缀（主力连续合约），后复权。

    Args:
        symbol: 品种代码，如 "rb"、"hc"
        period: K 线周期，如 "日线"、"60分钟"
        start_date: 开始日期 "YYYY-MM-DD"
        end_date: 结束日期，默认今天

    Returns:
        DataFrame with columns: date, open, high, low, close, volume, symbol, ...
        日期为 "YYYY-MM-DD" 字符串格式。
    """
    from ssquant.data.api_data_fetcher import get_futures_data
    from ssquant.config.trading_config import get_api_auth

    ssquant_period = PERIOD_MAP.get(period, "1d")
    username, password = get_api_auth()

    # 品种代码补 888（主力连续），如 rb → rb888
    ssymbol = symbol if symbol.endswith("888") else f"{symbol}888"

    # 日期格式统一为 YYYY-MM-DD
    fmt_date = start_date.replace("/", "-") if start_date else None
    fmt_end = (end_date or datetime.now().strftime("%Y-%m-%d")).replace("/", "-")

    try:
        df = get_futures_data(
            symbol=ssymbol,
            start_date=fmt_date,
            end_date=fmt_end,
            username=username,
            password=password,
            kline_period=ssquant_period,
            adjust_type="1",  # 后复权
            use_cache=True,
            save_data=True,
        )
        if df is not None and not df.empty:
            # get_futures_data 返回 datetime 为 index，reset 出来
            if "datetime" not in df.columns and df.index.name == "datetime":
                df = df.reset_index()
            elif df.index.name != "datetime" and "datetime" not in df.columns:
                df = df.reset_index()

            # 统一列名为小写
            df.columns = [c.lower() for c in df.columns]

            # 统一 symbol 为输入的品种代码（去掉 888 后缀）
            df["symbol"] = symbol

            if "date" not in df.columns and "datetime" in df.columns:
                df["date"] = pd.to_datetime(df["datetime"]).dt.strftime("%Y-%m-%d")
            elif "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

            return df
    except Exception as e:
        print(f"[data_fetcher] ssquant get_futures_data failed for {symbol}: {e}")

    return pd.DataFrame()


# ==================== Tushare 通路（主力连续·后复权，含 adj_factor）====================
# tushare 的 fut_daily('RB.SHF') 返回主力连续·未复权序列（已按 mapping 拼接），
# fut_mapping 给每日主力对应的月合约。换月处有跳空 → 需后复权。
# 后复权：最早价不变（adj_factor 从 1 起累积），ratio=旧合约当日收/新合约当日收。

# 月/周/日 K 线库：项目根/data_cache/k_data.db
K_DATA_DB = PROJECT_ROOT / "data_cache" / "k_data.db"

# period → k_data 表名 / 重采样频率
_TS_K_TABLE = {"1d": "1d_k_data", "week": "week_k_data", "mon": "mon_k_data"}
_TS_RESAMPLE = {"week": "W-FRI", "mon": "ME"}

# ssquant 交易所名 → tushare ts_code 后缀（郑商所是 ZCE，非 CZC/CZCE）
_SSQ_TO_TS_EXCH = {"SHFE": "SHF", "DCE": "DCE", "CZCE": "ZCE",
                   "CFFEX": "CFX", "INE": "INE", "GFEX": "GFE"}
_TS_EXCH_CACHE = None  # {品种小写: tushare交易所代码}


def _read_env(key):
    """从项目根 .env 读取某 key（大小写不敏感），返回去引号的值。"""
    p = PROJECT_ROOT / ".env"
    if not p.exists():
        return None
    for ln in p.read_text(encoding="utf-8").splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            if k.strip().upper() == key:
                return v.strip().strip('"').strip("'")
    return None


def _get_tushare_pro():
    import tushare as ts
    tok = _read_env("TUSHARE_TOKEN")
    if not tok:
        raise RuntimeError("未在 .env 找到 TUSHARE_TOKEN，无法用 tushare")
    return ts.pro_api(tok)


def _ts_cont_code(symbol):
    """品种代码 → tushare 连续合约代码，如 rb → RB.SHF。"""
    global _TS_EXCH_CACHE
    if _TS_EXCH_CACHE is None:
        try:
            df = list_varieties()
            _TS_EXCH_CACHE = {
                r["variety"].lower(): _SSQ_TO_TS_EXCH.get(r["exchange"], r["exchange"])
                for _, r in df.iterrows()
            }
        except Exception as e:
            raise RuntimeError(f"取交易所映射失败（list_varieties）：{e}")
    exch = _TS_EXCH_CACHE.get(symbol.lower())
    if not exch:
        raise ValueError(f"未知品种 {symbol}，无法映射交易所")
    return f"{symbol.upper()}.{exch}"


def _ts_paged(pro, kind, ts_code, start, end):
    """按年分页拉 fut_daily / fut_mapping（单次≤2000 行）。
    start/end 为 'YYYY-MM-DD'。返回 DataFrame（含 trade_date，YYYYMMDD）。"""
    out, sy, ey = [], int(start[:4]), int(end[:4])
    for y in range(sy, ey + 1):
        s = f"{y}0101" if y > sy else start.replace("-", "")
        e = f"{y}1231" if y < ey else end.replace("-", "")
        if kind == "daily":
            d = pro.fut_daily(ts_code=ts_code, start_date=s, end_date=e,
                              fields="ts_code,trade_date,open,high,low,close,vol,oi")
        else:
            d = pro.fut_mapping(ts_code=ts_code, start_date=s, end_date=e)
        if d is not None and len(d):
            out.append(d)
        time.sleep(0.05)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _max_date_and_factor(table, symbol):
    """本地表中该 symbol 最大 date 及其 adj_factor；无则 (None, 1.0)。"""
    if not K_DATA_DB.exists():
        return None, 1.0
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        row = conn.execute(
            f'SELECT date, adj_factor FROM "{table}" WHERE symbol=? ORDER BY date DESC LIMIT 1',
            (symbol,),
        ).fetchone()
        if not row:
            return None, 1.0
        return row[0], (float(row[1]) if row[1] is not None else 1.0)
    finally:
        conn.close()


def _save_k_data(table, df):
    """UPSERT 写入 *_k_data（symbol,date,open,close,high,low,vol,oi,adj_factor）。"""
    K_DATA_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS "{table}" ('
            "symbol TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL, "
            "vol REAL, oi REAL, adj_factor REAL, PRIMARY KEY (symbol, date))"
        )
        cols = ["symbol", "date", "open", "close", "high", "low", "vol", "oi", "adj_factor"]
        ph = ", ".join("?" for _ in cols)
        cn = ", ".join(f'"{c}"' for c in cols)
        rows = [tuple(r) for r in df[cols].to_numpy()]
        cur.executemany(
            f'INSERT INTO "{table}" ({cn}) VALUES ({ph}) ON CONFLICT(symbol,date) DO UPDATE SET '
            "open=excluded.open, close=excluded.close, high=excluded.high, low=excluded.low, "
            "vol=excluded.vol, oi=excluded.oi, adj_factor=excluded.adj_factor",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _delete_k_data_before(table, symbol, cut_date):
    """删除某 symbol date <= cut_date 的行（用于清掉婴儿期/NaN 残留）。"""
    if not K_DATA_DB.exists():
        return
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        conn.execute(
            f'DELETE FROM "{table}" WHERE symbol=? AND date <= ?', (symbol, cut_date)
        )
        conn.commit()
    finally:
        conn.close()


def _build_tushare_daily(symbol, start_date="1999-01-01", end_date=None):
    """从 tushare 拉主力连续日线，后复权（增量），写入 1d_k_data。"""
    end_date = end_date or datetime.now().strftime("%Y-%m-%d")
    table = _TS_K_TABLE["1d"]
    pro = _get_tushare_pro()
    cont = _ts_cont_code(symbol)

    # 增量：本地最大 date + 该处 adj_factor
    max_date, f_start = _max_date_and_factor(table, symbol)
    fetch_start = max_date or start_date

    raw = _ts_paged(pro, "daily", cont, fetch_start, end_date)
    if raw.empty:
        print(f"[tushare] {symbol} {fetch_start}~{end_date} 无数据")
        return 0
    raw = raw.sort_values("trade_date").reset_index(drop=True)
    raw["trade_date"] = raw["trade_date"].astype(str)

    # 换月点：mapping 中 mapping_ts_code 变化的那天
    mp = _ts_paged(pro, "mapping", cont, fetch_start, end_date)
    rolls = []  # (roll_date_yyyymmdd, 旧月合约)
    if not mp.empty:
        mp = mp.sort_values("trade_date").reset_index(drop=True)
        mp["trade_date"] = mp["trade_date"].astype(str)
        md = max_date.replace("-", "") if max_date else None
        for i in range(1, len(mp)):
            if mp.loc[i, "mapping_ts_code"] != mp.loc[i - 1, "mapping_ts_code"]:
                rd = mp.loc[i, "trade_date"]
                if md and rd <= md:
                    continue  # 增量：跳过已处理的换月（其效应已在 f_start 内）
                rolls.append((rd, mp.loc[i - 1, "mapping_ts_code"]))

    # 逐换月点累积 adj_factor；ratio = 旧合约收 / 新主力当日收
    close_by_date = dict(zip(raw["trade_date"], pd.to_numeric(raw["close"], errors="coerce")))
    roll_f = []  # (roll_date, F_after)
    cur_f = f_start
    lookback = 0     # 用了非 rd 当日价（节假日/无成交，回看解决）
    data_err = []    # 窗口内仍无价 → 疑似数据异常，待排查
    for rd, old_c in rolls:
        new_close = close_by_date.get(rd)
        if new_close is None or pd.isna(new_close) or new_close == 0:
            data_err.append((old_c, rd, "新主力无价"))
            continue
        # 回看窗口：rd 往前 20 个自然日，取旧合约最新一条收盘（处理节假日/当日无成交）
        start_lb = (pd.Timestamp(rd) - pd.Timedelta(days=20)).strftime("%Y%m%d")
        try:
            row = pro.fut_daily(ts_code=old_c, start_date=start_lb, end_date=rd,
                                fields="trade_date,close")
        except Exception:
            row = None
        time.sleep(0.05)
        if row is None or row.empty:
            data_err.append((old_c, rd, "窗口内无价"))
            continue
        row = row.sort_values("trade_date").iloc[-1]   # 最新（≤rd）一条
        if pd.isna(row["close"]):
            data_err.append((old_c, rd, "close为NaN"))
            continue
        if str(row["trade_date"]) != rd:
            lookback += 1
        cur_f *= float(row["close"]) / float(new_close)
        roll_f.append((rd, cur_f))

    # 给每天分配 adj_factor（= 截至该日的累积 F），并后复权 OHLC
    adj, ri = [], 0
    now_f = f_start
    for td in raw["trade_date"]:
        while ri < len(roll_f) and roll_f[ri][0] <= td:
            now_f = roll_f[ri][1]
            ri += 1
        adj.append(now_f)
    raw["adj_factor"] = adj
    for c in ("open", "high", "low", "close"):
        raw[c] = raw[c].astype(float) * raw["adj_factor"]

    out = pd.DataFrame({
        "symbol": symbol,
        "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
        "open": raw["open"], "close": raw["close"], "high": raw["high"], "low": raw["low"],
        "vol": raw["vol"], "oi": raw["oi"], "adj_factor": raw["adj_factor"],
    })

    # 若有换月数据异常：丢弃「最后一个异常换月」及之前的婴儿期数据，
    # 保留之后干净段（其内换月全部成功 → 无跳空）；并重新锚定 adj_factor 首日=1。
    infancy_cut = None
    abnormal = []
    if data_err:
        err_dates = sorted({d for _, d, _ in data_err})  # YYYYMMDD
        abnormal = [d for d in err_dates if d >= "20160101"]  # 2016+ 仍异常 → 非婴儿期
        last_err = err_dates[-1]
        infancy_cut = pd.to_datetime(last_err, format="%Y%m%d").strftime("%Y-%m-%d")
        n0 = len(out)
        out = out[out["date"] > infancy_cut].reset_index(drop=True)
        if len(out) and (f0 := float(out["adj_factor"].iloc[0])):
            for c in ("open", "close", "high", "low"):
                out[c] = out[c] / f0
            out["adj_factor"] = out["adj_factor"] / f0
        print(f"[tushare]   丢弃婴儿期 {n0 - len(out)} 行(≤{infancy_cut})，保留 {len(out)} 行")
        if abnormal:
            print(f"[tushare]   ⚠️ 2016+ 仍有 {len(abnormal)} 个异常换月(非婴儿期): {abnormal}")
        _delete_k_data_before(table, symbol, infancy_cut)

    _save_k_data(table, out)
    extra = []
    if lookback:
        extra.append(f"回看解决 {lookback}")
    if data_err:
        extra.append(f"数据异常 {len(data_err)}")
    sk = ("（" + "，".join(extra) + "）") if extra else ""
    if len(out):
        print(f"[tushare] {symbol} 1d → {table}: {len(out)} 行 "
              f"({out['date'].iloc[0]} ~ {out['date'].iloc[-1]}, 换月点 {len(roll_f)}{sk})")
    else:
        print(f"[tushare] {symbol} 1d: 截断后无数据")
    return len(out)


def _build_tushare_resampled(symbol, period):
    """从 1d_k_data 重采样到 week/mon，写入对应表（前提：1d 已构建）。"""
    freq, table = _TS_RESAMPLE[period], _TS_K_TABLE[period]
    if not K_DATA_DB.exists():
        print(f"[tushare] {symbol} {period}: 无 1d_k_data，请先 build period='1d'")
        return 0
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        df = pd.read_sql(
            f'SELECT date,open,close,high,low,vol,oi,adj_factor FROM "1d_k_data" '
            f"WHERE symbol=? ORDER BY date", conn, params=(symbol,))
    finally:
        conn.close()
    if df.empty:
        print(f"[tushare] {symbol} {period}: 1d_k_data 无该品种数据")
        return 0
    df["date"] = pd.to_datetime(df["date"])
    agg = (df.set_index("date")
           .resample(freq)
           .agg(open="first", close="last", high="max", low="min",
                vol="sum", oi="last", adj_factor="last")
           .dropna(subset=["open"])
           .reset_index())
    agg["date"] = agg["date"].dt.strftime("%Y-%m-%d")
    agg.insert(0, "symbol", symbol)
    _save_k_data(table, agg)
    print(f"[tushare] {symbol} {period} → {table}: {len(agg)} 行")
    return len(agg)


def fetch_klines_tushare_build(symbol, period="1d", start_date="1999-01-01",
                               end_date=None, adjust="post"):
    """从 tushare 构建主力连续·后复权 K 线并入库（增量）。

    - period='1d'：tushare fut_daily(连续代码) + fut_mapping(换月点) → 后复权 → 1d_k_data
    - period='week'/'mon'：从已构建的 1d_k_data 重采样 → week_k_data / mon_k_data
    - 增量：1d 只拉本地最大 date 之后的尾部数据 + 仅处理新换月点（旧数据不动）
    - 表字段：symbol, date, open, close, high, low, vol, oi, adj_factor

    Args:
        symbol:     品种代码，如 "rb"
        period:     "1d" / "week" / "mon"
        start_date: 首次构建起始日（默认 1999-01-01，覆盖上市全历史）
        end_date:   结束日（默认今天）
        adjust:     仅支持 "post"（后复权）
    """
    if period not in _TS_K_TABLE:
        raise ValueError(f"period 仅支持 {list(_TS_K_TABLE)}")
    if adjust != "post":
        raise ValueError("仅支持 adjust='post'（后复权）")
    if period == "1d":
        return _build_tushare_daily(symbol, start_date, end_date)
    return _build_tushare_resampled(symbol, period)


def fetch_klines_tushare(symbol, period="1d", start_date=None, end_date=None):
    """从本地 *_k_data 表读取（纯读，不拼接/不复权）。"""
    if period not in _TS_K_TABLE:
        raise ValueError(f"period 仅支持 {list(_TS_K_TABLE)}")
    table = _TS_K_TABLE[period]
    if not K_DATA_DB.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        sql = (f'SELECT date,symbol,open,close,high,low,vol,oi,adj_factor '
               f'FROM "{table}" WHERE symbol=?')
        params = [symbol]
        if start_date:
            sql += " AND date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND date <= ?"
            params.append(end_date)
        sql += " ORDER BY date"
        return pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()
