"""analysis_008 — 牛熊闸门对照（生成版：扩散指标 vs MA200；更新一：+LLT 低延迟趋势线闸门）。

目的：验证候选牛熊 regime（扩散指标 / LLT 切线）作为开仓闸门，是否优于 strategy_006
更新三的 MA200 年线闸门。

方法（简化口径，须与完整引擎回测区分解读）：
  1. 基线 = strategy_006 ab_tests/A_v2（无闸门，修复后引擎，673 笔）
  2. 闸门日度序列（多头=True）：
     - MA200：指数收盘 > MA200（与更新三 strategy.py 同口径）
     - ROC_市值加权 / RSI_市值加权：扩散指标项目 regime_impl（研报最优参数，严格当日成分）
     - **LLT60（更新一）**：广发 LLT 低延迟趋势线(d=60)切线斜率 >0 = 多头
       （沪深300 指数 2005 起长历史算 LLT，规避递推暖机）
  3. 简化筛选：交易的【信号日 = entry 前一交易日】闸门为空头 → 剔除（不开仓）；
     保留交易的全部持有期损益不变（"已开仓的不变"，与更新三闸门只挡开仓端语义一致）
  4. 指标：各版本 trades 过 strategy_005/metrics_from_trades.py（指标铁律同一把尺子）

⚠ 简化口径的已知局限（解读时必须考虑）：
  - 静态筛选不重排坑位：真实引擎中被挡交易不占仓，其他信号可能提前入场；
  - 闸门在信号日判定（池等待跨闸门翻转的少数情形不处理）；
  - regime NaN（窗口未满）按不开仓处理（保守；A_v2 首笔信号日 2017-04-06，各闸门已有值）。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range")
PROJ = ROOT / "replication/research-projects/hs300-enh-2017-2021"
HERE = Path(__file__).resolve().parent
REGIME_DIR = ROOT / "replication/扩散指标择时研究之一-基本用法/03_regime_analysis"
A_V2_TRADES = PROJ / "02_strategy_iteration/strategy_006/ab_tests/A_v2/backtest_logs/trades_paired.csv"
IDX_CSV = REGIME_DIR / "index_000300_daily.csv"
PANEL = PROJ / "_market_hs300_panel_2017.parquet"
METRICS_CLI = PROJ / "02_strategy_iteration/strategy_005/metrics_from_trades.py"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
WEIGHT, COST_BPS = 0.1, 15.0


LLT_IMPL_DIR = ROOT / "replication/短线择时策略研究之三-低延迟趋势线与交易性择时/03_backtest_strategy"
LLT_D = 60                      # LLT 等效 EMA 天数（α=2/(d+1)），广发研报指数较优区


def _load_hs300_idx() -> pd.DataFrame:
    """沪深300 指数全窗（2005 起，本地 warehouse index_bar1d）。"""
    import duckdb
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                     "ORDER BY date").fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def build_gates() -> pd.DataFrame:
    """闸门日度序列（True=多头/允许开仓）。"""
    idx = pd.read_csv(IDX_CSV)
    idx["date"] = pd.to_datetime(idx["date"])
    idx = idx.sort_values("date").reset_index(drop=True)

    # MA200（更新三同口径）
    s = idx.set_index("date")["close"]
    gates = pd.DataFrame({"MA200": s > s.rolling(200).mean()})

    # 扩散指标（研报最优参数，严格当日成分）
    sys.path.insert(0, str(REGIME_DIR))
    from regime_impl import classify_regime          # noqa: E402
    res = classify_regime(idx)
    for m in ("ROC_市值加权", "RSI上下限_市值加权"):
        gates[m] = pd.Series(res["methods"][m], index=idx["date"]).astype("float")

    # LLT60（更新一）：沪深300 2005 起长历史算 LLT → 切线斜率 >0 = 多头
    sys.path.insert(0, str(LLT_IMPL_DIR))
    from reference_implementation import llt         # noqa: E402
    full = _load_hs300_idx().set_index("date")["close"]
    ll = llt(full, LLT_D)
    ll_bull = (ll.diff() > 0)                          # 切线斜率>0（k=0 前向已由 ffill 维持）
    ll_bull = ll_bull.replace(0, pd.NA).ffill().fillna(False)
    # 对齐到 A_v2 交易日历（idx 的 date 范围）
    gates["LLT60"] = ll_bull.reindex(gates.index).astype("float")

    gates.index.name = "date"
    return gates


def filter_trades(trades: pd.DataFrame, gate: pd.Series, name: str) -> pd.DataFrame:
    """信号日（entry 前一交易日）闸门为空头 → 剔除。"""
    cal = pd.DatetimeIndex(gate.index)
    pos = {d: i for i, d in enumerate(cal)}
    sig = []
    for e in pd.to_datetime(trades["entry_date"]):
        i = pos.get(e)
        sig.append(cal[i - 1] if i and i > 0 else pd.NaT)
    g = pd.Series([gate.get(x, np.nan) if pd.notna(x) else np.nan for x in sig],
                  index=trades.index)
    keep = g.fillna(False).astype(bool)              # NaN（窗口未满）保守不开仓
    out = trades[keep].copy()
    dropped = trades[~keep]
    print(f"[{name}] 保留 {len(out)} / 剔除 {len(dropped)} 笔"
          f"（被剔除交易自身收益合计 {dropped['return_pct'].sum():+.1f}%，"
          f"均值 {dropped['return_pct'].mean() if len(dropped) else 0:+.2f}%/笔）")
    return out


def run_metrics(trades_csv: Path, out_dir: Path):
    """同一把尺子：strategy_005/metrics_from_trades.py（指标铁律）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(METRICS_CLI), "--trades", str(trades_csv),
           "--market", str(PANEL), "--out-dir", str(out_dir),
           "--initial-cash", "1000000", "--notional", "100000", "--cost-bps", "15"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"metrics CLI 失败:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return out_dir / "metrics_from_trades.csv"


