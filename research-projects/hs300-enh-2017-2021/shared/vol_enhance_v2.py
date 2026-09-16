"""量价信息增强 v2（长江研报 §1.4）——**26 变量**（含市值 4 个）逐步回归 + 半年固定变量/系数。

迭代三版：在 v1（22 变量，45日持有标签）基础上两处**修正**（skill 规范已同步）：
  ① **事件表覆盖到数据末**：尾部 45 日无完整标签的突破也入表（ret_exit=NaN, exit_date=NaT），
     供入场检测（无需标签）；回归样本靠 exit_date < t 过滤（NaN 自动排除），无前视。
     —— 修复"数据延长后最后 45 交易日无交易"缺陷
  ② **标签 = 策略实际离场收益**：模拟策略离场规则（滚动回撤 10% 或 45 自然日，先到者，次日开盘成交），
     而非纯 45 日持有收益——让回归预测目标贴合真实交易（多数交易未满 45 天即因回撤离场）。
     —— 修复"预测45日收益 vs 实际提前离场"口径差

其余（节点半年固定变量/系数、查表执行、市值变量）与先前版本一致。
铁律：严禁未来数据。样本只取 exit_date < t（排除未离场/未实现）；节点 t 当日用上期、t+1 生效。

供 strategy_003 及各迭代复用；strategy.py 只 import 不内联。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from plateau_algo import (turning_points, resistance_level, members_asof,
                          PARAMS as BREAK_PARAMS, LOOKBACK)
from exit_rules import exit_triggered          # 离场规则单一事实源（与策略 exit_check 共用）

# ── 26 个变量（论文完整集：换手率7 + 成交额6 + 动量3 + 波动率3 + 市值4 + 均线偏离3）──
VOL_VARS = ["Turn", "TurnMean5d", "TurnMean20d", "TurnMean45d",
            "TurnVol5d", "TurnVol20d", "TurnVol45d",
            "AmtMean5d", "AmtMean20d", "AmtMean45d",
            "AmtRatio5d", "AmtRatio20d", "AmtRatio45d",
            "Ret5d", "Ret20d", "Ret45d",
            "Vol5d", "Vol20d", "Vol45d",
            "LnCap", "CapVol5d", "CapVol20d", "CapVol45d",
            "PriceMA5Dev", "PriceMA20Dev", "PriceMA45Dev"]

# ── 配置（与先前一致；离场标签参数）──
RESELECT_INTERVAL = 126        # 半年（约126交易日）一节点
COEF_WINDOW = 500              # 固定系数用过去500交易日
MIN_SAMPLES = 260              # 变量选择最小样本
MIN_COEF_SAMPLES = 30          # 固定系数最小样本
MAX_HOLD = 45                  # 最大持有 45 自然日（离场）
TRAILING_DD = 0.10             # 滚动回撤 10%（离场）
COST_BPS = 0.0                 # 标签口径：毛收益（不含成本，与论文一致）


# ═══════════════════════════════════════════════════════════
# 行情归一化（保留 OHLC + turn/amount/total_market_cap 额外列，剔 NaN/非正 OHLC）
# ═══════════════════════════════════════════════════════════

def normalize_market(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["symbol"] = out["symbol"].astype(str)
    for c in ["open", "high", "low", "close"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ["volume", "amount", "turn", "total_market_cap"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out = out.sort_values(["symbol", "date"]).drop_duplicates(["date", "symbol"], keep="last")
    return out.reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# 每窗口转折点（numpy，与 plateau_algo.turning_points 逐行等价）
# ═══════════════════════════════════════════════════════════

def tp_window_np(close, high, low, ub, lb, a, b, bb_window=20, p_clear=4):
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
# 26 变量向量化计算（含市值类）
# ═══════════════════════════════════════════════════════════

def _compute_vars_arrays(g: pd.DataFrame) -> dict[str, np.ndarray]:
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


# ═══════════════════════════════════════════════════════════
# 模拟策略离场（标签用）——与回测引擎时序一致
# ═══════════════════════════════════════════════════════════

def _exit_at(open_px, dates, j, entry_px):
    """离场：j 收盘决策 → j+1 开盘成交；超出数据末 → 未实现 (NaN, NaT)。"""
    if j + 1 >= len(dates):
        return np.nan, pd.NaT
    exit_px = open_px[j + 1]
    if np.isfinite(exit_px) and exit_px > 0:
        return exit_px / entry_px - 1.0, dates[j + 1]
    return np.nan, pd.NaT


def _sim_exit_return(open_px, close_px, dates, b, max_hold=MAX_HOLD, trail_dd=TRAILING_DD):
    """突破日 b（收盘确认）→ 次日开盘入场 → 滚动回撤 10% 或 45 自然日先到者离场。

    时序同引擎：t 收盘决策 → t+1 开盘成交；回撤检查用截至 j-1 的 peak（滞后一日）。
    返回 (ret_exit, exit_date)；数据内未离场/无法入场 → (NaN, NaT)。
    """
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
        # 离场判定用共享规则 exit_triggered（回撤检查用截至 j-1 的 peak，滞后一日，同引擎时序）
        if np.isfinite(c) and np.isfinite(peak) and \
                exit_triggered(peak, c, entry_date, dates[j], trail_dd=trail_dd, max_hold=max_hold):
            return _exit_at(open_px, dates, j, entry_px)
        if np.isfinite(c):
            peak = max(peak, c)
    return np.nan, pd.NaT                        # 数据内未离场 → 未实现


# ═══════════════════════════════════════════════════════════
# 突破事件表（预计算，一次性，缓存 parquet）
# ═══════════════════════════════════════════════════════════

def build_events_df(market: pd.DataFrame) -> pd.DataFrame:
    """检测全部平台突破事件：{date, symbol, 26变量, ret_exit, exit_date}。

    覆盖到数据末（range(LOOKBACK, n)）：尾部无完整离场标签的突破也入表，
    ret_exit/exit_date 记 NaN/NaT——供入场检测（无需标签）；样本按 exit_date<t 过滤，无前视。
    标签 = 模拟策略实际离场收益（回撤10%/45自然日先到者）。"""
    p = BREAK_PARAMS
    rows = []
    for sym, g in market.groupby("symbol", sort=False):
        g = g.sort_values("date").reset_index(drop=True)
        n = len(g)
        if n <= LOOKBACK:
            continue
        c = g["close"].to_numpy(float)
        h = g["high"].to_numpy(float)
        lo = g["low"].to_numpy(float)
        op = g["open"].to_numpy(float)
        ma = pd.Series(c).rolling(p["bb_window"]).mean().to_numpy()
        sd = pd.Series(c).rolling(p["bb_window"]).std().to_numpy()
        ub = ma + p["bb_k"] * sd
        lb = ma - p["bb_k"] * sd
        varrs = _compute_vars_arrays(g)
        dates = g["date"].to_numpy()
        for b in range(LOOKBACK, n):
            if sym not in members_asof(dates[b]):
                continue
            a = b - LOOKBACK + 1
            hp, _ = tp_window_np(c, h, lo, ub, lb, a, b, p["bb_window"], p["p_clear"])
            res = resistance_level(hp, p)
            if res is None:
                continue
            if not (c[b] > res * (1 + p["break_pct"])):
                continue
            ret_exit, exit_date = _sim_exit_return(op, c, dates, b)
            rows.append({
                "date": dates[b], "symbol": sym,
                "ret_exit": ret_exit, "exit_date": exit_date,
                **{v: varrs[v][b] for v in VOL_VARS},
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════
# 逐步回归（标准前向+后向，p 值进出，z-score 后比较 p 值）
# ═══════════════════════════════════════════════════════════

def _stepwise_select(Xn: pd.DataFrame, y: np.ndarray, p_enter=0.05, p_exit=0.05):
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
                model = sm_ols(y, Xn, selected + [f])
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
                model = sm_ols(y, Xn, selected)
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


def sm_ols(y, Xn, cols):
    import statsmodels.api as sm
    return sm.OLS(y, sm.add_constant(Xn[cols])).fit()


# ═══════════════════════════════════════════════════════════
# 半年节点计划（变量 + 固定系数）
# ═══════════════════════════════════════════════════════════

def build_node_plan(events: pd.DataFrame, dates: list, interval=RESELECT_INTERVAL,
                    coef_window=COEF_WINDOW, min_samples=MIN_SAMPLES,
                    min_coef=MIN_COEF_SAMPLES, vol_vars=None) -> list[dict]:
    """节点 t：用 <t 已实现（已离场，exit_date<t）样本选变量；过去 coef_window 交易日回归固定系数。
    返回 [{node_date, active, selected_vars, coef, mu, sigma}]。样本不足 → active=False。
    vol_vars：候选变量集（默认 26 全量；诊断时可传子集如 22 变量对照）。"""
    vol_vars = vol_vars or VOL_VARS
    dates = [pd.Timestamp(d) for d in dates]
    nodes = []
    for k in range(0, len(dates), interval):
        t = dates[k]
        realized = events[events["exit_date"] < t]           # 排除未离场（防前视）
        node = {"node_date": t, "active": False, "selected_vars": None,
                "coef": None, "mu": None, "sigma": None}
        if len(realized) >= min_samples:
            X = realized[vol_vars].dropna(how="any")
            y = realized.loc[X.index, "ret_exit"]
            if len(X) >= min_samples:
                mu = X.mean()
                sigma = X.std().replace(0, 1.0)
                Xn = (X - mu) / sigma
                selected = _stepwise_select(Xn, y)
                if selected:
                    d500 = dates[max(0, k - coef_window)]
                    cs = realized[(realized["date"] >= d500)].dropna(subset=selected + ["ret_exit"])
                    if len(cs) >= min_coef:
                        mu2 = cs[selected].mean()
                        sigma2 = cs[selected].std().replace(0, 1.0)
                        Xn2 = ((cs[selected] - mu2) / sigma2).values
                        Xd = np.column_stack([np.ones(len(cs)), Xn2])
                        beta, *_ = np.linalg.lstsq(Xd, cs["ret_exit"].to_numpy(), rcond=None)
                        node.update(active=True, selected_vars=selected,
                                    coef=beta, mu=mu2, sigma=sigma2)
        nodes.append(node)
    return nodes


# ═══════════════════════════════════════════════════════════
# 运行时查表 API
# ═══════════════════════════════════════════════════════════

def active_node_for(nodes: list[dict], d) -> dict | None:
    d = pd.Timestamp(d)
    node = None
    for nd in nodes:
        if nd["node_date"] < d:
            node = nd
        else:
            break
    return node


def predict_fit(node: dict | None, vars_d: dict):
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
# 缓存（v2 独立文件；config 含标签口径，改口径强制重建）
# ═══════════════════════════════════════════════════════════

def _config_hash() -> dict:
    return {"interval": RESELECT_INTERVAL, "coef_window": COEF_WINDOW,
            "min_samples": MIN_SAMPLES, "min_coef": MIN_COEF_SAMPLES,
            "vol_vars": VOL_VARS,
            "label": f"exit_sim_dd{TRAILING_DD}_max{MAX_HOLD}"}


def _read_market(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def load_precomp(market_path: Path, cache_dir: Path, force_rebuild: bool = False):
    """返回 (events_df, node_plan)。缓存 v2 独立文件，源/config 变更时重建。"""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    ev_path = cache_dir / "vol_enhance_v2_events.parquet"
    nd_path = cache_dir / "vol_enhance_v2_nodes.json"
    meta_path = cache_dir / "vol_enhance_v2_meta.json"
    src = str(Path(market_path).resolve())
    src_mtime = Path(market_path).resolve().stat().st_mtime

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
        for nd in nodes:
            nd["node_date"] = pd.Timestamp(nd["node_date"])
            if nd["coef"] is not None:
                nd["coef"] = np.asarray(nd["coef"], dtype=float)
        return events, nodes

    market = normalize_market(_read_market(market_path))
    events = build_events_df(market)
    dates = sorted(market["date"].unique())
    nodes = build_node_plan(events, dates)
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
    for nd in nodes_ser:
        nd["node_date"] = pd.Timestamp(nd["node_date"])
        if nd["coef"] is not None:
            nd["coef"] = np.asarray(nd["coef"], dtype=float)
    return events, nodes_ser


def load_breakouts(events: pd.DataFrame) -> set:
    return {(r.symbol, pd.Timestamp(r.date)) for r in events.itertuples()}
