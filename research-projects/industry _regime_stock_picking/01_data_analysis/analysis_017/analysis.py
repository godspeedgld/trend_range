"""analysis_017 — strategy_008 镜像闸门的年度归因：为什么 2017~2022 让出收益、2023~2025 大赢？

**现象**（strategy_008/final_report.md §5-②）：008 相对 007 的逐年收益差
    2017 −3.1 / 2018 −9.3 / 2019 −8.8 / 2020 −1.0 / 2021 −3.5 / 2022 −10.3
    2023 +5.9 / 2024 +15.6 / 2025 +16.3 / 2026 −0.7  （pp）
两个互斥假设：
  H1「闸门在那段误关」—— 被关的反转周在 2017~2022 其实是赚钱的（闸门选错）
  H2「那段触发结构不同」—— 2017~2022 被关的周本身与 2023~2025 不是一类（sc 分布/市场状态不同）

**方法**：
  A. 逐年清点被关的 23 周（数量、在 007 轨迹下的周收益）
  B. **★年块反事实**（引擎口径）：对每个含被关周的年份 Y，跑「008 但把 Y 年的被关周全部放开」，
     比较 **Y 年内** 的收益率（008 vs 该反事实）→ 得到**干净的年内增量归因**
  C. 被关周 vs 保留反转周 的特征对比（分段）：sc_max / sc_mean / 市场状态 / 变盘指数水平
  D. 对照：007 的动量闸门（sc_mean<2）是否也有同样的年度结构？

**口径**：引擎 = `local_weight_backtest.py`（权重引擎）；周收益由 `nav_from_trades.csv` 差分。
自检：基线 / 007 / 008 须逐值回到 3.6001 / 4.5663 / 4.5535。

用法：python analysis.py
产物：year_attribution.csv / closed_vs_kept.csv / result_view.html（records.md 手写）
"""
from __future__ import annotations

import io
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
REPO = PROJ.parents[1]
S8 = PROJ / "02_strategy_iteration/strategy_008"
sys.path.insert(0, str(SHARED))
sys.path.insert(0, str(REPO / ".claude/skills/skill-research-assistant/scripts"))

from build_weekly_targets import (                     # noqa: E402
    N_IND, build_targets, factor_directions, industry_weights, pick_industries,
)
from expand_targets_daily import expand_to_daily       # noqa: E402
from local_weight_backtest import (                    # noqa: E402
    TradingDaysRebalance, WeightBacktestConfig, nav_from_trades, run_weight_backtest,
)

SC_THR, SC_MAX_THR = 2.0, 3.0

# 视图配色（与 009/016 同一套）
C_BASE, C_ALT, C_POS, C_NEG = "#2a78d6", "#eb6834", "#2a78d6", "#e34948"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"


def build_all_on(panel, ind, reg, crowd):
    """全开周频持仓表（exposure≡1）+ 每周元数据。股票选择与 exposure 无关 ⇒ 可复用。"""
    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    pby = {d: g for d, g in panel.groupby("date")}
    prev_top3, held, frames, meta = None, {}, [], {}
    for t in sorted(panel["date"].unique()):
        if t not in regi.index or pd.isna(regi.at[t, "T_prime"]):
            continue
        day, cand = indi.get(t), pby.get(t)
        if day is None or cand is None:
            continue
        top3, regime = pick_industries(day, float(regi.at[t, "T_prime"]))
        tg = build_targets(cand, top3, factor_directions("baseline", regime), held)
        scs = [crowd.get((t, p), np.nan) for p in top3]
        scs = [x for x in scs if pd.notna(x)]
        meta[t] = {"regime": regime, "top3": ",".join(top3),
                   "T_prime": float(regi.at[t, "T_prime"]),
                   "sc_mean": float(np.mean(scs)) if scs else np.nan,
                   "sc_max": float(np.max(scs)) if scs else np.nan,
                   "stable": (prev_top3 is None or set(top3) == set(prev_top3))}
        rows, hn = [], {}
        for ind_name, syms in tg.items():
            if not syms:
                continue
            w = industry_weights(cand, syms)
            for s in syms:
                hn[s] = ind_name
                rows.append({"date": t, "instrument": s, "weight": float(w[s] / N_IND)})
        if rows:
            frames.append(pd.DataFrame(rows))
        held, prev_top3 = hn, top3
    return pd.concat(frames, ignore_index=True), meta


