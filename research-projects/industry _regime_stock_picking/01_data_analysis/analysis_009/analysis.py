"""analysis_009 — 动量周失败 ↔ 行业拥挤度假说检验（广发技术篇拥挤度因子的本地化）。

**假说链**（用户 2026-10-15 提出，承 analysis_008 + 广发《考虑拥挤度的细分行业动量策略》提取件）：
  基线（变盘指数行业轮动）在动量周（T′<0，行业层选 mom_240 前 3）表现差，
  可能因为**动量行业已拥挤**（涨过头、资金切换快）→
  若成立，可在行业层加「拥挤度闸门」（动量行业触发拥挤 → 空仓/顺延），恢复
  「主线稳定用动量、不稳定用反转」的原本意图。

**五步检验**：
  A. 动量行业是否更拥挤 —— weekly_plan 动量周 top3 vs 反转周 top3 vs 全行业的信号数分布
  B. 拥挤 → 下周行业收益 —— 全行业分组 + 动量 top3 内部条件分组（广发结论的周频 L1 版）
  C. 基线动量周失败归因 —— 基线实际周收益（nav）按 regime × 拥挤度分组：亏的动量周是否=拥挤的周
  D. 闸门模拟（★nav 级理想化上界，只作方向参考）—— 动量周 top3 拥挤 → 该周按 0 收益（空仓）计；
     对比原始基线；反转周同规则对照（预期无益或有害）
  E. 参数敏感性 —— 回看窗口 W ∈ {52,104,156}

**拥挤度因子（广发口径本地化，全部只用 ≤t 数据）**：
  行业周度量（申万 L1，由 stock_bar1d × stock_industry_component_daily 逐日成分聚合）：
    vol = Σ 成分股周成交量；amt = Σ 成分股周成交额；turn = 成分股日换手率(>0)中位数的周均值
  6 个因子 = {vol, amt, turn, vol_bias, amt_bias, turn_bias} 各自的**过去 W 周(含当周)滚动百分位**
    bias = 近 4 周均值 / 近 52 周均值 − 1（「月度乖离率」的周频版；广发原文公式未明确，此为本地定义）
  触发 = 百分位 ≥ 60（广发：越敏感越好，60 优于 70/80/90）；signal_count = 6 个因子中触发数(0..6)

  ⚠ 与广发原文的口径差：他们是申万二级(102 个)·月频·官方指数量能；我们是 L1(31 个)·周频·
    成分聚合量能。本分析在**我们自己的口径**上重验效应是否存在。

数据全部本地（零云端、零回测重跑）：
  shared/_cache/{weekly_plan,industry_index}.parquet + 基线 nav_from_trades
  仓库 stock_industry_sw_bar1d（行业指数收盘）+ stock_bar1d × stock_industry_component_daily

用法：python analysis.py
产物：crowding_panel.csv / gate_grid.csv / result_view.html（records.md 手写）
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
REPO = PROJ.parents[1]
WAREHOUSE = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
CACHE = SHARED / "_cache"
BL = PROJ / "02_strategy_iteration/strategy_004/backtest_strategy_baseline/backtest_logs"
CUT = pd.Timestamp("2017-05-12")

W_MAIN = 104            # 滚动百分位回看窗口（周）
PCT_THR = 0.60          # 触发百分位阈值（广发最优口径）
BIAS_SHORT, BIAS_LONG = 4, 52
F6 = ["vol", "amt", "turn", "vol_bias", "amt_bias", "turn_bias"]

# 视图配色（dataviz 校验通过）
C_BASE, C_6F = "#2a78d6", "#eb6834"
C_POS, C_NEG = "#2a78d6", "#e34948"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


def build_industry_weekly(sig_dates: list) -> pd.DataFrame:
    """信号周行业面板：每周每 L1 行业的 vol/amt/turn（成分聚合）。

    周归属与策略一致：每个交易日归到「下一个信号日」的周（信号日本身属于本周），
    即信号日 t 的周度量 = (上一个信号日, t] 的日度聚合。
    """
    import duckdb
    sig_list = ",".join(f"DATE '{pd.Timestamp(d).date()}'" for d in sig_dates)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    mkt = con.execute(f"""
        WITH sig AS (SELECT unnest([{sig_list}]) AS s),
        d AS (SELECT DISTINCT date FROM stock_industry_sw_bar1d),
        wk AS (SELECT d.date, (SELECT min(sig.s) FROM sig WHERE sig.s >= d.date) AS week_end
               FROM d WHERE d.date <= (SELECT max(s) FROM sig)),
        daily AS (
            SELECT b.date, cd.industry_level1_name AS ind,
                   SUM(b.volume) AS vol, SUM(b.amount) AS amt,
                   median(b.turn) FILTER (WHERE b.turn > 0) AS med_turn
            FROM stock_bar1d b
            JOIN stock_industry_component_daily cd USING (date, instrument)
            JOIN wk ON wk.date = b.date
            WHERE b.volume IS NOT NULL AND cd.industry_level1_name IS NOT NULL
            GROUP BY 1, 2)
        SELECT wk.week_end AS week, daily.ind,
               SUM(daily.vol) AS vol, SUM(daily.amt) AS amt, AVG(daily.med_turn) AS turn
        FROM daily JOIN wk ON wk.date = daily.date
        GROUP BY 1, 2
    """).df()
    con.close()
    return mkt


def add_crowding(base: pd.DataFrame, w: int = W_MAIN) -> pd.DataFrame:
    """行业周面板 + 6 个拥挤因子（滚动百分位）+ signal_count。"""
    m = base.sort_values(["ind", "week"]).copy()
    g = m.groupby("ind")
    for c in ("vol", "amt", "turn"):
        m[f"{c}_bias"] = g[c].transform(lambda s: s.rolling(BIAS_SHORT).mean()
                                        / s.rolling(BIAS_LONG).mean() - 1)
    for c in F6:
        m[f"{c}_pct"] = g[c].transform(
            lambda s: s.rolling(w, min_periods=w // 2).apply(
                lambda a: (a[-1] >= a).mean(), raw=True))
    m["signal_count"] = (m[[f"{c}_pct" for c in F6]] >= PCT_THR).sum(axis=1)
    return m


def industry_close_weekly(sig_dates: list) -> pd.DataFrame:
    """行业指数收盘在信号日上的宽表（前瞻收益用）。"""
    import duckdb
    sig_list = ",".join(f"DATE '{pd.Timestamp(d).date()}'" for d in sig_dates)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    px = con.execute(f"""
        SELECT b.date AS week, m.name AS ind, b.close
        FROM stock_industry_sw_bar1d b JOIN sw_industry_map m ON b.instrument = m.sw_code
        WHERE b.date IN ({sig_list})
    """).df()
    con.close()
    px["week"] = pd.to_datetime(px["week"])
    w = px.pivot(index="week", columns="ind", values="close").sort_index()
    w.index.name = "week"
    return w


def top3_crowding(mkt_key, wp: pd.DataFrame) -> pd.DataFrame:
    """每周 top3 行业的 signal_count（mean/max）——用 weekly_plan 的 top3（策略真实选择）。"""
    rows = []
    for _, r in wp.iterrows():
        wk = r["signal_date"]
        sc = [mkt_key.at[(wk, p), "signal_count"] if (wk, p) in mkt_key.index else np.nan
              for p in r["top3"].split(",")]
        rows.append({"signal_date": wk, "regime": r["regime"],
                     "top3_sc_mean": np.nanmean(sc) if np.isfinite(np.nanmax(sc)) else np.nan,
                     "top3_sc_max": np.nanmax(sc) if np.isfinite(np.nanmax(sc)) else np.nan})
    return pd.DataFrame(rows)


def main():
    print("[1/6] weekly_plan / 基线 nav / top3 复刻自检 …")
    wp = pd.read_parquet(CACHE / "weekly_plan.parquet")
    for c in ("signal_date", "exec_date"):
        wp[c] = pd.to_datetime(wp[c])
    nav = pd.read_csv(BL / "nav_from_trades.csv"); nav["date"] = pd.to_datetime(nav["date"])
    ii = pd.read_parquet(CACHE / "industry_index.parquet")
    ii["date"] = pd.to_datetime(ii["date"])
    # 复刻 pick_industries 自检（mom_240 前3 / mom_60 后3）——只用 weekly_plan 的 top3 做正式计算
    ii_s = ii[ii["date"].isin(set(wp["signal_date"]))]
    ok = []
    for _, r in wp.iterrows():
        day = ii_s[ii_s["date"] == r["signal_date"]]
        col = "mom_240" if r["regime"] == "momentum" else "mom_60"
        d2 = day.dropna(subset=[col])
        pick = (d2.nlargest(3, col) if r["regime"] == "momentum" else d2.nsmallest(3, col))["ind_name"].tolist()
        ok.append(set(pick) == set(r["top3"].split(",")))
    print(f"    top3 复刻一致率 {np.mean(ok):.1%}（<100% 则口径漂移，须停下检查）")

    print("[2/6] 行业周度量面板（成分聚合，duckdb）…")
    sig_dates = sorted(wp["signal_date"].unique())
    mkt0 = build_industry_weekly(sig_dates)
    print(f"    {mkt0.shape[0]} 行 / {mkt0['ind'].nunique()} 行业 / {mkt0['week'].nunique()} 周")

    print("[3/6] 拥挤因子（滚动百分位）+ 前瞻收益 …")
    mkt = add_crowding(mkt0)
    pxw = industry_close_weekly(sig_dates)
    fwd = pxw.pct_change(fill_method="pad").shift(-1)   # week w 收盘 → week w+1 收盘 − 1
    mkt["fwd"] = [fwd.at[w, i] if (w in fwd.index and i in fwd.columns) else np.nan
                  for w, i in zip(mkt["week"], mkt["ind"])]
    mkt.to_csv(HERE / "crowding_panel.csv", index=False, encoding="utf-8-sig")

    # ── A. 动量行业是否更拥挤 ──
    print("[4/6] A. 动量 top3 vs 反转 top3 vs 全行业 拥挤度 …")
    mkt_key = mkt.set_index(["week", "ind"])
    pl = top3_crowding(mkt_key, wp)
    all_sc = mkt.groupby("week")["signal_count"].mean().rename("all_mean")
    pl = pl.merge(all_sc, left_on="signal_date", right_index=True)
    for rg, g in pl.groupby("regime"):
        print(f"    {rg} 周 {len(g)}：top3 平均信号数 {g['top3_sc_mean'].mean():.2f} "
              f"（全行业 {g['all_mean'].mean():.2f}；top3 最大值 {g['top3_sc_max'].mean():.2f}）")
    mg = pl[pl["regime"] == "momentum"]
    rg_ = pl[pl["regime"] == "reversal"]
    t_mom = mg["top3_sc_mean"].sub(mg["all_mean"]).dropna()
    t_rev = rg_["top3_sc_mean"].sub(rg_["all_mean"]).dropna()
    print(f"    top3−全行业 信号差：动量周 {t_mom.mean():+.2f}（t {t_mom.mean()/(t_mom.std()/np.sqrt(len(t_mom))):.1f}）"
          f" vs 反转周 {t_rev.mean():+.2f}（t {t_rev.mean()/(t_rev.std()/np.sqrt(len(t_rev))):.1f}）")

    # ── B. 拥挤 → 下周行业收益 ──
    print("[5/6] B. 拥挤度对下周行业收益的预测力 …")
    ev = mkt.dropna(subset=["fwd", "signal_count"]).copy()
    ev = ev[ev["week"] >= CUT]
    bins = pd.cut(ev["signal_count"], [-1, 1, 3, 6], labels=["0-1 信号", "2-3 信号", "4-6 信号"])
    tab = ev.groupby(bins, observed=False)["fwd"].agg(["mean", "count"])
    print("    全行业 下周收益 分组（bp/周）：")
    print(tab.assign(mean=lambda d: (d["mean"] * 1e4).round(1)).to_string())

    def _ic(gdf):
        return gdf["signal_count"].corr(gdf["fwd"], method="spearman") if len(gdf) >= 10 else np.nan
    ic = ev.groupby("week")[["signal_count", "fwd"]].apply(_ic).dropna()
    print(f"    周内 Spearman(signal_count, fwd) 均值 {ic.mean():+.4f}（n={len(ic)} 周）")
    # 动量 top3 内部
    top3_of = {r["signal_date"]: set(r["top3"].split(",")) for _, r in wp.iterrows()}
    e3 = ev[ev.apply(lambda r: r["ind"] in top3_of.get(r["week"], set()) and
                     wp.set_index("signal_date").at[r["week"], "regime"] == "momentum", axis=1)]
    hi = e3[e3["signal_count"] >= 3]["fwd"]; lo = e3[e3["signal_count"] < 3]["fwd"]
    print(f"    动量 top3 内部：信号≥3 下周 {hi.mean():+.3%}（n={len(hi)}） vs <3 {lo.mean():+.3%}（n={len(lo)}）")

    # ── C. 基线周收益 × 拥挤 + D. 闸门模拟 ──
    print("[6/6] C/D. 基线周收益 × 拥挤度分组 + 闸门模拟（nav 级理想化） …")
    navi = nav.set_index("date")["nav"]
    execs = wp.loc[wp["exec_date"] > CUT].reset_index(drop=True)
    pli = pl.set_index("signal_date")
    wrows = []
    for i in range(len(execs) - 1):
        e, en = execs.iloc[i]["exec_date"], execs.iloc[i + 1]["exec_date"]
        sd = execs.iloc[i]["signal_date"]
        if e not in navi.index or en not in navi.index or sd not in pli.index:
            continue
        wrows.append({"signal_date": sd, "regime": execs.iloc[i]["regime"],
                      "r": navi.at[en] / navi.at[e] - 1,
                      "sc_mean": pli.at[sd, "top3_sc_mean"], "sc_max": pli.at[sd, "top3_sc_max"]})
    Wc = pd.DataFrame(wrows)
    for rg, g in Wc.groupby("regime"):
        hi_ = g[g["sc_mean"] >= 2]["r"]; lo_ = g[g["sc_mean"] < 2]["r"]
        print(f"    [{rg}] 基线周收益：top3 拥挤(均信号≥2) {hi_.mean():+.3%}（n={len(hi_)}）"
              f" vs 不拥挤 {lo_.mean():+.3%}（n={len(lo_)}）")

    # D. 闸门网格：j=1 任一行业(sc_max)≥m；j=2 平均(sc_mean)≥m；j=3 两者同时
    def stats(r):
        nav_ = float((1 + r).prod())
        sd_ = r.std(ddof=1)
        n_yr = len(r) / 52
        return (nav_, nav_ ** (1 / n_yr) - 1, r.mean() / sd_ * np.sqrt(52) if sd_ > 0 else np.nan)

    gate_rows = []
    b_nav, b_ann, b_sh = stats(Wc["r"])
    gate_rows.append({"rule": "无闸门(基线)", "nav": b_nav, "ann": b_ann, "sharpe": b_sh,
                      "n_gated": 0, "gated_mean_ret": np.nan})
    conds = {"j1": Wc["sc_max"], "j2": Wc["sc_mean"], "j3": pd.concat([Wc["sc_max"], Wc["sc_mean"]], axis=1).min(axis=1)}
    for rg in ("momentum", "reversal"):
        isr = Wc["regime"] == rg
        for jn, scv in conds.items():
            for m in (2, 3, 4):
                mask = isr & (scv >= m)
                r2 = Wc["r"].where(~mask, 0.0)
                nav_, ann_, sh_ = stats(r2)
                gate_rows.append({"rule": f"{rg[:3]}·{jn}·m≥{m}", "nav": nav_, "ann": ann_,
                                  "sharpe": sh_, "n_gated": int(mask.sum()),
                                  "gated_mean_ret": Wc.loc[mask, "r"].mean() if mask.any() else np.nan})
    gg = pd.DataFrame(gate_rows)
    gg.to_csv(HERE / "gate_grid.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print("    闸门网格（nav 级理想化；被关周均收益越负、净值越高于基线越好）：")
    print(gg.round(4).to_string(index=False))

    # ── E. 回看窗口敏感性 ──
    print("[E] 回看窗口敏感性（52/104/156）…")
    for w_ in (52, 104, 156):
        m2 = add_crowding(mkt0, w=w_).set_index(["week", "ind"])
        sc_mean = {}
        for _, r in wp.iterrows():
            wk = r["signal_date"]
            vals = [m2.at[(wk, p), "signal_count"] if (wk, p) in m2.index else np.nan
                    for p in r["top3"].split(",")]
            sc_mean[wk] = np.nanmean(vals) if np.any(np.isfinite(vals)) else np.nan
        W2 = Wc.copy(); W2["sc_mean"] = W2["signal_date"].map(sc_mean)
        g = W2[(W2["regime"] == "momentum") & W2["sc_mean"].notna()]
        hi_, lo_ = g[g["sc_mean"] >= 2]["r"], g[g["sc_mean"] < 2]["r"]
        print(f"    W={w_}：动量周拥挤 {hi_.mean():+.3%}(n={len(hi_)}) vs 不拥挤 {lo_.mean():+.3%}(n={len(lo_)}) "
              f"差 {(hi_.mean() - lo_.mean()) * 1e2:+.2f}pp")

    # ── F. 开仓前期 vs 后期（用户追问：动量亏损周在 streak 前段还是后段）──
    print("[F] 满仓持续位置（streak）：亏损在开仓前期还是后期 …")
    streak = {}
    run = 0
    for _, r in wp.sort_values("signal_date").iterrows():
        run = run + 1 if r["exposure"] == 1.0 else 0
        streak[r["signal_date"]] = run
    Wf = Wc.copy()
    Wf["streak"] = Wf["signal_date"].map(streak)
    Wf = Wf[Wf["streak"] >= 1]                       # 只看满仓周
    Wf["pos"] = np.where(Wf["streak"] == 1, "第1周(刚开仓)",
                 np.where(Wf["streak"] == 2, "第2周", "第3周+"))
    for rg in ("momentum", "reversal"):
        g = Wf[Wf["regime"] == rg]
        line = [f"{p}: {v['r'].mean():+.3%}(n={len(v)})"
                for p, v in g.groupby("pos") if len(v)]
        print(f"    [{rg} 满仓周] " + " ｜ ".join(line))
    # 交叉：动量第1周 × 拥挤
    g1 = Wf[(Wf["regime"] == "momentum") & (Wf["streak"] == 1)]
    for lab, m_ in (("不拥挤(sc<2)", g1["sc_mean"] < 2), ("拥挤(sc≥2)", g1["sc_mean"] >= 2)):
        v = g1[m_]["r"]
        print(f"    动量·刚开仓·{lab}：{v.mean():+.3%}（n={len(v)}）")

    html = build_view(pl, ev, e3, Wc, gg, Wf)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("完成。")


# ══════════════════════════════ 视图 ══════════════════════════════
def build_view(pl, ev, e3, Wc, gg, Wf=None):
    import plotly.graph_objects as go

    LAY = dict(font=dict(family="Arial,'Microsoft YaHei',sans-serif", color=INK2, size=13),
               paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
               xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               hovermode="x unified", margin=dict(l=56, r=24, t=56, b=44), showlegend=True)
    NOL = {k: v for k, v in LAY.items() if k != "showlegend"} | {"showlegend": False}
    figs = []

    # 图1 top3 拥挤度时序
    f1 = go.Figure()
    pl_s = pl.sort_values("signal_date")
    f1.add_trace(go.Scatter(x=pl_s["signal_date"], y=pl_s["top3_sc_mean"], name="top3 行业平均信号数",
                            line=dict(color=C_6F, width=1.6), mode="lines"))
    f1.add_trace(go.Scatter(x=pl_s["signal_date"], y=pl_s["all_mean"], name="全行业平均",
                            line=dict(color=MUTED, width=1.6), mode="lines"))
    mr = pl_s[pl_s["regime"] == "momentum"]
    f1.add_trace(go.Scatter(x=mr["signal_date"], y=mr["top3_sc_mean"], name="动量周 top3",
                            mode="markers", marker=dict(color=C_POS, size=5), opacity=0.6))
    f1.update_layout(height=380, **LAY, title="图1 · 行业拥挤度时序（0-6 个信号；蓝点=动量周）")
    f1.update_yaxes(title_text="signal_count")
    figs.append(f1.to_html(full_html=False, include_plotlyjs=True))

    # 图2 分组下周收益
    f2 = go.Figure()
    b_all = pd.cut(ev["signal_count"], [-1, 1, 3, 6], labels=["0-1", "2-3", "4-6"])
    grp = ev.groupby(b_all, observed=False)["fwd"].mean() * 100
    f2.add_trace(go.Bar(x=["0-1", "2-3", "4-6"], y=grp.values, name="全行业", marker_color=C_BASE))
    b3 = pd.cut(e3["signal_count"], [-1, 1, 3, 6], labels=["0-1", "2-3", "4-6"])
    grp3 = e3.groupby(b3, observed=False)["fwd"].mean() * 100
    f2.add_trace(go.Bar(x=["0-1", "2-3", "4-6"], y=grp3.values, name="动量top3内", marker_color=C_6F))
    f2.update_layout(height=360, barmode="group", **LAY,
                     title="图2 · 拥挤分组 → 下周行业收益（%，周频·共同区间）")
    f2.update_yaxes(title_text="下周收益(%)")
    figs.append(f2.to_html(full_html=False, include_plotlyjs=False))

    # 图3 基线周收益箱线
    f3 = go.Figure()
    Wc = Wc.copy()
    Wc["grp"] = Wc["regime"] + "_" + np.where(Wc["sc_mean"] >= 2, "crowded", "clean")
    lbl = {"momentum_crowded": "动量周·拥挤", "momentum_clean": "动量周·不拥挤",
           "reversal_crowded": "反转周·拥挤", "reversal_clean": "反转周·不拥挤"}
    for k in ("momentum_crowded", "momentum_clean", "reversal_crowded", "reversal_clean"):
        g = Wc[Wc["grp"] == k]["r"].clip(-0.15, 0.15)
        if len(g) == 0:
            continue
        f3.add_trace(go.Box(y=g.values, name=f"{lbl[k]}(n={len(g)})", marker_color=C_NEG if "crowded" in k else C_POS,
                            boxpoints="outliers", pointpos=-1.5))
    f3.update_layout(height=400, **NOL, title="图3 · 基线实际周收益（nav）× regime × 拥挤（截尾±15%）")
    f3.update_yaxes(tickformat=".1%")
    figs.append(f3.to_html(full_html=False, include_plotlyjs=False))

    # 图4 闸门网格
    f4 = go.Figure()
    base = gg[gg["rule"].str.startswith("无")]["nav"].iloc[0]
    colors = [MUTED if r.startswith("无") else (C_POS if v >= base else C_NEG)
              for r, v in zip(gg["rule"], gg["nav"])]
    f4.add_trace(go.Bar(x=gg["rule"], y=gg["nav"], marker_color=colors))
    f4.update_layout(height=420, **NOL,
                     title=f"图4 · 拥挤闸门网格（nav 级理想化；基线 {base:.3f}x，蓝=更优）")
    f4.update_yaxes(title_text="累计净值（周收益连乘）")
    figs.append(f4.to_html(full_html=False, include_plotlyjs=False))

    # 图5 满仓持续位置（streak）
    if Wf is not None and len(Wf):
        f5 = go.Figure()
        order = ["第1周(刚开仓)", "第2周", "第3周+"]
        for rg, color in (("momentum", C_6F), ("reversal", C_BASE)):
            g = Wf[Wf["regime"] == rg]
            grp = g.groupby("pos")["r"].mean().reindex(order)
            ns = g.groupby("pos")["r"].count().reindex(order)
            f5.add_trace(go.Bar(x=order, y=grp.values * 100,
                                name={"momentum": "动量周", "reversal": "反转周"}[rg],
                                marker_color=color,
                                customdata=ns.values,
                                hovertemplate="%{x}: %{y:.3f}%/周 (n=%{customdata})<extra>%{fullData.name}</extra>"))
        f5.update_layout(height=340, barmode="group", **LAY,
                         title="图5 · 满仓持续位置 → 基线周均收益（%，只统计满仓周）")
        f5.update_yaxes(title_text="周均收益(%)")
        figs.append(f5.to_html(full_html=False, include_plotlyjs=False))

    parts = "".join(f"<div class='fig'>{f}</div>" for f in figs)
    css = f"""
    <style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      h2 {{ color:{INK}; }}
      .fig {{ margin:8px 0 28px 0; }}
      div.warn {{ border-left:4px solid {C_NEG}; background:#fff; padding:10px 14px; color:{INK2}; font-size:13px; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_009 — 动量周失败 ↔ 行业拥挤度（假说检验）</h2>"
            f"<div class='warn'>图4 为 <b>nav 级理想化上界</b>（无成本/无部分平仓/空仓按 0 收益计），"
            f"只用于判断方向；正式检验须进 strategy 引擎回测，并过 analysis_004 随机门槛。</div>"
            f"{parts}</body></html>")


if __name__ == "__main__":
    main()
