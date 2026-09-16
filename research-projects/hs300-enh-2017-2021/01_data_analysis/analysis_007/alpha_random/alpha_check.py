"""analysis_007 更新五 — v3 事件 alpha 检验（随机股 + 同规则对照）。

口径（用户选定"随机股+同规则"）：
  - v3 组：breakout_detail_v3.parquet（12977 事件，更新四规则 m=4 吊灯 + 破线止损 + degree≥2）
    ret 为已有结果（t+1 开盘入场、破 line 止损 / 4×ATR 吊灯、触发日收盘离场）
  - 随机组：对【同一组 (date)】，每个信号日随机抽 1 只【当日成分且非本事件股】的股票
    作伪事件：伪信号日 = 该 date；伪 line = 伪股当日收盘×0.95（无阻力带，用 5% 硬止损
    对称于 v3 的破带）；判定 = 完全复用 analysis.simulate_event（同 4×ATR 吊灯 + 止损）。
  - 样本量对齐：随机组抽 N 组（如 ×5 或 ×10）降单次抽样噪声；报告均值与分布。
  - 检验：v3 ret 均值 vs 随机 ret 均值差、t 检验 / 无参数秩和、超额比例；
    以及收益率分布直方/分位对比（用户第 3 点）。
铁律：随机伪事件只用 ≤t 信息选股（当日成分）、t+1 入场，无未来。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
A7 = HERE.parent
PROJ = A7.parents[1]
sys.path.insert(0, str(A7))
from analysis import simulate_event, load_atr14  # noqa: E402  复用同源判定

SHARED = PROJ / "shared"
PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = Path(r"C:\Quant\trend_range\data_cache\bigquant_warehouse\bigquant_warehouse.duckdb")
RNG = np.random.default_rng(42)
RANDOM_MULT = 10        # 每 v3 事件抽 10 个随机伪事件


def main():
    # ── v3 组（更新四判定结果，已落盘）──
    det = pd.read_parquet(A7 / "breakout_detail_v3.parquet")
    det["date"] = pd.to_datetime(det["date"])
    dec = det[det["result"].isin(["success", "fail"])].copy()
    print(f"v3 组：{len(dec)} 事件（成功 {int((dec.result=='success').sum())} / "
          f"失败 {int((dec.result=='fail').sum())}）| ret 均值 {dec['ret'].mean()*100:+.2f}%")

    # ── 市场/成分/ATR 结构 ──
    market = pd.read_parquet(PANEL)
    market["date"] = pd.to_datetime(market["date"])
    groups = {s: g.sort_values("date").reset_index(drop=True)
              for s, g in market.groupby("symbol")}
    atr_df = load_atr14(PANEL, SHARED)
    atr_by_sym = {s: x.set_index("date")["atr14"] for s, x in atr_df.groupby("symbol")}
    all_syms = sorted(groups.keys())
    sym_loc = {s: i for i, s in enumerate(all_syms)}

    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    comp = con.execute("SELECT date, member_code FROM index_component "
                       "WHERE instrument='000300.SH'").fetchdf()
    con.close()
    comp["date"] = pd.to_datetime(comp["date"])
    comp_mem = {d: set(g["member_code"]) for d, g in comp.groupby("date")}
    comp_dates = sorted(comp_mem)
    # 成分 asof（非记录日沿用最近）
    import bisect
    def members_asof(d):
        if d in comp_mem:
            return comp_mem[d]
        i = bisect.bisect_right(comp_dates, d)
        return comp_mem[comp_dates[i - 1]] if i > 0 else set()

    # ── 逐 v3 事件日抽随机伪事件 ──
    sig_dates = sorted(dec["date"].unique())
    date_loc = {d: i for i, d in enumerate(sig_dates)}
    v3_sig_date_set = {pd.Timestamp(r.date) for r in dec.itertuples()}
    # 需要每个日期当日的成分 + 该日各 v3 事件股（避免抽到信号股本身）
    sig_sym_by_date = {d: set(g["symbol"]) for d, g in dec.groupby("date")}

    rand_rows = []
    n_days = len(sig_dates)
    for di, d in enumerate(sig_dates):
        sig_syms = sig_sym_by_date[d]
        mbr = members_asof(d) & set(all_syms)
        cand = sorted(mbr - sig_syms)                 # 当日成分、非当日 v3 信号股
        if not cand:
            continue
        for _ in range(RANDOM_MULT):
            sym = cand[int(RNG.integers(len(cand)))]
            g = groups[sym]
            gd = g.set_index("date")
            if d not in gd.index:
                continue
            i = g.index[g["date"] == d][0] if (g["date"] == d).any() else None
            if i is None:
                continue
            sig_close = float(g["close"].iloc[i])
            a_ser = atr_by_sym.get(sym)
            atr = (g["date"].map(a_ser).to_numpy(dtype=float) if a_ser is not None
                   else np.full(len(g), np.nan))
            sim = simulate_event(g, atr, i, sig_close * 0.95)   # 伪 line = 信号日 close×0.95
            if sim is None:
                continue
            rand_rows.append({"date": d, "sym": sym, "ret": sim["ret"],
                              "reason": sim["exit_reason"]})
        if (di + 1) % 200 == 0:
            print(f"  [{di + 1}/{n_days}] 随机事件 {len(rand_rows)}")

    rnd = pd.DataFrame(rand_rows)
    rnd = rnd.dropna(subset=["ret"]).reset_index(drop=True)
    print(f"随机组：{len(rnd)} 伪事件（含 {len(dec)*RANDOM_MULT} 目标样本，剔停牌/边界）| "
          f"ret 均值 {rnd['ret'].mean()*100:+.2f}%")

    # ── 配对对齐：同一批 (date, 组) 才有可比性 ──
    # v3 组每事件 ret，随机组抽 10 个 → 用"按 date 聚合均值"比更稳
    v3_by_day = dec.groupby("date")["ret"].agg(["mean", "count"])
    rnd_by_day = rnd.groupby("date")["ret"].agg(["mean", "count"])
    j = v3_by_day.join(rnd_by_day, lsuffix="_v3", rsuffix="_rnd").dropna()
    j = j[j["count_v3"] > 0]
    print(f"\n按信号日对齐 {len(j)} 天")
    diff = j["mean_v3"] - j["mean_rnd"]
    from scipy import stats as st
    t_stat, p_val = st.ttest_1samp(diff, 0)
    z_stat, p_rank = st.ranksums(j["mean_v3"], j["mean_rnd"]) if len(j) > 20 else (np.nan, np.nan)
    print(f"v3 日收益均值 {j['mean_v3'].mean()*100:+.2f}% vs 随机日 {j['mean_rnd'].mean()*100:+.2f}% | "
          f"日差 {diff.mean()*100:+.2f}pp")
    print(f"t检验 p={p_val:.4f} | 秩和 p={p_rank:.4f}" if isinstance(p_rank, float) else "样本不足秩和")

    # ── 汇总落盘 ──
    v3_det = dec[["date", "symbol", "ret", "reason", "degree"]].copy()
    v3_det.to_parquet(HERE / "v3_ret.parquet", index=False)
    rnd.to_parquet(HERE / "random_ret.parquet", index=False)
    pd.DataFrame([{"v3_mean_ret": dec["ret"].mean(), "random_mean_ret": rnd["ret"].mean(),
                   "v3_n": len(dec), "random_n": len(rnd),
                   "day_diff_mean_pp": diff.mean() * 100, "t_p": p_val}]).to_csv(
        HERE / "alpha_summary.csv", index=False)
    print("\n写出 alpha_random/: v3_ret.parquet / random_ret.parquet / alpha_summary.csv")
    return dec, rnd, j


if __name__ == "__main__":
    main()