def main():
    gates = build_gates()
    gates.to_csv(HERE / "gates_daily.csv")
    trades = pd.read_csv(A_V2_TRADES, encoding="utf-8-sig")

    print(f"A_v2 基线：{len(trades)} 笔\n─── 闸门筛选 ───")
    ALL_GATES = (("MA200", "MA200", "ma200"),
                 ("ROC_市值加权", "ROC_市值加权", "roc"),
                 ("RSI上下限_市值加权", "RSI_市值加权", "rsi"),
                 ("LLT60", "LLT60", "llt60"))
    versions = {"A_v2_无闸门": trades}
    for _gname, _short, _fn in ALL_GATES:
        sub = filter_trades(trades, gates[_gname], _short)
        sub.to_csv(HERE / f"A_v2_gate_{_fn}.csv", index=False, encoding="utf-8-sig")
        versions[f"闸门_{_short}"] = sub

    # 剔除交易的年度分布（闸门到底砍了什么）
    print("\n─── 各闸门剔除交易的年度分布（笔数 / 收益合计%）───")
    cal = pd.DatetimeIndex(gates.index)
    pos = {d: i for i, d in enumerate(cal)}
    for _gname, _short, _fn in ALL_GATES:
        g = gates[_gname]
        sig, keep = [], []
        for e in pd.to_datetime(trades["entry_date"]):
            i = pos.get(e)
            sd = cal[i - 1] if i and i > 0 else pd.NaT
            sig.append(sd)
            keep.append(bool(g.get(sd, np.nan)) if pd.notna(sd) else False)
        sig = pd.Series(sig)
        keep = pd.Series(keep)
        dropped = trades[~keep.values].copy()
        dropped["y"] = pd.to_datetime(dropped["entry_date"]).dt.year
        agg = dropped.groupby("y").agg(n=("return_pct", "size"), ret=("return_pct", "sum"))
        print(f"\n[{_short}]")
        print(agg.round(1).to_string())

    # 指标（指标铁律：全部过 metrics_from_trades 同尺子）
    print("\n─── trades 口径指标（metrics_from_trades.py）───")
    rows = {}
    navs = {}
    base_metrics = (A_V2_TRADES.parent / "metrics_from_trades.csv")
    if not base_metrics.exists():                     # A_v2 现成指标缺失时补跑
        run_metrics(A_V2_TRADES, A_V2_TRADES.parent)
    rows["A_v2_无闸门"] = pd.read_csv(base_metrics).iloc[0]
    navs["A_v2_无闸门"] = pd.read_csv(A_V2_TRADES.parent / "nav_from_trades.csv")
    for _gname, _short, _fn in ALL_GATES:
        d = HERE / f"gates_{_fn}"
        run_metrics(HERE / f"A_v2_gate_{_fn}.csv", d)
        rows[f"闸门_{_short}"] = pd.read_csv(d / "metrics_from_trades.csv").iloc[0]
        navs[f"闸门_{_short}"] = pd.read_csv(d / "nav_from_trades.csv")

    cols = ["total_return", "annual_return", "sharpe", "max_drawdown", "n_trades",
            "win_rate_pct", "payoff", "avg_return_pct", "avg_hold_natural_days"]
    cmp = pd.DataFrame(rows).T[cols]
    print(cmp.round(3).to_string())
    cmp.round(4).to_csv(HERE / "gate_comparison.csv", encoding="utf-8-sig")
    return versions, rows, navs


if __name__ == "__main__":
    main()
