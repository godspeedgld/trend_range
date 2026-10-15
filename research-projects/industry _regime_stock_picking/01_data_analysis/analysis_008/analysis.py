"""analysis_008 — 六因子为何输给四因子基线：交易记录 × 行业轮动归因（不重跑回测）。

承 strategy_004（方案 B 六因子 3.173x vs 基线 3.600x，共同区间 ≥2017-05-12）与
analysis_007（3 个新因子本身有效、落在随机因子集 95 分位 ⇒ 输在结构不在因子挑选）。
本分析回答剩下的「**输在哪**」：

  A. 净值差距曲线 —— 差距在什么时段 / regime 累积（nav_from_trades，日粒度聚合到周）
  B. 持仓重叠 —— 两版每周实际持仓的重合度（position_return_detail = 引擎真实持仓）
  C. 逐日收益分解 —— 差距拆成 {共同持仓的权重差 | 六因子独有票 | 基线独有票 | 费用}，
     **逐日**口径：昨收持仓权重 × 今收收益（与 NAV 估值同频），再按周聚合。
     ★ 不用周窗口的原因（实测踩坑）：空仓切换周清算滞后 1~2 天，exec 日持仓明细里
       是「正在清仓的旧仓」，周窗口模型会拿旧仓的整周波动去对一条已经平掉的 NAV。
  D. 行业 × regime 归因 —— 差距集中在哪些行业、动量周还是反转周
     （边际票质量只统计**满仓周 exposure=1** 的决策，排除清算残留；另标 fresh=新开仓）
  E. 头部检验 —— 同一行业周内全体候选分别按两套打分取 top2 的前瞻收益对比
     + 池化 IC vs 行业内 IC（IC 两种粒度都升，但头部变差 → 增量信息在中段）
  F. 边际票画像 —— 独有票的**行业内 rank_pct 中位数**（换进来的是什么票）

两套收益口径（明确分开，勿混引）：
  · raw 收-收（engine_market_weekly_indpre_rawpx）→ 分解 / 边际票（对齐引擎估值）
  · hfq 开-开（panel.exec_open）→ 头部检验与 IC（对齐 analysis_003/006 既有标尺口径）

数据全部来自已有回测产物 + shared 冻结件（**不重跑任何回测**）：
  strategy_004/backtest_strategy{,_baseline}/backtest_logs/{nav_from_trades,trades,position_return_detail}.csv
  shared/_cache/{weekly_plan,signal_panel_weekly_indpre,engine_market_weekly_indpre_rawpx}.parquet
  仓库 v_factor_1w（3 个新因子列，经 shared/build_weekly_targets_b6.load_panel6 同款 join）

用法：python analysis.py
产物：daily_decomp.csv / marginal_picks.csv / head_test_weeks.csv / result_view.html
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SHARED = PROJ / "shared"
sys.path.insert(0, str(SHARED))

from build_weekly_targets_b6 import DIRS6, load_panel6  # noqa: E402  ★ 复用冻结件

B6 = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy/backtest_logs"
BL = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy_baseline/backtest_logs"
CACHE = SHARED / "_cache"
CUT = pd.Timestamp("2017-05-12")            # 共同区间起点 = 基线首个满仓日（analysis_007 口径）
FACTORS4 = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]
DIRS4 = {f: -1 for f in FACTORS4}           # 基线恒反转（build_weekly_targets.factor_directions("baseline")）
INIT_CAP = 500_000.0

# ── 视图配色（dataviz 校验通过：类别蓝/橙 + 发散红/蓝，浅色表面）──
C_BASE, C_6F = "#2a78d6", "#eb6834"         # 基线=蓝  六因子=橙（固定，不随图换）
C_POS, C_NEG = "#2a78d6", "#e34948"         # 发散：正=蓝 负=红（六因子视角：正=6F更好）
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


def load_all():
    wp = pd.read_parquet(CACHE / "weekly_plan.parquet")
    for c in ("signal_date", "exec_date"):
        wp[c] = pd.to_datetime(wp[c])
    nav6 = pd.read_csv(B6 / "nav_from_trades.csv")
    navb = pd.read_csv(BL / "nav_from_trades.csv")
    for d in (nav6, navb):
        d["date"] = pd.to_datetime(d["date"])
    tr6 = pd.read_csv(B6 / "trades.csv"); tr6["date"] = pd.to_datetime(tr6["date"])
    trb = pd.read_csv(BL / "trades.csv"); trb["date"] = pd.to_datetime(trb["date"])
    pos6 = pd.read_csv(B6 / "position_return_detail.csv"); pos6["date"] = pd.to_datetime(pos6["date"])
    posb = pd.read_csv(BL / "position_return_detail.csv"); posb["date"] = pd.to_datetime(posb["date"])
    return wp, nav6, navb, tr6, trb, pos6, posb


def common_nav_metrics(nav: pd.DataFrame) -> dict:
    """共同区间（≥CUT）净值 —— 与 strategy_004 报告口径一致（全序列 pct_change 后再切）。"""
    dt = nav["date"].to_numpy()
    ret = pd.Series(nav["nav"].to_numpy(dtype=float)).pct_change().to_numpy()
    ret = ret[dt >= CUT]; ret = ret[~np.isnan(ret)]
    return {"final_nav": float((1 + ret).prod()), "n_days": int(len(ret))}


def build_weekly_frames(wp, nav6, navb, pos6, posb) -> list[dict]:
    """逐周帧：exec 日持仓 {symbol: weight} + 周 regime/exposure（净值收益改由逐日分解承担）。"""
    execs = wp.loc[wp["exec_date"] > CUT,
                   ["signal_date", "exec_date", "regime", "T_prime", "top3", "exposure"]].copy()
    execs = execs[execs["exec_date"] <= nav6["date"].max()].reset_index(drop=True)
    hold6 = {d: dict(zip(g["symbol"], g["weight"])) for d, g in pos6.groupby("date")}
    holdb = {d: dict(zip(g["symbol"], g["weight"])) for d, g in posb.groupby("date")}
    rows = []
    for i in range(len(execs) - 1):
        w, wn = execs.iloc[i], execs.iloc[i + 1]
        e = w["exec_date"]
        prev6 = hold6.get(execs.iloc[i - 1]["exec_date"], {}) if i > 0 else {}
        prevb = holdb.get(execs.iloc[i - 1]["exec_date"], {}) if i > 0 else {}
        rows.append({
            "week": i, "signal_date": w["signal_date"], "exec_date": e, "next_exec": wn["exec_date"],
            "regime": w["regime"], "top3": w["top3"], "exposure": w["exposure"],
            "pos6": hold6.get(e, {}), "posb": holdb.get(e, {}),
            "prev6": prev6, "prevb": prevb,
        })
    return rows


def raw_close_matrix(syms: list[str], d0, d1) -> pd.DataFrame:
    """held 股票在共同窗口内每交易日的 raw 收盘价宽表（date × symbol）。"""
    import duckdb
    slist = ",".join(repr(s) for s in syms)
    con = duckdb.connect()
    op = con.execute(f"""
        SELECT date, symbol, close
        FROM read_parquet('{(CACHE / "engine_market_weekly_indpre_rawpx.parquet").as_posix()}')
        WHERE symbol IN ({slist}) AND date >= DATE '{d0.date()}' AND date <= DATE '{d1.date()}'
    """).df()
    con.close()
    op["date"] = pd.to_datetime(op["date"])
    return op.pivot(index="date", columns="symbol", values="close").sort_index()


def decomp_daily(nav6, navb, pos6, posb, tr6, trb, close_m: pd.DataFrame) -> pd.DataFrame:
    """逐日：gap_log(d) = log1p(r6)−log1p(rb) ≈ Σ_共同(Δw)r + Σ_6F独有 w·r − Σ_基线独有 w·r − 费用差。"""
    nav6i = nav6.set_index("date"); navb_i = navb.set_index("date")
    hold6 = {d: dict(zip(g["symbol"], g["weight"])) for d, g in pos6.groupby("date")}
    holdb = {d: dict(zip(g["symbol"], g["weight"])) for d, g in posb.groupby("date")}
    fee6 = tr6.groupby("date")["fee"].sum(); feeb = trb.groupby("date")["fee"].sum()
    dates = [d for d in close_m.index if d in nav6i.index and d > min(close_m.index)]
    rets = close_m.pct_change(fill_method="pad")   # 停牌日收益 0，复牌日含跳空 —— 与引擎按最近收盘估值一致

    out = []
    for i in range(1, len(dates)):
        d, dp = dates[i], dates[i - 1]
        h6, hb = hold6.get(dp, {}), holdb.get(dp, {})
        rrow = rets.loc[d] if d in rets.index else None
        c_common = c_only6 = c_onlyb = m6r = mbr = 0.0
        for s in set(h6) | set(hb):
            r = rrow.get(s) if rrow is not None else None
            if r is None or not np.isfinite(r):
                continue
            w6, wb = h6.get(s), hb.get(s)
            if w6 is not None: m6r += w6 * r
            if wb is not None: mbr += wb * r
            if w6 is not None and wb is not None:
                c_common += (w6 - wb) * r
            elif w6 is not None:
                c_only6 += w6 * r
            else:
                c_onlyb += wb * r
        r6 = nav6i.at[d, "ret"]; rb = navb_i.at[d, "ret"]
        eq6 = INIT_CAP * float(nav6i.at[dp, "nav"])
        fee = -((float(fee6.get(d, 0.0)) - float(feeb.get(d, 0.0))) / eq6) if eq6 else 0.0
        gap = np.log1p(r6) - np.log1p(rb)
        out.append({"date": d, "gap_log": gap, "r6_nav": r6, "rb_nav": rb,
                    "c_common": c_common, "c_only6": c_only6, "c_onlyb": c_onlyb,
                    "fee": fee, "m6_ret": m6r, "mb_ret": mbr})
    df = pd.DataFrame(out)
    df["residual"] = df["gap_log"] - (df["c_common"] + df["c_only6"] - df["c_onlyb"] + df["fee"])
    return df


def week_of(date, boundaries: list) -> int:
    """date 落在第几个 exec 周窗（boundaries = 排序后的 exec_date 列表）。"""
    import bisect
    return bisect.bisect_right(boundaries, date) - 1


def weekly_quality(wf, close_m) -> pd.DataFrame:
    """满仓周的选股质量：exec 日持仓的当周收-收收益（边际票 M6/MB + fresh 标记）。"""
    rows = []
    for w in wf:
        if w["exposure"] != 1.0:
            continue
        e, en = w["exec_date"], w["next_exec"]
        if e not in close_m.index or en not in close_m.index:
            continue
        rweek = close_m.loc[en] / close_m.loc[e] - 1
        for s in set(w["pos6"]) | set(w["posb"]):
            r = rweek.get(s)
            if r is None or not np.isfinite(r):
                continue
            w6, wb = w["pos6"].get(s), w["posb"].get(s)
            if w6 is not None and wb is not None:
                side, wt = "both", (w6 + wb) / 2
            elif w6 is not None:
                side, wt = "6F", w6
            else:
                side, wt = "base", wb
            rows.append({"signal_date": w["signal_date"], "regime": w["regime"], "exec_date": e,
                         "side": side, "symbol": s, "ret": float(r), "weight": wt,
                         "fresh6": s not in w["prev6"], "freshb": s not in w["prevb"]})
    return pd.DataFrame(rows)


def head_test(panel6: pd.DataFrame, wp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """E. 头部检验（hfq 开-开口径，与 analysis_003/006 同）。

    返回 (top2 行, 名次分桶行, IC 行)。`selected` = 该行业当周是否在 top3（策略真实选择范围）。
    IC 两种粒度：池化（每 signal_date 全候选 Spearman）vs 行业内（每 (date, ind) 组内）。
    """
    p = panel6[panel6["date"] >= CUT].copy()
    p = p.dropna(subset=["fwd"])
    top3_of = {d: set(t.split(",")) for d, t in zip(wp["signal_date"], wp["top3"])}

    rows, buckets, ic_rows = [], [], []
    for d, sub_d in p.groupby("date", sort=False):
        t3 = top3_of.get(d, set())
        fwd_d = dict(zip(sub_d["symbol"], sub_d["fwd"]))
        for nm, factors, dirs in (("4F", FACTORS4, DIRS4), ("6F", list(DIRS6), DIRS6)):
            sc = pd.concat([sub_d[f].mul(dirs[f]).rank(pct=True) for f in factors],
                           axis=1).mean(axis=1)
            ok = sc.notna() & sub_d["fwd"].notna()
            if ok.sum() > 30:
                ic_rows.append({"date": d, "scope": "pooled", "score": nm,
                                "ic": sc[ok].corr(sub_d.loc[ok, "fwd"], method="spearman"),
                                "n": int(ok.sum())})
        for ind, sub in sub_d.groupby("ind_name", sort=False):
            if len(sub) < 12:
                continue
            tops = {}
            for nm, factors, dirs in (("4F", FACTORS4, DIRS4), ("6F", list(DIRS6), DIRS6)):
                sc = pd.concat([sub[f].mul(dirs[f]).rank(pct=True) for f in factors],
                               axis=1).mean(axis=1)
                ok = sc.notna() & sub["fwd"].notna()
                if ok.sum() > 8:
                    ic_rows.append({"date": d, "scope": "within", "score": nm,
                                    "ic": sc[ok].corr(sub.loc[ok, "fwd"], method="spearman"),
                                    "n": int(ok.sum())})
                s = sub.assign(_s=sc).dropna(subset=["_s"])
                if s.empty:
                    tops[nm] = []
                    continue
                r = s.sort_values(["_s", "symbol"], ascending=[False, True])["symbol"].tolist()
                tops[nm] = r[:2]
                for a, b, bn in ((0, 2, "1-2"), (2, 6, "3-6"), (6, 12, "7-12"), (12, 30, "13-30"), (30, 10**9, ">30")):
                    if len(s) > a:
                        pick = r[a:min(b, len(s))]
                        buckets.append({"date": d, "ind": ind, "score": nm, "bucket": bn,
                                        "fwd": float(np.mean([fwd_d[x] for x in pick]))})
            if not tops["4F"] or not tops["6F"]:
                continue
            rows.append({"date": d, "ind_name": ind, "regime": sub["regime"].iloc[0],
                         "selected": ind in t3, "n_cand": len(sub),
                         "r_top2_4": float(np.mean([fwd_d[s] for s in tops["4F"]])),
                         "r_top2_6": float(np.mean([fwd_d[s] for s in tops["6F"]])),
                         "differ": set(tops["4F"]) != set(tops["6F"])})
    return pd.DataFrame(rows), pd.DataFrame(buckets), pd.DataFrame(ic_rows)


def factor_profile(q: pd.DataFrame, panel6: pd.DataFrame) -> pd.DataFrame:
    """F. 边际票的行业内 rank_pct 中位数（0.5=行业中位；跨行业可比）。"""
    cols = list(dict.fromkeys(FACTORS4 + list(DIRS6)))
    rk = panel6.copy()
    for c in cols:
        rk[c] = rk.groupby(["date", "ind_name"])[c].rank(pct=True)
    rk = rk.set_index(["date", "symbol"])[cols]
    prof = pd.DataFrame(index=cols, dtype=float)
    for side in ("6F", "base"):
        g = q[q["side"] == side]
        keys = [(d, s) for d, s in zip(g["signal_date"], g["symbol"]) if (d, s) in rk.index]
        prof[side] = rk.loc[keys].median()
    return prof


def main():
    print("[1/8] 读入回测产物与面板 …")
    wp, nav6, navb, tr6, trb, pos6, posb = load_all()
    m6 = common_nav_metrics(nav6); mb = common_nav_metrics(navb)
    print(f"    共同区间净值：6F {m6['final_nav']:.4f} / 基线 {mb['final_nav']:.4f}"
          f"（报告值 3.1732 / 3.6001）")

    print("[2/8] 面板 + 3 个新因子（v_factor_1w join）…")
    panel6 = load_panel6()
    p = panel6.sort_values(["symbol", "date"])
    p["fwd"] = p.groupby("symbol")["exec_open"].shift(-1) / p["exec_open"] - 1   # hfq 开-开
    panel6 = p
    ind_of = dict(zip(zip(panel6["date"], panel6["symbol"]), panel6["ind_name"]))
    sym_last_ind = {s: g.iloc[-1]["ind_name"]
                    for s, g in panel6.sort_values("date").groupby("symbol")}
    reg_of = dict(zip(wp["signal_date"], wp["regime"]))
    panel6["regime"] = panel6["date"].map(reg_of)

    print("[3/8] 逐周帧 + 持仓重叠 …")
    wf = build_weekly_frames(wp, nav6, navb, pos6, posb)
    jac, slots = [], []
    for w in wf:
        s6, sb = w["pos6"], w["posb"]
        if s6 or sb:
            jac.append(len(set(s6) & set(sb)) / max(1, len(set(s6) | set(sb))))
            slots.append(len(set(s6) & set(sb)))
    full = [w for w in wf if w["exposure"] == 1.0]
    jac_full = [len(set(w["pos6"]) & set(w["posb"])) / max(1, len(set(w["pos6"]) | set(w["posb"])))
                for w in full if w["pos6"] or w["posb"]]
    print(f"    有持仓周 {len(jac)}：周均 Jaccard {np.mean(jac):.3f}（周均同票 {np.mean(slots):.2f}/6）")
    print(f"    满仓周 {len(full)}：Jaccard {np.mean(jac_full):.3f}")

    print("[4/8] raw 收盘矩阵（duckdb）+ 逐日分解 …")
    syms = sorted(set().union(*[{s for w in wf for s in set(w["pos6"]) | set(w["posb"])}]))
    close_m = raw_close_matrix(syms, CUT, nav6["date"].max())
    dd = decomp_daily(nav6, navb, pos6, posb, tr6, trb, close_m)
    tot = dd[["gap_log", "c_common", "c_only6", "c_onlyb", "fee", "residual"]].sum()
    print(f"    Σgap_log {tot['gap_log']:+.4f}（校验 log(3.1732/3.6001)={np.log(3.1732/3.6001):+.4f}）")
    print(f"    共同权重差 {tot['c_common']:+.4f} | 6F独有 {tot['c_only6']:+.4f} | "
          f"基线独有 −{tot['c_onlyb']:.4f} | 费用差 {tot['fee']:+.4f} | 残差 {tot['residual']:+.4f}")
    print(f"    单边对账相关：6F {dd['r6_nav'].corr(dd['m6_ret']):.3f} / base {dd['rb_nav'].corr(dd['mb_ret']):.3f}"
          f"｜分解与 gap_log 日相关 {(dd['c_common']+dd['c_only6']-dd['c_onlyb']+dd['fee']).corr(dd['gap_log']):.3f}")

    # 周聚合（图与 regime/年度汇总用）
    boundaries = sorted(w["exec_date"] for w in wf)
    dd["week"] = [week_of(d, boundaries) for d in dd["date"]]
    wkmap = {w["week"]: w for w in wf}
    dd["regime"] = dd["week"].map(lambda i: wkmap[i]["regime"] if i in wkmap else None)
    dec = dd.groupby("week").agg(
        signal_date=("date", "last"), gap_log=("gap_log", "sum"),
        c_common=("c_common", "sum"), c_only6=("c_only6", "sum"), c_onlyb=("c_onlyb", "sum"),
        fee=("fee", "sum"), residual=("residual", "sum"), regime=("regime", "last")).reset_index()
    dec["signal_date"] = dec["signal_date"].map(lambda d: wkmap.get(week_of(d, boundaries), {}).get("signal_date", d))

    print("[5/8] 边际票质量（满仓周） / 行业 / regime …")
    q = weekly_quality(wf, close_m)
    q["ind"] = [ind_of.get((d, s)) or sym_last_ind.get(s, "?")
                for d, s in zip(q["signal_date"], q["symbol"])]
    by_ind = pd.Series(dtype=float)
    if len(q):
        for side, g in q.groupby("side"):
            print(f"    {side} 票 {len(g)} 只·周：当周收益均值 {g['ret'].mean():+.4%} "
                  f"胜率 {(g['ret'] > 0).mean():.1%}")
        m = q[q["side"] != "both"]
        for side, g in m.groupby("side"):
            fr = g[g["fresh6"]] if side == "6F" else g[g["freshb"]]
            print(f"    {side} 独有（fresh 新开仓 {len(fr)}/{len(g)}）：{fr['ret'].mean():+.4%}")
        q_m = q[q["side"] != "both"].copy()
        q_m["contrib"] = np.where(q_m["side"] == "6F", q_m["weight"] * q_m["ret"],
                                  -q_m["weight"] * q_m["ret"])
        by_ind = q_m.groupby("ind")["contrib"].sum().sort_values()
        print("    行业归因（正=6F 更好）最差 5：", {k: round(v, 4) for k, v in by_ind.head(5).items()})
        print("    行业归因 最好 5：", {k: round(v, 4) for k, v in by_ind.tail(5).items()})
        for rg, g in q_m.groupby("regime"):
            d = g[g["side"] == "6F"]["ret"].mean() - g[g["side"] == "base"]["ret"].mean()
            print(f"    {rg} 周：6F独有 − 基线独有 当周均值 {d:+.4%}（n={len(g)}）")
    for rg, g in dec.groupby("regime"):
        print(f"    {rg} 周 Σgap_log {g['gap_log'].sum():+.4f}（{len(g)} 周）")
    dec["year"] = pd.to_datetime(dec["signal_date"]).dt.year
    yr = dec.groupby("year")["gap_log"].sum()
    print("    年度 Σgap_log：", {int(k): round(v, 4) for k, v in yr.items()})

    print("[6/8] 头部检验 + 池化/行业内 IC …")
    ht, bk, ic = head_test(panel6, wp)
    for sel, g in ((True, ht[ht["selected"]]), (False, ht[~ht["selected"]]), (None, ht)):
        tag = "全部" if sel is None else ("top3 行业内" if sel else "非选中行业")
        diff = g[g["differ"]]
        w6 = (diff["r_top2_6"] > diff["r_top2_4"]).mean() if len(diff) else np.nan
        print(f"    [{tag}] 行业周 {len(g)}：6F top2 {g['r_top2_6'].mean():+.4%} vs "
              f"4F {g['r_top2_4'].mean():+.4%}｜top2 不同占 {len(diff)/max(1,len(g)):.0%}，"
              f"6F 胜率 {w6:.1%}")
    hb = bk[bk["bucket"] == "1-2"].groupby("score")["fwd"].mean()
    mid = bk[bk["bucket"].isin(["3-6", "7-12"])].groupby("score")["fwd"].mean()
    print(f"    名次 1-2 桶：{hb.round(5).to_dict()} ｜ 名次 3-12 桶：{mid.round(5).to_dict()}")
    icm = ic.groupby(["scope", "score"])["ic"].mean()
    print(f"    IC 均值：{icm.round(4).to_dict()}")

    print("[7/8] 边际票因子画像（行业内 rank_pct 中位数）…")
    prof = factor_profile(q, panel6) if len(q) else pd.DataFrame()
    if len(prof):
        print(prof.round(3).to_string())

    print("[8/8] 写 result_view.html …")
    dd.to_csv(HERE / "daily_decomp.csv", index=False, encoding="utf-8-sig")
    q.to_csv(HERE / "marginal_picks.csv", index=False, encoding="utf-8-sig")
    ht.to_csv(HERE / "head_test_weeks.csv", index=False, encoding="utf-8-sig")
    html = build_view(nav6, navb, dec, q, ht, bk, ic, prof, by_ind, jac, jac_full)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("完成。")


# ══════════════════════════════ 视图（plotly 离线单文件）══════════════════════════════
def build_view(nav6, navb, dec, q, ht, bk, ic, prof, by_ind, jac, jac_full):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    LAY = dict(font=dict(family="Arial,'Microsoft YaHei',sans-serif", color=INK2, size=13),
               paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
               xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               hovermode="x unified", margin=dict(l=56, r=24, t=56, b=44),
               showlegend=True)
    NOL = {k: v for k, v in LAY.items() if k != "showlegend"} | {"showlegend": False}
    figs = []

    # 图1 净值 + 累计 gap（两行子图，各自坐标，非双轴）
    f1 = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.62, 0.38], vertical_spacing=0.06)
    c = nav6[nav6["date"] >= CUT]; b = navb[navb["date"] >= CUT]
    f1.add_trace(go.Scatter(x=b["date"], y=b["nav"], name="基线四因子", line=dict(color=C_BASE, width=2)), 1, 1)
    f1.add_trace(go.Scatter(x=c["date"], y=c["nav"], name="六因子(方案B)", line=dict(color=C_6F, width=2)), 1, 1)
    g = dec.set_index("signal_date")["gap_log"].cumsum()
    f1.add_trace(go.Scatter(x=g.index, y=g.values, name="累计差距 log(6F)−log(基线)",
                            line=dict(color=C_NEG, width=2)), 2, 1)
    f1.update_layout(height=470, title="图1 · 净值与累计差距（共同区间 ≥2017-05-12）", **LAY)
    f1.update_yaxes(title_text="净值", row=1, col=1)
    f1.update_yaxes(title_text="累计 log 差距", row=2, col=1)
    figs.append(f1.to_html(full_html=False, include_plotlyjs=True))

    # 图2 逐日分解（周聚合）累计贡献
    f2 = go.Figure()
    for nm, col, color in (("共同持仓权重差", "c_common", C_BASE), ("六因子独有票", "c_only6", C_6F),
                           ("−基线独有票", "c_onlyb", C_NEG)):
        s = dec.set_index("signal_date")[col].cumsum()
        f2.add_trace(go.Scatter(x=s.index, y=s.values, name=nm, line=dict(color=color, width=2)))
    s = dec.set_index("signal_date")["fee"].cumsum()
    f2.add_trace(go.Scatter(x=s.index, y=s.values, name="费用差", line=dict(color=MUTED, width=2, dash="dot")))
    s = dec.set_index("signal_date")["gap_log"].cumsum()
    f2.add_trace(go.Scatter(x=s.index, y=s.values, name="实际累计差距",
                            line=dict(color=INK, width=1.5, dash="dash")))
    f2.update_layout(height=430, **LAY,
                     title="图2 · 差距从哪里来：逐日分解（周聚合）的累计贡献（净值 log 点，raw 收-收口径）")
    f2.update_yaxes(title_text="累计贡献（log 点）")
    figs.append(f2.to_html(full_html=False, include_plotlyjs=False))

    # 图3 边际票当周收益分布（箱线，两只）
    if len(q):
        f3 = go.Figure()
        for side, color, nm in (("base", C_BASE, "基线独有票"), ("6F", C_6F, "六因子独有票")):
            g = q[q["side"] == side]["ret"].clip(-0.25, 0.25)
            f3.add_trace(go.Box(x=g, name=nm, marker_color=color, orientation="h",
                                boxpoints="outliers", pointpos=-1.5))
        f3.update_layout(height=330, **NOL,
                         title="图3 · 边际票（满仓周只被一版持有）的当周收益分布（raw 收-收，截尾 ±25%）")
        f3.update_xaxes(title_text="当周收益", tickformat=".0%")
        figs.append(f3.to_html(full_html=False, include_plotlyjs=False))

    # 图4 行业归因（发散条形）
    if len(by_ind):
        sel = pd.concat([by_ind.head(10), by_ind.tail(10)]).sort_values()
        f4 = go.Figure(go.Bar(x=sel.values, y=sel.index.astype(str), orientation="h",
                              marker_color=[C_POS if v > 0 else C_NEG for v in sel.values]))
        f4.update_layout(height=540, **NOL,
                         title="图4 · 行业归因：Σ(权重×当周收益)，六因子独有 − 基线独有（蓝=六因子更好）")
        f4.update_xaxes(title_text="累计贡献（净值 log 点）")
        figs.append(f4.to_html(full_html=False, include_plotlyjs=False))

    # 图5 regime 分组
    regs = ["momentum", "reversal"]
    zh = {"momentum": "动量周(T′<0)", "reversal": "反转周(T′≥0)"}
    qm = q[q["side"] != "both"] if len(q) else pd.DataFrame()
    diff_reg, gap_reg = [], []
    for r in regs:
        g = qm[qm["regime"] == r]
        diff_reg.append(g[g["side"] == "6F"]["ret"].mean() - g[g["side"] == "base"]["ret"].mean()
                        if len(g) else np.nan)
        gap_reg.append(dec[dec["regime"] == r]["gap_log"].sum())
    f5 = go.Figure(go.Bar(x=[zh[r] for r in regs], y=diff_reg, marker_color=C_6F))
    f5.update_layout(height=300, **NOL, title="图5a · regime 分组：边际票当周收益均值差（6F−基线）")
    f5.update_yaxes(tickformat=".1%")
    figs.append(f5.to_html(full_html=False, include_plotlyjs=False))
    f5b = go.Figure(go.Bar(x=[zh[r] for r in regs], y=gap_reg,
                           marker_color=[C_POS if v > 0 else C_NEG for v in gap_reg]))
    f5b.update_layout(height=300, **NOL, title="图5b · regime 分组：累计净值差距（log 点，负=六因子落后）")
    figs.append(f5b.to_html(full_html=False, include_plotlyjs=False))

    # 图6 头部检验：名次分桶
    if len(bk):
        piv = bk.groupby(["bucket", "score"])["fwd"].mean().unstack()
        piv = piv.reindex(["1-2", "3-6", "7-12", "13-30", ">30"])
        f6 = go.Figure()
        f6.add_trace(go.Scatter(x=piv.index, y=piv["4F"], name="四因子打分", mode="lines+markers",
                                line=dict(color=C_BASE, width=2), marker=dict(size=8)))
        f6.add_trace(go.Scatter(x=piv.index, y=piv["6F"], name="六因子打分", mode="lines+markers",
                                line=dict(color=C_6F, width=2), marker=dict(size=8)))
        f6.update_layout(height=350, **LAY,
                         title="图6 · 头部检验：行业内名次分桶的平均下周收益（hfq 口径，两套打分各排各的）")
        f6.update_yaxes(tickformat=".2%", title_text="平均下周收益")
        f6.update_xaxes(title_text="行业内名次桶")
        figs.append(f6.to_html(full_html=False, include_plotlyjs=False))

    # 图7 因子画像（行业内 rank_pct 中位数）
    if len(prof):
        f7 = go.Figure()
        for side, color, nm in (("base", C_BASE, "基线独有票"), ("6F", C_6F, "六因子独有票")):
            if side in prof:
                f7.add_trace(go.Bar(y=prof.index, x=prof[side], name=nm, orientation="h",
                                    marker_color=color))
        f7.update_layout(height=430, barmode="group", **LAY,
                         title="图7 · 边际票画像：行业内 rank_pct 中位数（0.5=行业中位；越高=该维度越强）")
        f7.update_xaxes(title_text="行业内分位中位数", tickformat=".2f")
        figs.append(f7.to_html(full_html=False, include_plotlyjs=False))

    # ── 统计卡与合计表 ──
    tot = dec[["gap_log", "c_common", "c_only6", "c_onlyb", "fee", "residual"]].sum()
    m6q = q[q["side"] == "6F"]["ret"] if len(q) else pd.Series(dtype=float)
    mbq = q[q["side"] == "base"]["ret"] if len(q) else pd.Series(dtype=float)
    ht3 = ht[ht["selected"]] if len(ht) else pd.DataFrame()
    diff3 = ht3[ht3["differ"]] if len(ht3) else pd.DataFrame()
    icm = ic.groupby(["scope", "score"])["ic"].mean() if len(ic) else pd.Series(dtype=float)

    def tile(k, v, s):
        return (f"<div class='tile'><div class='k'>{k}</div><div class='v'>{v}</div>"
                f"<div class='s'>{s}</div></div>")

    tiles = ("<div style='display:flex;gap:12px;flex-wrap:wrap;margin:16px 0'>"
             + tile("共同区间净值", "6F 3.173x vs 基线 3.600x", "−11.9%（strategy_004 口径）")
             + tile("周持仓重叠", f"Jaccard {np.mean(jac):.2f}（满仓周 {np.mean(jac_full):.2f}）",
                    "周均同票≈1.6/6 —— 换因子≈换整本书")
             + tile("6F独有票 当周均值", f"{m6q.mean():+.2%}",
                    f"n={len(m6q)} 只·周，胜率 {(m6q > 0).mean():.0%}" if len(m6q) else "n=0")
             + tile("基线独有票 当周均值", f"{mbq.mean():+.2%}",
                    f"n={len(mbq)} 只·周，胜率 {(mbq > 0).mean():.0%}" if len(mbq) else "n=0")
             + tile("top3行业·头部检验",
                    f"6F {ht3['r_top2_6'].mean():+.2%} vs 4F {ht3['r_top2_4'].mean():+.2%}" if len(ht3) else "n/a",
                    f"6F 胜率 {(diff3['r_top2_6'] > diff3['r_top2_4']).mean():.0%}"
                    f"（top2 不同的 {len(diff3)} 行业周）" if len(diff3) else "")
             + tile("IC：池化 vs 行业内",
                    f"池化 {icm.get(('pooled','4F'),np.nan):.3f}→{icm.get(('pooled','6F'),np.nan):.3f}；"
                    f"行业内 {icm.get(('within','4F'),np.nan):.3f}→{icm.get(('within','6F'),np.nan):.3f}",
                    "两种粒度 IC 都升、头部却变差 → 增量信息在中段")
             + "</div>")

    parts_html = "".join(f"<div class='fig'>{f}</div>" for f in figs)
    css = f"""
    <style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      h2 {{ color:{INK}; }} h3 {{ color:{INK2}; border-bottom:1px solid {GRID}; padding-bottom:6px; }}
      .tile {{ border:1px solid {GRID}; border-radius:8px; padding:12px 16px; min-width:190px; background:#fff; }}
      .tile .k {{ color:{MUTED}; font-size:12px; }}
      .tile .v {{ color:{INK}; font-size:18px; font-weight:600; margin:4px 0; }}
      .tile .s {{ color:{INK2}; font-size:12px; }}
      .fig {{ margin:8px 0 28px 0; }}
      table {{ border-collapse:collapse; font-size:12.5px; color:{INK2}; }}
      td,th {{ border:1px solid {GRID}; padding:4px 10px; text-align:right; }}
      th {{ color:{INK}; background:#fff; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_008 — 六因子为何输给四因子基线（交易记录 × 行业轮动归因）</h2>"
            f"{tiles}"
            f"<h3>图1 净值与差距 · 图2 差距分解 · 图3 边际票分布 · 图4 行业归因 · "
            f"图5 regime · 图6 头部检验 · 图7 边际票画像</h3>"
            f"{parts_html}"
            f"<h3>分解合计（净值 log 点，共同区间；残差=逐日线性近似与逐日复利之差+停牌缺口）</h3>"
            f"<table><tr><th></th><th>共同权重差</th><th>6F独有</th><th>−基线独有</th>"
            f"<th>费用差</th><th>残差</th><th>合计=Σgap_log</th></tr>"
            f"<tr><td>累计</td><td>{tot['c_common']:+.3f}</td><td>{tot['c_only6']:+.3f}</td>"
            f"<td>−{tot['c_onlyb']:.3f}</td><td>{tot['fee']:+.3f}</td>"
            f"<td>{tot['residual']:+.3f}</td><td>{tot['gap_log']:+.3f}</td></tr></table>"
            f"</body></html>")


if __name__ == "__main__":
    main()
