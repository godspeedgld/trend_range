"""迭代三策略 → BigQuant aistudio 自包含版（bigtrader.run，单文件）。

全部自包含，不依赖本地文件/上传：
  1. initialize：云端 SQL（dai.query）拉 沪深300历史成分 → cn_stock_bar1d(行情) +
     cn_stock_valuation(市值) 合并成宽面板 → 本地预计算逻辑（突破事件表 + 半年节点
     逐步回归固定系数 + 实际离场标签）内联在此文件，一次性算出 → 存 context
  2. before_trading_start：查当日突破事件 → 当前节点固定系数拟合实际离场收益
     → score>0 有效突破 → 取前 N 为目标持仓
  3. handle_data：离场（回撤10%/45自然日，peak 由 context 跟踪）+ 调仓 1/n

与本地引擎差异（平台执行模型所致，信号一致）：
  - 本地「t收盘→t+1开盘 + 开仓池5日 + 突破最近优先」；aistudio 用 handle_data +
    order_price_field=open、按 score 排序取前 N
  - 无有效节点期（样本不足）等同迭代一：全部突破直接进目标池

cloud 表结构见 skill-bigquant-sdk/references/data_tables.md：
  cn_stock_bar1d（后复权日线，含 turn/amount）/ cn_stock_valuation / cn_stock_index_component
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from bigquant import bigtrader, dai

# ── 参数（与本地迭代三一致）──
INDEX_CODE = "000300.SH"
START_PRECOMP = "2015-01-01"       # 预计算数据起点（含 252 日暖期）
BACKTEST_START = "2015-01-01"
BACKTEST_END = "2026-08-21"
MAX_POSITIONS = 10
TRAILING_DD = 0.10
MAX_HOLD_DAYS = 45
LOOKBACK = 252
BB = {"bb_window": 20, "bb_k": 1.0, "p_clear": 4, "m_bins": 10,
      "q_density": 2, "break_pct": 0.03}
VOL_VARS = ["Turn", "TurnMean5d", "TurnMean20d", "TurnMean45d",
            "TurnVol5d", "TurnVol20d", "TurnVol45d",
            "AmtMean5d", "AmtMean20d", "AmtMean45d",
            "AmtRatio5d", "AmtRatio20d", "AmtRatio45d",
            "Ret5d", "Ret20d", "Ret45d",
            "Vol5d", "Vol20d", "Vol45d",
            "LnCap", "CapVol5d", "CapVol20d", "CapVol45d",
            "PriceMA5Dev", "PriceMA20Dev", "PriceMA45Dev"]


# ═══════════════════════════════════════════════════════════
# 云端取数（SQL）
# ═══════════════════════════════════════════════════════════
def _query(sql, date_range):
    return dai.query(sql, filters={"date": date_range}).df()


def _normalize_panel(df):
    """剔停牌/无效 OHLC 行（与本地 normalize_market 一致，保额外列）。"""
    out = df.copy()
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    return out.sort_values(["instrument", "date"]).reset_index(drop=True)


def _load_cloud_panel(end_date=BACKTEST_END):
    """拉 沪深300 历史成分 行情+市值，合并为宽面板（对齐本地 _market_hs300_panel）。"""
    date_range = (START_PRECOMP, end_date)
    # 1) 历史成分（当日成分在事件构建时用成员表过滤）
    mc = dai.query(
        f"SELECT DISTINCT member_code FROM cn_stock_index_component "
        f"WHERE instrument='{INDEX_CODE}'",
        filters={"date": date_range}).df()
    instruments = mc["member_code"].astype(str).tolist()
    in_list = ",".join(f"'{s}'" for s in instruments)
    # 2) 行情（后复权，含 turn/amount）
    bar = _query(
        f"SELECT date, instrument, open, high, low, close, volume, amount, turn "
        f"FROM cn_stock_bar1d WHERE instrument IN ({in_list})", date_range)
    bar["date"] = pd.to_datetime(bar["date"])
    # 3) 估值（市值 → LnCap/CapVol）
    val = _query(
        f"SELECT date, instrument, total_market_cap FROM cn_stock_valuation "
        f"WHERE instrument IN ({in_list})", date_range)
    val["date"] = pd.to_datetime(val["date"])
    # 4) 成员（按日，供当日成分过滤）
    mem = dai.query(
        f"SELECT date, member_code FROM cn_stock_index_component "
        f"WHERE instrument='{INDEX_CODE}'",
        filters={"date": date_range}).df()
    mem["date"] = pd.to_datetime(mem["date"])
    # 宽面板（bar 锚 + 估值 LEFT JOIN）
    panel = bar.merge(val, on=["date", "instrument"], how="left")
    panel = panel.sort_values(["instrument", "date"]).reset_index(drop=True)
    return panel, mem


# ═══════════════════════════════════════════════════════════
# 预计算：突破事件 + 26变量 + 实际离场标签
# ═══════════════════════════════════════════════════════════
def _tp_window_np(close, high, low, ub, lb, a, b, bb_window, p_clear):
    highs, lows = [], []
    direction, hp_i, hp_p, lp_i, lp_p = 0, -1, -1.0, -1, -1.0
    start = a + bb_window - 1
    for i in range(start, b + 1):
        hi, lo = high[i], low[i]
        u, l = ub[i], lb[i]
        if direction == 0:
            if hi > u:
                direction, hp_i, hp_p = 1, i, hi
            elif lo < l:
                direction, lp_i, lp_p = -1, i, lo
        elif direction == 1:
            if hi > hp_p:
                hp_i, hp_p = i, hi
            if lo < l:
                if hp_i >= 0:
                    highs.append((hp_i, hp_p))
                direction, lp_i, lp_p = -1, i, lo
        else:
            if lo < lp_p:
                lp_i, lp_p = i, lo
            if hi > u:
                if lp_i >= 0:
                    lows.append((lp_i, lp_p))
                direction, hp_i, hp_p = 1, i, hi
    pts = sorted([(i, pr, 1) for i, pr in highs] + [(i, pr, 0) for i, pr in lows])
    keep = []
    for k, (idx, pr, kind) in enumerate(pts):
        if 0 < k and idx - pts[k - 1][0] < p_clear:
            continue
        if k < len(pts) - 1 and pts[k + 1][0] - idx < p_clear:
            continue
        keep.append((idx, pr, kind))
    return ([(i, pr) for i, pr, k in keep if k == 1],
            [(i, pr) for i, pr, k in keep if k == 0])


def _resistance_level(highs, m_bins, q_density):
    if len(highs) < q_density:
        return None
    prices = np.array([pr for _, pr in highs])
    lo, hi = prices.min(), prices.max()
    if hi - lo < 1e-12:
        return None
    width = (hi - lo) / m_bins
    counts = np.zeros(m_bins)
    for pr in prices:
        counts[min(int((pr - lo) / width), m_bins - 1)] += 1
    cand = np.where(counts >= q_density)[0]
    top = np.where(lo + np.arange(m_bins) * width >= lo + 2 * (hi - lo) / 3)[0]
    valid = [b for b in cand if b in set(top)]
    if not valid:
        return None
    best = max(valid, key=lambda b: (counts[b], b))
    return lo + (best + 1) * width


def _vars_arrays(g):
    close = g["close"]
    turn = g["turn"] if "turn" in g.columns else pd.Series(0.0, index=g.index)
    amt = g["amount"] if "amount" in g.columns else pd.Series(0.0, index=g.index)
    cap = g["total_market_cap"] if "total_market_cap" in g.columns else pd.Series(np.nan, index=g.index)
    ret = close.pct_change()
    out = {"Turn": turn.to_numpy(float),
           "LnCap": np.log(cap.replace(0, np.nan)).to_numpy(float)}
    for w in (5, 20, 45):
        amt_mean = amt.rolling(w).mean()
        out[f"TurnMean{w}d"] = turn.rolling(w).mean().to_numpy(float)
        out[f"TurnVol{w}d"] = turn.rolling(w).std().to_numpy(float)
        out[f"AmtMean{w}d"] = amt_mean.to_numpy(float)
        out[f"AmtRatio{w}d"] = (amt / amt_mean.replace(0, np.nan)).to_numpy(float)
        out[f"Ret{w}d"] = close.pct_change(w).to_numpy(float)
        out[f"Vol{w}d"] = ret.rolling(w).std().to_numpy(float)
        out[f"CapVol{w}d"] = cap.rolling(w).std().to_numpy(float)
        out[f"PriceMA{w}Dev"] = (close / close.rolling(w).mean() - 1).to_numpy(float)
    return out


def _exit_at(open_px, dates, j, entry_px):
    if j + 1 >= len(dates):
        return np.nan, pd.NaT
    exit_px = open_px[j + 1]
    if np.isfinite(exit_px) and exit_px > 0:
        return exit_px / entry_px - 1.0, dates[j + 1]
    return np.nan, pd.NaT


def _exit_triggered(peak, close, entry_date, cur_date, trail_dd=TRAILING_DD, max_hold=MAX_HOLD_DAYS):
    if peak and peak > 0 and close / peak - 1.0 < -trail_dd:
        return True
    return (pd.Timestamp(cur_date) - pd.Timestamp(entry_date)).days > max_hold


def _sim_exit_return(open_px, close_px, dates, b):
    entry = b + 1
    if entry >= len(dates):
        return np.nan, pd.NaT
    entry_px = open_px[entry]
    if not np.isfinite(entry_px) or entry_px <= 0:
        return np.nan, pd.NaT
    entry_date = dates[entry]
    peak = entry_px
    for j in range(entry, len(dates)):
        c = close_px[j]
        if np.isfinite(c) and np.isfinite(peak) and _exit_triggered(peak, c, entry_date, dates[j]):
            return _exit_at(open_px, dates, j, entry_px)
        if np.isfinite(c):
            peak = max(peak, c)
    return np.nan, pd.NaT


def _build_events(panel, mem):
    """全部平台突破事件：{date, symbol, 26变量, ret_exit, exit_date}。"""
    # 成员表 → 当日成分 asof
    mem_map = {d: set(g["member_code"]) for d, g in mem.groupby("date")}
    mem_dates = sorted(mem_map)

    def members_asof(d):
        d = pd.Timestamp(d)
        if d in mem_map:
            return mem_map[d]
        earlier = [x for x in mem_dates if x <= d]
        return mem_map[earlier[-1]] if earlier else set()

    rows = []
    for sym, g in panel.groupby("instrument", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        if n <= LOOKBACK:
            continue
        c = g["close"].to_numpy(float)
        h = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        op = g["open"].to_numpy(float)
        ma = pd.Series(c).rolling(BB["bb_window"]).mean().to_numpy()
        sd = pd.Series(c).rolling(BB["bb_window"]).std().to_numpy()
        ub = ma + BB["bb_k"] * sd
        lb = ma - BB["bb_k"] * sd
        varrs = _vars_arrays(g)
        dates = g["date"].to_numpy()
        for b in range(LOOKBACK, n):
            if sym not in members_asof(dates[b]):
                continue
            a = b - LOOKBACK + 1
            hp, _ = _tp_window_np(c, h, lo, ub, lb, a, b, BB["bb_window"], BB["p_clear"])
            res = _resistance_level(hp, BB["m_bins"], BB["q_density"])
            if res is None or not (c[b] > res * (1 + BB["break_pct"])):
                continue
            ret_exit, exit_date = _sim_exit_return(op, c, dates, b)
            rows.append({"date": dates[b], "instrument": sym,
                         "ret_exit": ret_exit, "exit_date": exit_date,
                         **{v: varrs[v][b] for v in VOL_VARS}})
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# 逐步回归（numpy OLS + p 值，无 statsmodels 依赖）
# ═══════════════════════════════════════════════════════════
def _ols_pvalues(X, y):
    """X:(n,k) 不含常数；返回 (beta, pvalues)（含常数项 beta[0]）。"""
    Xd = np.column_stack([np.ones(len(y)), X])
    n, k = Xd.shape
    if n <= k:
        return np.full(k, np.nan), np.full(k, np.nan)
    beta, *_ = np.linalg.lstsq(Xd, y, rcond=None)
    resid = y - Xd @ beta
    dof = n - k
    mse = float(resid @ resid) / dof
    try:
        cov = mse * np.linalg.inv(Xd.T @ Xd)
    except np.linalg.LinAlgError:
        return beta, np.full(k, np.nan)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = beta / se
        p = 2 * stats.t.sf(np.abs(t), dof)
    return beta, p


def _stepwise_select(Xn, y, p_enter=0.05, p_exit=0.05):
    features = list(Xn.columns)
    selected = []
    changed = True
    while changed:
        changed = False
        best_f, best_p = None, 1.0
        for f in features:
            if f in selected:
                continue
            _, p = _ols_pvalues(Xn[selected + [f]].to_numpy(), y)
            pv = p[-1]
            if pv == pv and pv < best_p:
                best_f, best_p = f, pv
        if best_f is not None and best_p < p_enter:
            selected.append(best_f)
            changed = True
        while len(selected) > 1:
            _, p = _ols_pvalues(Xn[selected].to_numpy(), y)
            worst = max(range(len(selected)), key=lambda i: p[1 + i])
            if p[1 + worst] == p[1 + worst] and p[1 + worst] >= p_exit:
                selected.pop(worst)
                changed = True
            else:
                break
    return selected


# ═══════════════════════════════════════════════════════════
# 半年节点计划（固定变量 + 固定系数）
# ═══════════════════════════════════════════════════════════
def _build_nodes(events, dates, interval=126, coef_window=500,
                 min_samples=260, min_coef=30):
    nodes = []
    for k in range(0, len(dates), interval):
        t = dates[k]
        realized = events[events["exit_date"] < t]           # 已离场（防前视）
        node = {"node_date": t, "active": False, "selected_vars": None,
                "coef": None, "mu": None, "sigma": None}
        if len(realized) >= min_samples:
            X = realized[VOL_VARS].dropna(how="any")
            y = realized.loc[X.index, "ret_exit"]
            if len(X) >= min_samples:
                mu = X.mean()
                sigma = X.std().replace(0, 1.0)
                Xn = (X - mu) / sigma
                selected = _stepwise_select(Xn, y)
                if selected:
                    d500 = dates[max(0, k - coef_window)]
                    cs = realized[realized["date"] >= d500].dropna(subset=selected + ["ret_exit"])
                    if len(cs) >= min_coef:
                        mu2 = cs[selected].mean()
                        sigma2 = cs[selected].std().replace(0, 1.0)
                        Xn2 = ((cs[selected] - mu2) / sigma2).to_numpy()
                        Xd = np.column_stack([np.ones(len(cs)), Xn2])
                        beta, *_ = np.linalg.lstsq(Xd, cs["ret_exit"].to_numpy(), rcond=None)
                        node.update(active=True, selected_vars=selected,
                                    coef=beta, mu=mu2, sigma=sigma2)
        nodes.append(node)
    return nodes


def _active_node(nodes, d):
    d = pd.Timestamp(d)
    node = None
    for nd in nodes:
        if nd["node_date"] < d:
            node = nd
        else:
            break
    return node


def _score_one(node, row):
    vs = node["selected_vars"]
    x = np.array([float(row[v]) for v in vs], dtype=float)
    if np.isnan(x).any():
        return np.nan
    mu = np.array([node["mu"][v] for v in vs], dtype=float)
    sig = np.array([node["sigma"][v] for v in vs], dtype=float)
    coef = node["coef"]
    return float(coef[0] + coef[1:] @ ((x - mu) / sig))


# ═══════════════════════════════════════════════════════════
# 策略
# ═══════════════════════════════════════════════════════════
def initialize(context: bigtrader.IContext):
    from bigtrader.finance.commission import PerOrder
    context.set_commission(PerOrder(buy_cost=0.0003, sell_cost=0.0013, min_cost=5))

    print("[initialize] 云端拉取 沪深300 历史成分行情+市值...")
    panel, mem = _load_cloud_panel(BACKTEST_END)
    panel = _normalize_panel(panel)          # 剔停牌/无效 OHLC（对齐本地 normalize_market）
    print(f"[initialize] 面板 {len(panel)} 行 / {panel['instrument'].nunique()} 只 "
          f"{pd.Timestamp(panel['date'].min()).date()}~{pd.Timestamp(panel['date'].max()).date()}")

    print("[initialize] 预计算突破事件表...")
    events = _build_events(panel, mem)
    print(f"[initialize] 事件 {len(events)} 个 "
          f"{pd.Timestamp(events['date'].min()).date()}~{pd.Timestamp(events['date'].max()).date()}")

    dates = sorted(panel["date"].unique())
    print("[initialize] 半年节点计划（逐步回归）...")
    context.nodes = _build_nodes(events, dates)
    context.events_by_date = {d: g for d, g in events.groupby("date")}
    context.pos_meta = {}
    context.pred = []
    context.max_positions = 10
    context.trailing_dd = 0.10
    context.max_hold_days = 45
    context.position_value = 150000.0      # 固定 15 万/仓（不复利）
    print(f"[initialize] 完成。节点 {len(context.nodes)}，"
          f"有效 {sum(1 for n in context.nodes if n['active'])}")


def before_trading(context, data):
    date = data.current_dt.strftime("%Y-%m-%d")
    context.pred = []
    ev = context.events_by_date.get(pd.Timestamp(date))
    if ev is None or len(ev) == 0:
        return
    node = _active_node(context.nodes, date)
    if node is None or not node["active"]:
        ev = ev.copy()
        ev["score"] = 1.0                       # 无过滤器期 → 等同迭代一
    else:
        ev = ev.copy()
        ev["score"] = ev.apply(lambda r: _score_one(node, r), axis=1)
        ev = ev[ev["score"] > 0]
    ev = ev.sort_values("score", ascending=False).head(MAX_POSITIONS)
    context.pred = ev[["instrument", "score"]].to_dict("records")


def _current_price(context, data, sym):
    """取当前价：优先持仓 last_price/market_value，回退 bar 数据。"""
    try:
        pos = context.get_account_positions().get(sym)
        if pos is not None:
            lp = pos.get("last_price") if isinstance(pos, dict) else getattr(pos, "last_price", None)
            if lp:
                return float(lp)
            mv = pos.get("market_value") if isinstance(pos, dict) else getattr(pos, "market_value", None)
            qty = pos.get("current_qty") if isinstance(pos, dict) else getattr(pos, "current_qty", None)
            if mv and qty:
                return float(mv) / float(qty)
    except Exception:
        pass
    try:
        return float(data[sym].close)
    except Exception:
        try:
            return float(data.close(sym))
        except Exception:
            return None


def handle_data(context: bigtrader.IContext, data: bigtrader.IBarData):
    date = pd.Timestamp(data.current_dt.strftime("%Y-%m-%d"))
    targets = {r["instrument"] for r in context.pred}

    # ① 离场（**45天独立判断——不依赖取价，避免价格API失败导致持仓永不轮动**）
    for sym in list(context.get_account_positions().keys()):
        meta = context.pos_meta.get(sym)
        if meta is None:
            meta = context.pos_meta[sym] = {"entry_date": date, "peak": None}
        if (date - pd.Timestamp(meta["entry_date"])).days > MAX_HOLD_DAYS:
            context.order_target_percent(sym, 0)
            context.pos_meta.pop(sym, None)
            continue
        close = _current_price(context, data, sym)
        if close is None or np.isnan(close):
            continue
        peak = meta["peak"]
        if peak and peak > 0 and close / peak - 1.0 < -TRAILING_DD:
            context.order_target_percent(sym, 0)
            context.pos_meta.pop(sym, None)
            continue
        meta["peak"] = max(peak or close, close)

    # ② 买入：今日有效突破，**每仓固定 15 万（不复利）**，仓位未满时按 score 优先补入
    pv = context.portfolio.portfolio_value
    pct = (context.position_value / pv) if pv and pv > 0 else 0.0
    held = set(context.get_account_positions().keys())
    open_slots = context.max_positions - len(held)
    for sym in targets - held:
        if open_slots <= 0:
            break
        context.order_target_percent(sym, pct)
        context.pos_meta[sym] = {"entry_date": date, "peak": None}
        open_slots -= 1
    context.pred = []


# ═══════════════════════════════════════════════════════════
# 回测入口
# ═══════════════════════════════════════════════════════════
performance = bigtrader.run(
    market=bigtrader.Market.CN_STOCK,
    frequency=bigtrader.Frequency.DAILY,
    start_date=BACKTEST_START,
    end_date=BACKTEST_END,
    capital_base=2_000_000,
    initialize=initialize,
    before_trading_start=before_trading,
    handle_data=handle_data,
    order_price_field_buy="open",
    order_price_field_sell="open",
)

performance.render()