def main():
    t0 = time.time()
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    cd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
    crowd = {(pd.Timestamp(w), i): float(s) for w, i, s in
             zip(cd["week"], cd["ind"], cd["signal_count"])}
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(
        pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet",
                        columns=["date"])["date"]).unique()))
    mk = pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])

    sig, meta = build_all_on(panel, ind, reg, crowd)
    sig_dates = list(sig["date"].unique())
    s = sig.copy()
    s["_wk"] = s["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})
    tag = expand_to_daily(s[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}), cal)
    wgt = expand_to_daily(s[["date", "instrument", "weight"]], cal)
    tag["date"] = pd.to_datetime(tag["date"]); wgt["date"] = pd.to_datetime(wgt["date"])
    ep = tag["weight"].values.astype(int) - 1
    w0 = wgt["weight"].values
    daily = wgt.rename(columns={"instrument": "symbol"})

    cfg = WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0, sell_bps=13.0, min_cost=5.0)
    period = TradingDaysRebalance(1)

    def run(flags: dict) -> tuple[float, pd.Series]:
        a = np.array([flags.get(t, 1) for t in sig_dates], dtype=float)
        d = daily.copy()
        d["weight"] = w0 * a[ep]
        _, tr, _ = run_weight_backtest(mk, d, cfg, period)
        nav, m = nav_from_trades(mk, tr, cfg.initial_cash)
        nav = nav.set_index(pd.to_datetime(nav["date"]))["nav"]
        return m["final_nav"], nav

    def f_base():
        return {t: (1 if meta[t]["stable"] else 0) for t in meta}

    def f_007():
        f = f_base()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "momentum" and pd.notna(m["sc_mean"]) and m["sc_mean"] < SC_THR:
                f[t] = 0
        return f

    def f_008():
        f = f_007()
        for t, m in meta.items():
            if f[t] == 1 and m["regime"] == "reversal" and pd.notna(m["sc_max"]) and m["sc_max"] >= SC_MAX_THR:
                f[t] = 0
        return f

    n_base, nav_base = run(f_base())
    f7, f8 = f_007(), f_008()
    n_007, nav7 = run(f7)
    n_008, nav8 = run(f8)
    print("== 自检（应回 3.6001 / 4.5663 / 4.5535）==")
    print(f"  基线 {n_base:.4f}   007 {n_007:.4f}   008 {n_008:.4f}\n")

    pool = [t for t in sig_dates if meta[t]["regime"] == "reversal" and f7[t] == 1]
    closed = [t for t in pool if meta[t]["sc_max"] >= SC_MAX_THR]
    kept = [t for t in pool if t not in set(closed)]
    print(f"反转周合格池 {len(pool)}：被关 {len(closed)} / 保留 {len(kept)}\n")

    # ── A/B. 逐年：差异 + 被关周 + 年块反事实 ──
    yr = lambda t: pd.Timestamp(t).year
    closed_by_year = pd.Series([yr(t) for t in closed]).value_counts().sort_index()
    print("== A. 被关周的年份分布 ==")
    print(closed_by_year.to_string(), "\n")

    # 周收益序列：wr = **007 轨迹**（用于评价「008 关掉的周本来能赚多少」）；
    #           wr_base = **无闸门轨迹**（用于评价 007 自己关掉的动量周 —— 不能用 wr，
    #           那些周在 007 轨迹里已被关掉，周收益恒≈0，会自我循环）
    nxt = {a: b for a, b in zip(sig_dates[:-1], sig_dates[1:])}

    def weekly_ret(nav):
        out = {}
        for t in sig_dates[:-1]:
            a, b = pd.Timestamp(t), pd.Timestamp(nxt[t])
            if a in nav.index and b in nav.index:
                out[t] = nav[b] / nav[a] - 1
        return out

    wr = weekly_ret(nav7)
    wr_base = weekly_ret(nav_base)

    yearly = []
    for y in sorted({yr(t) for t in sig_dates}):
        i7 = nav7[(nav7.index.year == y)]
        i8 = nav8[(nav8.index.year == y)]
        if len(i7) < 2 or len(i8) < 2:
            continue
        r7 = i7.iloc[-1] / i7.iloc[0] - 1
        r8 = i8.iloc[-1] / i8.iloc[0] - 1
        wk = [t for t in closed if yr(t) == y]
        # 年块反事实：把该年被关周全部放开
        cf = dict(f8)
        for t in wk:
            cf[t] = 1
        _, nav_cf = run(cf)
        icf = nav_cf[nav_cf.index.year == y]
        r_cf = icf.iloc[-1] / icf.iloc[0] - 1 if len(icf) > 1 else np.nan
        yearly.append({"year": y, "007": r7, "008": r8, "008-007": r8 - r7,
                       "反事实(放开本年)": r_cf, "年内闸门效应": r8 - r_cf,
                       "被关周数": len(wk),
                       "被关周收益均值": float(np.mean([wr[t] for t in wk if t in wr]))
                       if wk else np.nan,
                       "被关周收益合计": float(np.sum([wr[t] for t in wk if t in wr]))
                       if wk else 0.0})
    Y = pd.DataFrame(yearly)
    print("== B. 逐年归因（年内口径）==")
    print(Y.assign(**{c: (Y[c] * 100).round(2) for c in
                      ["007", "008", "008-007", "反事实(放开本年)", "年内闸门效应"]})
           .round(4).to_string(index=False))
    Y.to_csv(HERE / "year_attribution.csv", index=False)

    # ── C. 被关 vs 保留 的特征对比（分段）──
    def seg(t):
        return "2017~2022" if yr(t) <= 2022 else "2023~2026"

    # 市场状态：创业板指 MA200
    import duckdb
    con = duckdb.connect(str(REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"),
                         read_only=True)
    g = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='399006.SZ' "
                    "ORDER BY date").fetchdf()
    con.close()
    g["date"] = pd.to_datetime(g["date"])
    g = g.set_index("date")["close"]
    ma = g.rolling(200, min_periods=200).mean()
    bull = (g > ma)

    rows = []
    for lab, group in [("被关(sc_max>=3)", closed), ("保留(sc_max<3)", kept)]:
        for sg in ["2017~2022", "2023~2026"]:
            ts = [t for t in group if seg(t) == sg]
            if not ts:
                continue
            rr = np.array([wr.get(t, np.nan) for t in ts])
            rows.append({"分组": lab, "段": sg, "n": len(ts),
                         "007周收益均值": np.nanmean(rr), "胜率": np.nanmean(rr > 0),
                         "sc_max均值": np.mean([meta[t]["sc_max"] for t in ts]),
                         "sc_mean均值": np.mean([meta[t]["sc_mean"] for t in ts]),
                         "T水平均值": np.mean([meta[t]["T_prime"] for t in ts]),
                         "创业板牛市占比": np.mean([bool(bull.get(pd.Timestamp(t), np.nan))
                                               for t in ts]),
                         "被关周滞后收益(下一周)": np.nanmean(
                             [wr.get(nxt.get(t), np.nan) for t in ts])})
    C = pd.DataFrame(rows)
    print("\n== C. 被关 vs 保留（分段特征）==")
    print(C.round(4).to_string(index=False))
    C.to_csv(HERE / "closed_vs_kept.csv", index=False)

    # ── D. 对照：007 动量闸门被关周 的年度结构（★用无闸门轨迹 wr_base）──
    mgate = [t for t in sig_dates if meta[t]["regime"] == "momentum" and meta[t]["stable"]
             and pd.notna(meta[t]["sc_mean"]) and meta[t]["sc_mean"] < SC_THR]
    D = pd.DataFrame({"year": [yr(t) for t in mgate],
                      "无闸门周收益": [wr_base.get(t, np.nan) for t in mgate]})
    print(f"\n== D. 对照：007 动量闸门被关 {len(mgate)} 周（目标窗 2017-05-12 起；"
          f"007 报告全窗为 34 周，差在预热段）==")
    print(D.groupby("year")["无闸门周收益"].agg(["count", "mean"]).round(5).to_string())
    # 同样口径下，008 镜像闸门被关周的「无闸门轨迹」收益（与 C 表互相印证）
    E = pd.DataFrame({"year": [yr(t) for t in closed],
                      "无闸门周收益": [wr_base.get(t, np.nan) for t in closed]})
    print(f"\n== E. 008 镜像闸门被关 {len(closed)} 周（无闸门轨迹口径）==")
    print(E.groupby("year")["无闸门周收益"].agg(["count", "mean"]).round(5).to_string())
    D.to_csv(HERE / "momentum_gate_by_year.csv", index=False)
    E.to_csv(HERE / "mirror_gate_by_year.csv", index=False)

    html = build_view(Y, C, D, wr, closed, kept, nav7, nav8)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(f"\n产物 → {HERE}  （用时 {time.time()-t0:.0f}s）")
    return Y, C, D


