"""迭代四·平台突破 高性能适配版 —— 本地模拟（用与 ssquant 同源的 m888_1h_raw 数据）。

参考 ssquant B_双均线策略_高性能.py 的高性能结构，先本地验证算法逻辑（避免在 ssquant
上反复调试）。要点：
  1. register_indicator 思路：布林带 UB/LB、ATR 用滚动预计算（本地即逐 bar 查数组）
  2. 增量状态机：trend_state/temp_hp/temp_lp/confirmed_points 逐 bar 推进（等价
     ssquant 里存 api 属性，而非全局变量——规避 AI 版全局重置问题）
  3. 开仓：close > 阻力位×1.03 → 次日开盘买入
  4. 平仓：2×ATR 跟踪止损（持仓期最高收盘 − 2×ATR，只升不降）→ 次日开盘卖出

运行：python plateau_break_local_sim.py
"""
import sqlite3

import numpy as np
import pandas as pd

# ── 参数（与 ssquant 版一致）──
BB_WINDOW, BB_K = 20, 1.0
CLEAN_INTERVAL = 4
HSAR_M, HSAR_Q = 10, 2
BREAKOUT_PCT = 0.03
ATR_PERIOD, ATR_MULT = 14, 2.0


# ═══════════════════════════════════════════════════════════
# HSAR 阻力位（基于累计确认高点，同 AI 版）
# ═══════════════════════════════════════════════════════════
def resistance_hsar(highs, M=HSAR_M, Q=HSAR_Q):
    if len(highs) < Q:
        return None
    min_h, max_h = min(highs), max(highs)
    if max_h == min_h:
        return max_h
    width = (max_h - min_h) / M
    cnt = [0] * M
    upper = [0] * M
    for h in highs:
        idx = min(int((h - min_h) / width), M - 1)
        cnt[idx] += 1
        upper[idx] = min_h + (idx + 1) * width
    threshold = min_h + (max_h - min_h) * 2 / 3
    valid = [(cnt[i], upper[i]) for i in range(M) if cnt[i] >= Q and upper[i] >= threshold]
    if not valid:
        return None
    valid.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return valid[0][1]


def clean_points(points, min_interval=CLEAN_INTERVAL):
    if len(points) <= 1:
        return points
    cleaned = [points[0]]
    for p in points[1:]:
        if p[0] - cleaned[-1][0] < min_interval:
            cleaned.pop()
            cleaned.append(p)
        else:
            cleaned.append(p)
    return cleaned


