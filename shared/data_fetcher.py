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

import numpy as np
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

# period 英文 → 中文（fetch_klines 统一入口用英文，ssquant 取数时转中文）
_PERIOD_EN2CN = {"1d": "日线", "1h": "60分钟", "30m": "30分钟", "15m": "15分钟", "5m": "5分钟"}


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
    period: str = "1d",
    start_date: str = None,
    end_date: str = None,
    source: str = "ssquant",
) -> pd.DataFrame:
    """获取期货品种 K 线数据（统一入口）。

    Args:
        symbol:     品种代码，如 "rb"、"hc"
        period:     K 线周期。英文 "1d"/"week"/"mon"/"1h"/"30m"/"15m"/"5m"，
                    或中文 "日线"/"60分钟"/...（ssquant 兼容旧写法）
        start_date: 开始日期 "YYYY-MM-DD"
        end_date:   结束日期，默认今天
        source:     "ssquant"(默认，远程主力连续·后复权 rb888) 或
                    "local"(本地 k_data.db，主力连续·后复权，需先
                    fetch_klines_tushare_build 构建；仅 1d/week/mon)

    Returns:
        DataFrame，含 date/open/high/low/close/vol 等；日期为 "YYYY-MM-DD"。
        source="local" 额外含 adj_factor、oi。
    """
    if source == "local":
        return _fetch_klines_local(symbol, period, start_date, end_date)

    from ssquant.data.api_data_fetcher import get_futures_data
    from ssquant.config.trading_config import get_api_auth

    # ssquant：period 统一成中文再映射为 ssquant 内部代码
    cn_period = period if period in PERIOD_MAP else _PERIOD_EN2CN.get(period)
    if cn_period is None:
        raise ValueError(f"ssquant 不支持的 period: {period!r}（中文/英文皆可）")
    ssquant_period = PERIOD_MAP[cn_period]
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


def _report_none(df, symbol):
    """平滑后全局扫描 None/NaN/<=0，打印报告（只读，不改数据、不影响入库）。

    扫描最终要入库的 ``out``：
      - 价格列 open/high/low/close：NaN/None 或 <=0（无效价）都算坏；
      - vol/oi/adj_factor：仅 NaN/None 算坏（0 合法，不报）。
    干净打一行确认；有异常打 ⚠️ + 逐列 NaN 计数 + 前 ~20 个异常 date。
    现有 None 检查只在换月拼接点；此处补一个对整段的兜底全局扫描。
    """
    if df is None or len(df) == 0:
        return
    price_cols = [c for c in ("open", "high", "low", "close") if c in df.columns]
    other_cols = [c for c in ("vol", "oi", "adj_factor") if c in df.columns]

    # 价格异常行：价格列任一 NaN/None 或 <=0（NaN<=0 为 False，靠 isna 兜住）
    bad_mask = pd.Series(False, index=df.index)
    for c in price_cols:
        bad_mask |= df[c].isna() | (df[c] <= 0)
    n_bad = int(bad_mask.sum())

    # 逐列 NaN 计数（只列有 NaN 的列）
    nan_counts = {
        c: int(df[c].isna().sum())
        for c in price_cols + other_cols
        if int(df[c].isna().sum())
    }

    n = len(df)
    if n_bad == 0 and not nan_counts:
        print(f"[tushare] {symbol} None 扫描: 干净，无 NaN/<=0 ({n} 行)")
        return

    print(f"[tushare] ⚠️ {symbol} None 扫描: 发现 {n_bad} 行价格异常 (共 {n} 行)")
    if nan_counts:
        print(f"[tushare]   NaN 计数: {nan_counts}")
    if n_bad and "date" in df.columns:
        dates = df.loc[bad_mask, "date"].head(20).tolist()
        print(f"[tushare]   异常日期(前20): {dates}")


def _roll_dates(mp):
    """换月点 trade_date 集合：mp 中 mapping_ts_code 变化的那天。"""
    if mp is None or len(mp) == 0:
        return set()
    codes = mp["mapping_ts_code"].tolist()
    dates = mp["trade_date"].tolist()
    return {dates[i] for i in range(1, len(codes)) if codes[i] != codes[i - 1]}