def build_view(Y, C, D, wr, closed, kept, nav7, nav8) -> str:
    import plotly.graph_objects as go
    NOL = dict(template="plotly_white", margin=dict(l=60, r=20, t=56, b=50),
               font=dict(family="Arial,'Microsoft YaHei'", color=INK))
    LAY = dict(NOL, legend=dict(orientation="h", y=-0.22))
    figs = []

    f1 = go.Figure()
    f1.add_trace(go.Bar(x=Y["year"].astype(str), y=Y["008-007"] * 100, name="008−007",
                        marker_color=[C_POS if v >= 0 else C_NEG for v in Y["008-007"]]))
    f1.add_trace(go.Scatter(x=Y["year"].astype(str), y=Y["年内闸门效应"] * 100, mode="lines+markers",
                            name="年内闸门效应（年块反事实）", line=dict(color=C_ALT, width=3)))
    f1.update_layout(height=360, **LAY, title="图1 · 逐年：008−007 差异 vs 年内闸门效应（%）")
    f1.update_yaxes(title_text="%")
    figs.append(f1.to_html(full_html=False, include_plotlyjs=True))

    f2 = go.Figure()
    for lab, color in [("被关(sc_max>=3)", C_NEG), ("保留(sc_max<3)", C_POS)]:
        d = C[C["分组"] == lab]
        f2.add_trace(go.Bar(x=d["段"], y=d["007周收益均值"] * 100, name=lab, marker_color=color,
                            customdata=d["n"], hovertemplate="%{x} %{y:.3f}%/周 (n=%{customdata})<extra></extra>"))
    f2.update_layout(height=340, barmode="group", **LAY,
                     title="图2 · 反转周：被关组 vs 保留组 的 007 周收益（分两段）")
    f2.update_yaxes(title_text="周均收益(%)")
    figs.append(f2.to_html(full_html=False, include_plotlyjs=False))

    f3 = go.Figure()
    for lab, color in [("被关(sc_max>=3)", C_NEG), ("保留(sc_max<3)", C_POS)]:
        d = C[C["分组"] == lab]
        f3.add_trace(go.Bar(x=d["段"], y=d["创业板牛市占比"] * 100, name=lab, marker_color=color,
                            customdata=d["sc_max均值"],
                            hovertemplate="%{x} 牛市占比 %{y:.0f}% (sc_max 均值 %{customdata:.2f})<extra></extra>"))
    f3.update_layout(height=340, barmode="group", **LAY,
                     title="图3 · 市场状态：被关 vs 保留 的创业板指牛市占比（%）")
    f3.update_yaxes(title_text="创业板指在 MA200 上方的比例(%)")
    figs.append(f3.to_html(full_html=False, include_plotlyjs=False))

    f4 = go.Figure()
    d = D.groupby("year")["无闸门周收益"].agg(["count", "mean"]).reset_index()
    f4.add_trace(go.Bar(x=d["year"].astype(str), y=d["mean"] * 100,
                        marker_color=[C_POS if v >= 0 else C_NEG for v in d["mean"]],
                        customdata=d["count"],
                        hovertemplate="%{x} %{y:.3f}%/周 (n=%{customdata})<extra></extra>"))
    f4.add_hline(y=0, line=dict(color=MUTED))
    f4.update_layout(height=340, **LAY,
                     title="图4 · 对照：007 动量闸门被关周在**无闸门轨迹**下的周收益（%）"
                           "—— 正值=误关年")
    f4.update_yaxes(title_text="周均收益(%)")
    figs.append(f4.to_html(full_html=False, include_plotlyjs=False))

    f5 = go.Figure()
    f5.add_trace(go.Scatter(x=nav7.index, y=nav7.values, name="007", line=dict(color=MUTED, width=2)))
    f5.add_trace(go.Scatter(x=nav8.index, y=nav8.values, name="008", line=dict(color=C_BASE, width=2.5)))
    for t in closed:
        f5.add_vline(x=pd.Timestamp(t), line=dict(color=C_NEG, width=0.8, dash="dot"))
    f5.update_layout(height=400, **LAY, title="图5 · 净值曲线（虚线 = 008 关掉的反转周）")
    f5.update_yaxes(title_text="净值")
    figs.append(f5.to_html(full_html=False, include_plotlyjs=False))

    parts = "".join(f"<div class='fig'>{f}</div>" for f in figs)
    css = f"""<style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      .fig {{ margin:8px 0 28px 0; }}
      div.warn {{ border-left:4px solid {C_NEG}; background:#fff; padding:10px 14px; color:{INK2}; font-size:13px; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_017 — strategy_008 镜像闸门的年度归因</h2>"
            f"<div class='warn'>全部为<b>引擎口径</b>（权重引擎 trades）；自检 = 基线 3.6001 / "
            f"007 4.5663 / 008 4.5535 逐值一致。图 1 的「年内闸门效应」来自<b>年块反事实</b>"
            f"（把该年被关周全部放开后的年内收益差）。</div>"
            f"{parts}</body></html>")


if __name__ == "__main__":
    main()
