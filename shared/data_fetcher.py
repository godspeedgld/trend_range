"""共享数据获取工具 — K 线 OHLCV 数据。

独立于任何 Skill，供 indicator_calc、agent 等统一调用。
依赖 ssquant 的 get_futures_data。

用法:
    from shared.data_fetcher import fetch_klines

    df = fetch_klines("rb", period="日线", start_date="2025-01-01", end_date="2025-03-31")
    # 返回 DataFrame: date, open, high, low, close, volume, symbol, ...
"""

from datetime import datetime

import pandas as pd

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
