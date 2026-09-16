"""量价信息增强（长江研报 §1.4）——22 变量逐步回归筛选 + 半年固定变量/系数 + 查表执行。

铁律：严禁未来数据。
  - 突破事件表：每窗口（与迭代一同算法）转折点 + HSAR + 突破 3% 检测；变量值只用 ≤t 数据；
    45 日收益是事后标签，仅作为回归样本，且只在"标签已实现"时入样本
  - 半年节点 t（用 <t 数据）：
      * 已实现样本 = 事件表[ret45_date < t]（排除 t-45 ~ t-1 未实现突破，防前视）
      * 逐步回归选变量：样本 < 260 放弃本次、沿用上期；z-score 后标准前向+后向（p<0.05 进/出）
      * 变量确定后用过去 500 交易日已实现样本（同上排除未实现尾部）回归 → 固定系数
      * 节点 t 当日仍用上期节点，新节点 t+1 生效
  - 运行时只查表：突破日查 BREAKOUTS、变量查 EVENTS、系数查 NODE_PLAN，充分利用 numpy

供 strategy_002 及各迭代复用；strategy.py 只 import 不内联。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from plateau_algo import (turning_points, resistance_level, members_asof,
                          PARAMS as BREAK_PARAMS, LOOKBACK)

# ── 22 个量价变量（论文 26 - 市值 4；本地无市值，忽略 LnCap/CapVol5d/20d/45d）──
VOL_VARS = ["Turn", "TurnMean5d", "TurnMean20d", "TurnMean45d",
            "TurnVol5d", "TurnVol20d", "TurnVol45d",
            "AmtMean5d", "AmtMean20d", "AmtMean45d",
            "AmtRatio5d", "AmtRatio20d", "AmtRatio45d",
            "Ret5d", "Ret20d", "Ret45d",
            "Vol5d", "Vol20d", "Vol45d",
            "PriceMA5Dev", "PriceMA20Dev", "PriceMA45Dev"]

# ── 配置 ──
RESELECT_INTERVAL = 126        # 半年（约126交易日）一节点
COEF_WINDOW = 500              # 固定系数用过去500交易日
MIN_SAMPLES = 260              # 变量选择最小样本
MIN_COEF_SAMPLES = 30          # 固定系数最小样本
MAX_HOLD = 45                  # 45 日持有期（标签/预测期）


# ═══════════════════════════════════════════════════════════
# 行情归一化（与引擎 normalize_market 一致：保留额外列，剔 NaN/非正 OHLC）
# ═══════════════════════════════════════════════════════════

def normalize_market(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str)
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ["volume", "amount", "turn"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out = out.sort_values(["symbol", "date"]).drop_duplicates(["date", "symbol"], keep="last")
    return out.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# 每窗口转折点（numpy，与 plateau_algo.turning_points 逐行等价，返回全局索引）
# ═══════════════════════════════════════════════════════════

def tp_window_np(close, high, low, ub, lb, a, b, bb_window=20, p_clear=4):
    """窗口 [a,b] 的转折点（绝对索引）。与 DataFrame 版逐窗口等价：
    窗口前 bb_window-1 行布林带为 NaN（rolling 在窗口内不足），等价于从 a+bb_window-1 起跑状态机。"""
    highs, lows = [], []          # (全局索引, 价格)
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


# ═══════════════════════════════════════════════════════════
# 22 变量向量化计算（每股票一次性，突破日取行）
# ═══════════════════════════════════════════════════════════

def _compute_vars_arrays(g: pd.DataFrame) -> dict[str, np.ndarray]:
    """返回 {变量名: 全序列数组}，索引对齐 g 的行。"""
    close = g["close"]
    turn = g["turn"] if "turn" in g.columns else pd.Series(0.0, index=g.index)
    amt = g["amount"] if "amount" in g.columns else pd.Series(0.0, index=g.index)
    ret = close.pct_change()
    out = {"Turn": turn.to_numpy(float)}
    for w in (5, 20, 45):
        amt_mean = amt.rolling(w).mean()
        out[f"TurnMean{w}d"] = turn.rolling(w).mean().to_numpy(float)
        out[f"TurnVol{w}d"] = turn.rolling(w).std().to_numpy(float)
        out[f"AmtMean{w}d"] = amt_mean.to_numpy(float)
        out[f"AmtRatio{w}d"] = (amt / amt_mean.replace(0, np.nan)).to_numpy(float)
        out[f"Ret{w}d"] = close.pct_change(w).to_numpy(float)
        out[f"Vol{w}d"] = ret.rolling(w).std().to_numpy(float)
        out[f"PriceMA{w}Dev"] = (close / close.rolling(w).mean() - 1).to_numpy(float)
    return out


# ═══════════════════════════════════════════════════════════
# 突破事件表（预计算，一次性，缓存 parquet）
# ═══════════════════════════════════════════════════════════

def build_events_df(market: pd.DataFrame) -> pd.DataFrame:
    """检测全部平台突破事件：{date, symbol, 22变量, ret45, ret45_date}。
    检测与迭代一逐窗口一致（转折点+HSAR+突破3%+当日成分过滤）；变量用 ≤t 数据。
    ret45 = close[t+45]/close[t]-1；ret45_date = t+45 交易日（标签实现日，入样本门槛）。"""
    p = BREAK_PARAMS
    rows = []
    for sym, g in market.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        if n <= LOOKBACK + MAX_HOLD:
            continue
        c = g["close"].to_numpy(float)
        h = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        ma = pd.Series(c).rolling(p["bb_window"]).mean().to_numpy()
        sd = pd.Series(c).rolling(p["bb_window"]).std().to_numpy()
        ub = ma + p["bb_k"] * sd
        lb = ma - p["bb_k"] * sd
        varrs = _compute_vars_arrays(g)
        dates = g["date"].to_numpy()
        for b in range(LOOKBACK, n - MAX_HOLD):     # 需 b+45 存在（标签）
            if sym not in members_asof(dates[b]):
                continue
            a = b - LOOKBACK + 1
            hp, _ = tp_window_np(c, h, lo, ub, lb, a, b, p["bb_window"], p["p_clear"])
            res = resistance_level(hp, p)
            if res is None:
                continue
            if not (c[b] > res * (1 + p["break_pct"])):
                continue
            rows.append({
                "date": dates[b], "symbol": sym,
                "ret45": c[b + MAX_HOLD] / c[b] - 1.0,
                "ret45_date": dates[b + MAX_HOLD],
                **{v: varrs[v][b] for v in VOL_VARS},
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# 逐步回归（标准前向+后向，p 值进出，z-score 后比较 p 值）
# ═══════════════════════════════════════════════════════════

def _stepwise_select(Xn: pd.DataFrame, y: np.ndarray, p_enter=0.05, p_exit=0.05):
    """返回选中的变量列表。Xn 已 z-score。"""
    import statsmodels.api as sm
    features = list(Xn.columns)
    selected = []
    changed = True
    while changed:
        changed = False
        best_f, best_p = None, 1.0
        for f in features:
            if f in selected:
                continue
            try:
                model = sm.OLS(y, sm.add_constant(Xn[selected + [f]])).fit()
                p = model.pvalues.get(f)
            except Exception:
                continue
            if p is not None and not np.isnan(p) and p < best_p:
                best_f, best_p = f, p
        if best_f is not None and best_p < p_enter:
            selected.append(best_f)
            changed = True
        while len(selected) > 1:
            try:
                model = sm.OLS(y, sm.add_constant(Xn[selected])).fit()
            except Exception:
                break
            worst = max(selected, key=lambda f: model.pvalues[f])
            p = model.pvalues[worst]
            if not np.isnan(p) and p >= p_exit:
                selected.remove(worst)
                changed = True
            else:
                break
    return selected


# ═══════════════════════════════════════════════════════════
# 半年节点计划（变量 + 固定系数，一次性预计算）
# ═══════════════════════════════════════════════════════════

def build_node_plan(events: pd.DataFrame, dates: list, interval=RESELECT_INTERVAL,
                    coef_window=COEF_WINDOW, min_samples=MIN_SAMPLES,
                    min_coef=MIN_COEF_SAMPLES) -> list[dict]:
    """节点 t：用 <t 已实现样本选变量；变量确定后用过去 coef_window 交易日回归固定系数。
    返回 [{node_date, active, selected_vars, coef, mu, sigma}]（按日期升序）。
    样本不足 → active=False（沿用上期，运行时按无过滤器处理）。"""
    dates = [pd.Timestamp(d) for d in dates]
    nodes = []
    for k in range(0, len(dates), interval):
        t = dates[k]
        realized = events[events["ret45_date"] < t]           # 排除 t-45~t-1 未实现（防前视）
        node = {"node_date": t, "active": False, "selected_vars": None,
                "coef": None, "mu": None, "sigma": None}
        if len(realized) >= min_samples:
            X = realized[VOL_VARS].dropna(how="any")
            y = realized.loc[X.index, "ret45"]
            if len(X) >= min_samples:
                mu = X.mean()
                sigma = X.std().replace(0, 1.0)
                Xn = (X - mu) / sigma
                selected = _stepwise_select(Xn, y)
                if selected:
                    d500 = dates[max(0, k - coef_window)]
                    cs = realized[(realized["date"] >= d500)].dropna(subset=selected + ["ret45"])
                    if len(cs) >= min_coef:
                        mu2 = cs[selected].mean()
                        sigma2 = cs[selected].std().replace(0, 1.0)
                        Xn2 = ((cs[selected] - mu2) / sigma2).values
                        Xd = np.column_stack([np.ones(len(cs)), Xn2])
                        beta, *_ = np.linalg.lstsq(Xd, cs["ret45"].to_numpy(), rcond=None)
                        node.update(active=True, selected_vars=selected,
                                    coef=beta, mu=mu2, sigma=sigma2)
        nodes.append(node)
    return nodes


# ═══════════════════════════════════════════════════════════
# 运行时查表 API
# ═══════════════════════════════════════════════════════════

def active_node_for(nodes: list[dict], d) -> dict | None:
    """最后一个 node_date < d 的节点（节点 t 当日仍用上期，t+1 生效）。"""
    d = pd.Timestamp(d)
    node = None
    for nd in nodes:
        if nd["node_date"] < d:
            node = nd
        else:
            break
    return node


def predict_fit(node: dict | None, vars_d: dict):
    """用节点固定系数拟合 45 日收益（z-score 用系数样本统计量）。返回 None=无过滤器。"""
    if node is None or not node.get("active"):
        return None
    vars_sel = node["selected_vars"]
    beta = np.asarray(node["coef"], dtype=float)
    mu, sigma = node["mu"], node["sigma"]
    x = np.array([vars_d[v] for v in vars_sel], dtype=float)
    if np.isnan(x).any():
        return np.nan
    mu_arr = np.array([mu[v] for v in vars_sel], dtype=float)
    sig_arr = np.array([sigma[v] for v in vars_sel], dtype=float)
    xn = (x - mu_arr) / sig_arr
    return float(beta[0] + beta[1:] @ xn)


# ═══════════════════════════════════════════════════════════
# 缓存（parquet + json，按源数据 mtime 失效）
# ═══════════════════════════════════════════════════════════

def _config_hash() -> dict:
    return {"interval": RESELECT_INTERVAL, "coef_window": COEF_WINDOW,
            "min_samples": MIN_SAMPLES, "min_coef": MIN_COEF_SAMPLES,
            "vol_vars": VOL_VARS}


def load_precomp(market_csv: Path, cache_dir: Path, force_rebuild: bool = False):
    """返回 (events_df, node_plan, breakout_set)。缓存到 cache_dir，源变更时重建。"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ev_path = cache_dir / "vol_enhance_events.parquet"
    nd_path = cache_dir / "vol_enhance_nodes.json"
    meta_path = cache_dir / "vol_enhance_meta.json"
    src = str(Path(market_csv).resolve())
    src_mtime = Path(market_csv).resolve().stat().st_mtime

    def _meta_ok():
        if not meta_path.exists():
            return False
        m = json.loads(meta_path.read_text(encoding="utf-8"))
        return (m.get("src") == src and m.get("src_mtime") == src_mtime
                and m.get("config") == _config_hash())

    if not force_rebuild and ev_path.exists() and nd_path.exists() and _meta_ok():
        events = pd.read_parquet(ev_path)
        with open(nd_path, encoding="utf-8") as f:
            nodes = json.load(f)
        for nd in nodes:  # 反序列化：字符串/列表 → 运行期类型
            nd["node_date"] = pd.Timestamp(nd["node_date"])
            if nd["coef"] is not None:
                nd["coef"] = np.asarray(nd["coef"], dtype=float)
        return events, nodes

    market = normalize_market(pd.read_csv(market_csv))
    events = build_events_df(market)
    dates = sorted(market["date"].unique())
    nodes = build_node_plan(events, dates)
    # 序列化（numpy → list）
    nodes_ser = []
    for nd in nodes:
        nd_ser = dict(nd)
        if nd_ser["coef"] is not None:
            nd_ser["coef"] = [float(x) for x in nd_ser["coef"]]
            nd_ser["mu"] = {k: float(v) for k, v in nd_ser["mu"].items()}
            nd_ser["sigma"] = {k: float(v) for k, v in nd_ser["sigma"].items()}
        nd_ser["node_date"] = str(nd_ser["node_date"])
        nodes_ser.append(nd_ser)
    events.to_parquet(ev_path, index=False)
    (nd_path).write_text(json.dumps(nodes_ser, ensure_ascii=False, indent=1), encoding="utf-8")
    (meta_path).write_text(json.dumps({"src": src, "src_mtime": src_mtime,
                                       "config": _config_hash()}, ensure_ascii=False),
                           encoding="utf-8")
    for nd in nodes_ser:  # 返回运行期类型（与缓存加载路径一致）
        nd["node_date"] = pd.Timestamp(nd["node_date"])
        if nd["coef"] is not None:
            nd["coef"] = np.asarray(nd["coef"], dtype=float)
    return events, nodes_ser


def load_breakouts(events: pd.DataFrame) -> set:
    """{(symbol, date)} 突破日快速查表。"""
    return {(r.symbol, pd.Timestamp(r.date)) for r in events.itertuples()}