def _fill_none(raw, mp):
    """逐行填补缺失（不丢弃/不截断），返回无 None 的 df。

    价格列 OHLC 的 NaN 或 <=0 视为缺失；vol/oi 仅 NaN 视为缺失（0 合法）。
    - 部分缺失（OHLC 至少一个有效）：用本行 close>open>high>low 首个有效值填其余。
    - 全缺失连续段：一律用段两头非缺失值之间线性插值（跨换月也插值，
      把整段真实变动均摊到每天，避免压成单日伪跳空）。
    - vol/oi 缺失 → 后一日填充（bfill）。
    """
    df = raw.copy()
    ohlc = ["open", "high", "low", "close"]

    # 0) 价格 <=0/非数 → NaN（vol/oi 不动：0 成交量/持仓合法）
    for c in ohlc:
        num = pd.to_numeric(df[c], errors="coerce")
        df[c] = num.where(num > 0)

    # 1) 部分缺失 → close>open>high>low 首个有效值填其余
    part = df[ohlc].isna().any(axis=1) & ~df[ohlc].isna().all(axis=1)
    for idx in df.index[part]:
        for src in ("close", "open", "high", "low"):  # 优先级 close 先
            v = df.at[idx, src]
            if not pd.isna(v):
                for c in ohlc:
                    if pd.isna(df.at[idx, c]):
                        df.at[idx, c] = v
                break
    if int(part.sum()):
        print(f"[tushare]   部分缺失 {int(part.sum())} 行，按 close>open>high>low 填充")

    # 2) 全缺失连续段 → 段两头线性插值（跨换月也插值）
    all_none = df[ohlc].isna().all(axis=1).to_numpy()
    vals = {c: df[c].to_numpy(dtype=float).copy() for c in ohlc}
    N = len(df)
    n_interp = 0
    i = 0
    while i < N:
        if not all_none[i]:
            i += 1
            continue
        j = i
        while j < N and all_none[j]:
            j += 1
        # 段 = 位置 [i, j)，两头非缺失值之间线性插值
        k = j - i
        pre = {c: (vals[c][i - 1] if i - 1 >= 0 else np.nan) for c in ohlc}
        post = {c: (vals[c][j] if j < N else np.nan) for c in ohlc}
        for c in ohlc:                       # 边界缺失时用另一头
            if np.isnan(pre[c]):
                pre[c] = post[c]
            if np.isnan(post[c]):
                post[c] = pre[c]
        for p in range(i, j):
            frac = (p - i + 1) / (k + 1)
            for c in ohlc:
                vals[c][p] = pre[c] + (post[c] - pre[c]) * frac
        n_interp += k
        i = j
    for c in ohlc:
        df[c] = vals[c]
    if n_interp:
        print(f"[tushare]   全缺失段线性插值 {n_interp} 行")

    # 3) vol/oi NaN → 后一日填充（全局）
    for c in ("vol", "oi"):
        if c in df.columns and df[c].isna().any():
            df[c] = df[c].bfill()

    return df


def _report_jumps(out, symbol, roll_set):
    """平滑后全局检查大跳变：列最大 |收益| 前 8，标注换月点（潜在未平滑拼接）。"""
    if out is None or len(out) < 2:
        return
    c = out["close"].astype(float)
    ret = np.log(c).diff()
    big = ret.abs().nlargest(8)
    n_roll = 0
    print(f"[tushare] {symbol} 平滑后最大|收益| 前8:")
    for idx in big.index:
        r = ret.loc[idx]
        if pd.isna(r):
            continue
        d = str(out.loc[idx, "date"]).replace("-", "")
        is_roll = d in roll_set
        n_roll += 1 if is_roll else 0
        print(f"   {out.loc[idx, 'date']}  {r * 100:+7.2f}%{'  换月点⚠️' if is_roll else ''}")
    if n_roll:
        print(f"   (其中 {n_roll} 个在换月点 → 疑似未平滑拼接，需关注)")


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

        # 平滑前：逐行填补 None（不丢弃早期数据），保证平滑前后整段无 None
        raw = _fill_none(raw, mp)

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

    _report_jumps(out, symbol, _roll_dates(mp))  # 平滑后检查大跳变，标注换月点
    _report_none(out, symbol)   # 平滑后全局扫描 None/<=0，打印报告（不改数据）
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
           .agg({"open": "first", "close": "last", "high": "max",
                 "low": "min", "vol": "sum", "oi": "last", "adj_factor": "last"})
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


def _fetch_klines_local(symbol, period="1d", start_date=None, end_date=None):
    """从本地 k_data.db 的 *_k_data 表读取（纯读，主力连续·后复权，已构建）。

    由 fetch_klines(source="local") 调用；period 仅 1d/week/mon。
    """
    if period not in _TS_K_TABLE:
        raise ValueError(f"本地库仅支持 {list(_TS_K_TABLE)}，收到 {period!r}")
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
