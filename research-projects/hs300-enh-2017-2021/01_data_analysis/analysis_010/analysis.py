"""analysis_010 — 中芯国际(688981.SH) 单股：LLT 牛熊 × v3 阻力突破。

规则（用户指定）：
  开仓：v3 阻力突破事件（同日取 degree 最大，degree≤5）【且】事件日个股 LLT(d=60)
       切线斜率>0（个股牛市）
  平仓（两条，t 收盘判定）：
       ① 吊灯：close < 自信号日起最高 high − 4×ATR(14)（Wilder 口径）
       ② 固定止损：close < 突破价×0.95（突破价 = 信号日收盘 close_sig，
          沿 analysis_005 更新一"固定止损5%（突破价=信号日收盘基准）"口径）
  执行：t 收盘信号 → t+1 开盘成交（与项目引擎一致）；全仓单股复利。
  对照：无 LLT 闸门版（纯 v3 突破 + 同款平仓），量化 LLT 闸门在该股的贡献。

数据：本地 warehouse stock_bar1d（后复权），2020-07-16 上市 ~ 2026-08-21
（用户"15年至今"= 该股全部 A 股历史）。暖期：v3 状态机(~30bar)+LLT(~90bar) 收敛，
首信号约 2020-11 起。

口径注意：
  - v3 算法 import shared/plateau_algo_v3（冻结原版）；LLT import shared/llt60_precompute
    （与 strategy_007 同源，α=2/61）；ATR14 用 pandas Wilder ewm(alpha=1/14)（口径铁律）
  - 无未来：LLT/ATR/v3 事件 t 日值仅由 ≤t bar 推出；t+1 开盘执行
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range")
PROJ = ROOT / "replication/research-projects/hs300-enh-2017-2021"
HERE = Path(__file__).resolve().parent
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from llt60_precompute import _llt                     # noqa: E402  与 strategy_007 同源
from plateau_algo_v3 import run_band_breakout        # noqa: E402  v3 冻结原版

SYMBOL = "688981.SH"
LLT_D, ATR_N, ATR_MULT, STOP_PCT, MAX_DEGREE = 60, 14, 4.0, 0.05, 5


def load_data() -> pd.DataFrame:
    con = duckdb.connect(str(ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"),
                         read_only=True)
    df = con.execute("SELECT date, open, high, low, close FROM stock_bar1d "
                     "WHERE instrument='688981.SH' ORDER BY date").fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna().reset_index(drop=True)
    df.to_csv(HERE / "smic_daily.csv", index=False)
    return df


def atr14(df: pd.DataFrame) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / ATR_N, adjust=False, min_periods=ATR_N).mean()


def build_signals(df: pd.DataFrame) -> pd.DataFrame:
    events, _, _ = run_band_breakout(df.rename(columns={}))
    if len(events) == 0:
        return pd.DataFrame(columns=["date", "degree", "line", "close_sig"])
    ev = pd.DataFrame(events)
    ev = (ev.sort_values("degree", ascending=False)
            .drop_duplicates(["date"], keep="first"))
    ev = ev[ev["degree"] <= MAX_DEGREE]
    llt_up = _llt(df.set_index("date")["close"], LLT_D).diff() > 0
    ev["llt_up"] = [bool(llt_up.get(pd.Timestamp(d), False)) for d in ev["date"]]
    return ev.reset_index(drop=True)


def backtest(df: pd.DataFrame, ev: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """事件回测：t 收盘信号 → t+1 开盘成交；全仓复利。返回 (trades, 日收益序列)。"""
    dates = df["date"].tolist()
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    atr = atr14(df).to_numpy(float)
    pos = {d: i for i, d in enumerate(dates)}
    sig_by_date = {pd.Timestamp(r.date): r for r in ev.itertuples()}

    trades, eq, nav = [], [], 1.0
    in_pos = False
    entry_i = sig_i = -1
    for t in range(len(dates)):
        d = dates[t]
        ret = 0.0
        if in_pos:
            # t 收盘判定离场（吊灯 / 5% 止损）
            post_high = h[sig_i:t + 1].max()
            stop = c[sig_i] * (1 - STOP_PCT)
            if (not np.isnan(atr[t]) and c[t] < post_high - ATR_MULT * atr[t]) or c[t] < stop:
                px = o[t + 1] if t + 1 < len(dates) else c[t]     # t+1 开盘卖出
                ret = px / c[t - 1] - 1.0
                trades.append({"entry_date": dates[entry_i], "entry_px": o[entry_i],
                               "exit_date": dates[min(t + 1, len(dates) - 1)], "exit_px": px,
                               "ret_pct": (px / o[entry_i] - 1) * 100,
                               "hold_days": int(t + 1 - entry_i),
                               "reason": "chandelier" if c[t] < post_high - ATR_MULT * (atr[t] if not np.isnan(atr[t]) else 1e9) else "stop5"})
                in_pos = False
            else:
                ret = c[t] / c[t - 1] - 1.0
        else:
            # t-1 收盘信号 → t 开盘入场
            s = sig_by_date.get(pd.Timestamp(dates[t - 1])) if t >= 1 else None
            if s is not None:
                entry_i, sig_i = t, pos[pd.Timestamp(s.date)]
                in_pos = True
                ret = c[t] / o[t] - 1.0
        nav *= 1 + ret
        eq.append({"date": d, "ret": ret, "nav": nav})
    return pd.DataFrame(trades), pd.DataFrame(eq).set_index("date")


def metrics(eq: pd.DataFrame, trades: pd.DataFrame) -> dict:
    r = eq["ret"]
    yrs = len(r) / 252
    nav = eq["nav"].iloc[-1]
    mdd = (eq["nav"] / eq["nav"].cummax() - 1).min()
    return {
        "总收益": nav - 1, "年化": nav ** (1 / yrs) - 1,
        "Sharpe": r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else np.nan,
        "maxDD": mdd, "笔数": len(trades),
        "胜率": (trades["ret_pct"] > 0).mean() if len(trades) else np.nan,
        "盈亏比": (trades.loc[trades["ret_pct"] > 0, "ret_pct"].mean()
                   / abs(trades.loc[trades["ret_pct"] < 0, "ret_pct"].mean())) if len(trades) else np.nan,
    }


def build_llt_flip_signals(df: pd.DataFrame) -> pd.DataFrame:
    """更新一：LLT 由熊转牛的上穿日（斜率 ≤0 → >0）为信号日。

    纯 LLT 择时（不再用 v3 突破）；信号日收盘 close_sig 为 5% 止损基准。
    暖机：LLT 递推前 ~90 bar 的初值影响未消，弃用（与生成版口径一致偏保守）。
    """
    llt = _llt(df.set_index("date")["close"], LLT_D)
    up = llt.diff() > 0
    flip = (up & ~up.shift(1).fillna(False))
    flip.iloc[:90] = False                    # LLT 暖机
    out = pd.DataFrame({"date": df["date"][flip.values],
                        "degree": 0, "line": np.nan})
    out["close_sig"] = [float(df["close"].iloc[i])
                        for i in np.nonzero(flip.values)[0]]
    return out.reset_index(drop=True)


def main():
    df = load_data()
    ev = build_signals(df)
    print(f"数据 {len(df)} 行 {df['date'].min().date()}~{df['date'].max().date()} | "
          f"v3 突破事件(degree≤5) {len(ev)} 个 | 其中 LLT 牛市 {int(ev['llt_up'].sum())} 个")
    ev_flip = build_llt_flip_signals(df)
    print(f"更新一：LLT 转牛上穿日 {len(ev_flip)} 个")

    runs = [("无闸门版", ev, "raw"),
            ("LLT闸门版", ev[ev["llt_up"]], "llt"),
            ("更新一_LLT转牛开仓", ev_flip, "flip")]
    for name, sub, tag in runs:
        trades, eq = backtest(df, sub.reset_index(drop=True))
        m = metrics(eq, trades)
        print(f"\n[{name}] 总{m['总收益']*100:+.1f}% 年化{m['年化']*100:+.1f}% "
              f"Sharpe{m['Sharpe']:.2f} maxDD{m['maxDD']*100:.0f}% "
              f"{m['笔数']}笔 胜率{m['胜率']*100:.0f}% 盈亏比{m['盈亏比']:.2f}")
        if len(trades):
            print(trades.round(2).to_string(index=False))
        trades.to_csv(HERE / f"trades_{tag}.csv", index=False, encoding="utf-8-sig")
        eq.to_csv(HERE / f"nav_{tag}.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