# ═══════════════════════════════════════════════════════════
# 主模拟（增量状态机 + 2×ATR 跟踪止损）
# ═══════════════════════════════════════════════════════════
def run_sim(df):
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    dt = df["datetime"].to_numpy()

    # 预计算布林带 / ATR（register_indicator 等价）
    c_series = pd.Series(close)
    ma = c_series.rolling(BB_WINDOW).mean()
    sd = c_series.rolling(BB_WINDOW).std()
    ub = (ma + BB_K * sd).to_numpy()
    lb = (ma - BB_K * sd).to_numpy()
    pc = c_series.shift(1)
    tr = pd.concat([pd.Series(high) - pd.Series(low),
                    (pd.Series(high) - pc).abs(),
                    (pd.Series(low) - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean().to_numpy()

    # 增量状态机
    trend = "NONE"
    tmp_hp, tmp_hp_i = -1.0, -1
    tmp_lp, tmp_lp_i = -1.0, -1
    confirmed = []          # [(idx, price, 'H'/'L')]
    resistance = 0.0

    pos = 0                 # 0 或 1
    entry_i, entry_px = -1, 0.0
    highest_close, stop_px = 0.0, 0.0
    trades = []
    n = len(df)

    for i in range(n):
        cu, cl = ub[i], lb[i]
        if np.isnan(cu) or np.isnan(cl):
            continue
        hi, lo, cl0 = high[i], low[i], close[i]

        # ── 增量转折点状态机（同 AI 版）──
        if trend == "NONE":
            if hi > cu:
                trend = "UP"; tmp_hp, tmp_hp_i = hi, i
            elif lo < cl:
                trend = "DOWN"; tmp_lp, tmp_lp_i = lo, i
            # 首根只初始化，不确认点
        elif trend == "UP":
            if hi > tmp_hp:
                tmp_hp, tmp_hp_i = hi, i
            elif lo < cl:
                confirmed.append((tmp_hp_i, tmp_hp, "H"))
                trend = "DOWN"; tmp_lp, tmp_lp_i = lo, i
                confirmed = clean_points(confirmed)
        elif trend == "DOWN":
            if lo < tmp_lp:
                tmp_lp, tmp_lp_i = lo, i
            elif hi > cu:
                confirmed.append((tmp_lp_i, tmp_lp, "L"))
                trend = "UP"; tmp_hp, tmp_hp_i = hi, i
                confirmed = clean_points(confirmed)

        # ── HSAR 阻力位（有新高点确认时重算）──
        if confirmed:
            highs = [p[1] for p in confirmed if p[2] == "H"]
            r = resistance_hsar(highs)
            if r is not None:
                resistance = r

        # ── 持仓：2×ATR 跟踪止损（只升不降）→ 次日开盘平仓 ──
        if pos == 1:
            highest_close = max(highest_close, cl0)
            new_stop = highest_close - ATR_MULT * (atr[i] if not np.isnan(atr[i]) else 0)
            if new_stop > stop_px:
                stop_px = new_stop
            if cl0 < stop_px:
                if i + 1 < n:
                    exit_px = open_[i + 1]
                else:
                    exit_px = cl0
                ret = exit_px / entry_px - 1
                trades.append((dt[i], dt[i + 1] if i + 1 < n else dt[i],
                               round(entry_px, 1), round(exit_px, 1), round(ret * 100, 2)))
                pos = 0
                continue

        # ── 空仓：突破阻力位 3% → 次日开盘买入 ──
        if pos == 0 and resistance > 0 and cl0 > resistance * (1 + BREAKOUT_PCT):
            entry_px = open_[i + 1] if i + 1 < n else cl0
            entry_i = i
            pos = 1
            highest_close = cl0
            stop_px = cl0 - ATR_MULT * (atr[i] if not np.isnan(atr[i]) else 0)

    return trades


if __name__ == "__main__":
    con = sqlite3.connect("data_cache/backtest_data.db")
    df = pd.read_sql("SELECT * FROM m888_1h_raw ORDER BY datetime", con)
    con.close()
    print(f"数据: {len(df)} 根 | {df['datetime'].min()} ~ {df['datetime'].max()}")

    trades = run_sim(df)
    print(f"\n交易: {len(trades)} 笔")
    if trades:
        tr = pd.DataFrame(trades, columns=["entry_dt", "exit_dt", "entry_px", "exit_px", "ret_pct"])
        wins = (tr["ret_pct"] > 0).sum()
        print(f"胜率: {wins}/{len(tr)} = {wins/len(tr)*100:.1f}%")
        print(f"平均收益: {tr['ret_pct'].mean():+.2f}% | 中位 {tr['ret_pct'].median():+.2f}%")
        print(f"盈亏比: {tr[tr.ret_pct>0]['ret_pct'].mean()/abs(tr[tr.ret_pct<0]['ret_pct'].mean()):.2f}" if (tr.ret_pct>0).any() and (tr.ret_pct<0).any() else "")
        tr["year"] = pd.to_datetime(tr["entry_dt"]).dt.year
        print("\n按年:")
        print(tr.groupby("year").agg(n=("ret_pct","count"), 平均=("ret_pct","mean"), 胜率=("ret_pct", lambda s:(s>0).mean()*100)).to_string())
        print("\n前 12 笔:")
        print(tr.head(12).to_string(index=False))
