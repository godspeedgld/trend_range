"""analysis_009 — LLT 扩散指标：LLT(d=60) 切线斜率做个股牛熊判定（研报二方法），
聚合与快慢线判断沿用研报一（扩散指标）框架，严格当日沪深300成分股。

构造（两研报杂交）：
  微观（研报二 §三）：个股 LLT(d=60) 低延迟趋势线，切线斜率 k=LLT(t)−LLT(t−1)；
    k>0 → 该股多头；k≤0 → 空头（k=0 浮点相等极罕见，不另设维持态）
  宏观（研报一 §2.1）：当日严格在册成分 → 多头占比（等权 / 总市值加权）= 扩散指标 D；
    快线 FAST=MA_{N1}(D)，慢线 SLOW=MA_{N2}(FAST)（第二次平滑作用于快线）；
    FAST>SLOW = 指数多头，反之为空头（两态，研报一无第三态）
  平滑参数取研报一最优：N1=80/N2=35（ROC 判定器最优——LLT 斜率同为动量型判定器，
    语义最接近）；另做 N1=80/N2=60（MA 判定器最优）做平滑敏感性对照。

验证（HS300 指数，2015-01~2026-08，本地面板区间）：
  1. 状态统计：多头占比 / 段数 / 平均段长
  2. 区分度（无未来）：t 收盘状态 → t+1 指数收益归因：多头日 vs 空头日年化、方向 IC
  3. 关键时段抽查：各时段多头占比，对照 MA200 与研报一 ROC_市值加权扩散指标
  4. 可视化 result_view.html

铁律无未来：LLT/斜率 t 日值仅由 ≤t 收盘推出；成分非记录日沿用 ≤d 最近记录；
区分度归因用 shift(1) 状态对 t+1 收益。窗口未满（N1+N2+暖机）标 NaN。
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
LLT_DIR = ROOT / "replication/短线择时策略研究之三-低延迟趋势线与交易性择时/03_backtest_strategy"
DIFF_DIR = ROOT / "replication/扩散指标择时研究之一-基本用法/03_regime_analysis"
PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

LLT_D = 60                      # 研报二 LLT 窗（用户指定 d=60）
SMOOTH_VARIANTS = {             # 研报一最优平滑参数（名称: N1, N2）
    "LLT扩散_市值加权_80_35": ("mcap", 80, 35),    # ROC 判定器最优（主口径）
    "LLT扩散_等权_80_35": ("equal", 80, 35),
    "LLT扩散_市值加权_80_60": ("mcap", 80, 60),    # MA 判定器最优（敏感性）
}
KEY_PERIODS = {                 # 关键时段（沿 analysis_008）
    "2015股灾": ("2015-06-15", "2015-09-30"),
    "2016-17慢牛": ("2016-02-01", "2017-11-30"),
    "2018熊市": ("2018-02-01", "2018-12-28"),
    "2019反弹": ("2019-01-04", "2019-04-19"),
    "2020H2牛": ("2020-07-01", "2021-02-18"),
    "2022熊市": ("2022-01-04", "2022-10-31"),
    "2024-09急牛": ("2024-09-24", "2024-10-08"),
    "2025牛市": ("2025-01-01", "2025-11-30"),
    "2026至今": ("2026-01-01", "2026-08-14"),
}

sys.path.insert(0, str(LLT_DIR))
from reference_implementation import llt               # noqa: E402  研报二同源 LLT


def load_panel():
    p = pd.read_parquet(PANEL)
    p["date"] = pd.to_datetime(p["date"])
    for c in ("close", "total_market_cap"):
        p[c] = pd.to_numeric(p[c], errors="coerce")
    p = p.dropna(subset=["close"])
    p = p[p["close"] > 0]
    return p.sort_values(["symbol", "date"]).reset_index(drop=True)


def member_mask(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """严格当日成分 mask（date×symbol bool；非记录日沿用 ≤d 最近记录）。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    comp = con.execute("SELECT date, member_code FROM index_component "
                       "WHERE instrument='000300.SH'").fetchdf()
    con.close()
    comp["date"] = pd.to_datetime(comp["date"])
    membership = {d: set(g["member_code"]) for d, g in comp.groupby("date")}
    rec_ts = sorted(membership)
    rec64 = np.array(rec_ts, dtype="datetime64[ns]")
    panel_syms = _PANEL["symbol"].unique()
    mask = pd.DataFrame(False, index=dates, columns=panel_syms)
    pos = np.searchsorted(rec64, dates.to_numpy(), side="right") - 1
    for i, d in enumerate(dates):
        if pos[i] < 0:
            continue
        mask.iloc[i] = mask.columns.isin(membership[rec_ts[pos[i]]])
    return mask


_PANEL: pd.DataFrame | None = None


def _panel() -> pd.DataFrame:
    global _PANEL
    if _PANEL is None:
        _PANEL = load_panel()
    return _PANEL


def llt_bull_pivot() -> pd.DataFrame:
    """逐股 LLT(d) 切线斜率 >0 → date×symbol bool 透视（研报二微观判定）。"""
    panel = _panel()
    alpha = 2.0 / (LLT_D + 1)
    parts = []
    for sym, g in panel.groupby("symbol", sort=False):
        # ⚠ set_index("date")：groupby 的 g 为行号 index，必须换轨到日期
        k = llt(g.set_index("date")["close"], LLT_D).diff()   # 切线斜率（向前差分）
        parts.append((k > 0).rename(sym))
    return pd.concat(parts, axis=1)


def diffusion(bull: pd.DataFrame, weight: str) -> pd.Series:
    """严格成分下的扩散指标 D(t)：等权 = 多头家数/有效家数；市值 = 多头市值/有效市值。"""
    dates = pd.DatetimeIndex(sorted(_PANEL["date"].unique()))
    mask = member_mask(dates).reindex(index=dates, columns=bull.columns).fillna(False)
    b = bull.where(mask)                                   # 非当日在册 → 不入分子/分母
    if weight == "equal":
        return b.mean(axis=1, skipna=True)
    mcap = _PANEL.pivot_table(index="date", columns="symbol",
                              values="total_market_cap").sort_index()
    mcap = mcap.reindex(index=dates, columns=b.columns)
    w = mcap.where(b.notna())
    return w.where(b).sum(axis=1, skipna=True) / w.sum(axis=1, skipna=True)


def states(dif: pd.Series, n1: int, n2: int) -> pd.Series:
    """研报一框架：快线 MA_N1(D)，慢线 MA_N2(快线)；快>慢=1 多头，反之 0；窗口未满 NaN。"""
    fast = dif.rolling(n1).mean()
    slow = fast.rolling(n2).mean()
    st = (fast > slow).astype(float)
    st[~(fast.notna() & slow.notna())] = np.nan
    st.iloc[:LLT_D + n1 + n2] = np.nan                     # LLT 暖机 + 平滑窗
    return st


def load_index() -> pd.Series:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    idx = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                      "ORDER BY date").fetchdf()
    con.close()
    idx["date"] = pd.to_datetime(idx["date"])
    return idx.set_index("date")["close"]


def roc_diffusion_states(dates: pd.DatetimeIndex) -> pd.Series:
    """研报一 ROC_市值加权(N=100/80/35) 扩散状态（严格成分，同项目 regime_impl）。"""
    sys.path.insert(0, str(DIFF_DIR))
    from regime_impl import classify_regime               # noqa: E402
    idx_df = pd.DataFrame({"date": dates})
    res = classify_regime(idx_df)
    return pd.Series(res["methods"]["ROC_市值加权"], index=dates, dtype=float)


def quality(states_by_name: dict, index_close: pd.Series) -> pd.DataFrame:
    """区分度（无未来）：t 收盘状态 → t+1 收盘收益归因。"""
    ret = index_close.pct_change()
    rows = {}
    for name, st in states_by_name.items():
        st = st.reindex(ret.index)                         # 面板日历 → 指数日历对齐
        s = st.shift(1)                                    # t-1 收盘状态 → t 日收益
        valid = st.notna() & s.notna()
        r, sv = ret[valid], s[valid]
        # 状态为 0/1 两态（研报一口径）：1=多头日，0=空头日
        ld, sd = r[sv > 0.5], r[sv < 0.5]

        def ann(x):
            return (1 + x).prod() ** (252 / len(x)) - 1 if len(x) > 20 else np.nan

        rows[name] = {
            "多头日数": int((sv > 0.5).sum()), "空头日数": int((sv < 0.5).sum()),
            "多头日年化": ann(ld), "空头日年化": ann(sd),
            "区分度pp": (ann(ld) - ann(sd)) * 100,
            "IC": sv.corr(r),
        }
    return pd.DataFrame(rows).T


def key_periods_table(states_by_name: dict) -> pd.DataFrame:
    out = {}
    for name, st in states_by_name.items():
        out[name] = {k: round(float((st.loc[a:b] == 1).mean()), 2)
                     if st.loc[a:b].notna().any() else np.nan
                     for k, (a, b) in KEY_PERIODS.items()}
    return pd.DataFrame(out)


def main():
    print("─── 1. 个股 LLT(60) 斜率多头判定（研报二）───")
    bull = llt_bull_pivot()
    print(f"面板 {bull.shape[0]} 日 × {bull.shape[1]} 股")

    print("─── 2. 扩散指标聚合 + 快慢线状态（研报一框架，严格当日成分）───")
    dif_cache = {}
    states_by_name = {}
    for name, (weight, n1, n2) in SMOOTH_VARIANTS.items():
        if weight not in dif_cache:
            dif_cache[weight] = diffusion(bull, weight)
        dif_cache[weight].rename("D").to_frame().to_csv(
            HERE / f"diffusion_{weight}.csv", encoding="utf-8-sig")
        states_by_name[name] = states(dif_cache[weight], n1, n2)
        s = states_by_name[name].dropna()
        segs = (s != s.shift()).cumsum().nunique()
        print(f"{name}: 有效 {len(s)} 日 | 多头 {(s>0).mean()*100:.0f}% | "
              f"{segs} 段 / 均 {len(s)/segs:.0f} 日")

    # 对照闸门
    idx = load_index()
    common_dates = idx.index[idx.index >= pd.Timestamp("2015-01-01")]
    states_by_name["MA200"] = (idx > idx.rolling(200).mean()).reindex(common_dates).astype(float)
    states_by_name["研报一_ROC扩散"] = roc_diffusion_states(common_dates)

    print("\n─── 3. 区分度（t 收盘状态 → t+1 收益归因；有效窗约 2015-10 起）───")
    q = quality(states_by_name, idx)
    print(q.round(3).to_string())

    print("\n─── 4. 关键时段多头占比（NaN=暖期无效）───")
    kp = key_periods_table(states_by_name)
    print(kp.to_string())

    print("\n─── 5. 前瞻 K 日收益（慢信号公平检验：t 收盘状态 → t+K 收益年化）───")
    fw = forward_returns(states_by_name, idx)
    print(fw.round(1).to_string())

    q.round(4).to_csv(HERE / "quality_comparison.csv", encoding="utf-8-sig")
    kp.to_csv(HERE / "key_periods.csv", encoding="utf-8-sig")
    fw.round(2).to_csv(HERE / "forward_returns.csv", encoding="utf-8-sig")
    pd.DataFrame(states_by_name).to_csv(HERE / "states_daily.csv", encoding="utf-8-sig")
    print("\n写出: diffusion_{equal,mcap}.csv / quality_comparison.csv / "
          "key_periods.csv / forward_returns.csv / states_daily.csv")


def forward_returns(states_by_name: dict, index_close: pd.Series) -> pd.DataFrame:
    """前瞻 K 日收益（年化%）：状态 t 收盘 → close(t+K)/close(t)−1。
    慢趋势信号的公平检验（次日 IC 对慢信号系统性低估；前瞻窗口含重叠仅作描述统计）。"""
    out = {}
    for name, st in states_by_name.items():
        s = st.reindex(index_close.index)
        v = s.notna()
        row = {}
        for K in (1, 5, 20, 60):
            fwd = (index_close.shift(-K) / index_close - 1)[v]
            sv = s[v]
            row[f"多头{K}d"] = fwd[sv > 0.5].mean() * 252 / K * 100
            row[f"空头{K}d"] = fwd[sv < 0.5].mean() * 252 / K * 100
        out[name] = row
    return pd.DataFrame(out).T


if __name__ == "__main__":
    main()
