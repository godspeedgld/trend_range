"""analysis_019 — 方向 A（反转周在场率）的**引擎终审**。

承 analysis_016（nav 级理想化口径，判方向 A 为清洁负结果）与 strategy_008（把 A 留待 strategy_009）。
本分析在**引擎口径**（`local_weight_backtest.py`，trades 指标）对方向 A 做终审 —— 因为 016 的
风险侧判决已被引擎推翻过一半（016：Sharpe 必被稀释到 0.713；引擎：1.1395 ≈ 007）。

**规则**（= 方向 A 的唯一引擎变体 A2）：`007 + 反转周 n_common≥2 即开仓`
（`n_common` = 本周 top3 与上周 top3 的交集个数；基线稳定性过滤要求 = 3 才满仓）。

预登记判据（先写判据后看数，2026-10-16 用户拍板）：
  Q1 A2 的 nav 7.3276 在「随机开同数量 112 周」分布里的分位
  Q2 ★ A2 的 Sharpe 1.1395 在同一分布里的分位（旧跑只记了 nav）
  Q3 留一（逐个关掉新增周之一）—— 排除单周驱动（本工程陷阱 9）
  Q4 安慰剂反向（开 n_common 最小的同数量 112 周）—— 方向是否真有信息
  判据：Sharpe 分位 ≥ P95 **且** 留一多数仍 > 007  ⇒ 值得作为「收益侧」立项（不替代 008）
        否则 ⇒ 方向 A 清洁关闭

自检：A2 必须逐值回到 **7.3276 / 1.1395 / −0.2142**；007 参照 4.5663/1.1449/−0.2252。

数据全部本地（零云端）；引擎脚手架复用已入库件
`02_strategy_iteration/strategy_008/ab_engine_controls.py`（★含两个非显然修复：exposure 必须
**在周频施加后再 expand**；用 tag-expand 定位每行的贡献周）。本脚本只写本目录，不改任何冻结件。

用法：
    python analysis.py                 # 全量（50 种子 + 安慰剂 + 留一，约 12 分钟）
    python analysis.py --seeds 5 --skip-loo   # 冒烟
    python analysis.py --view-only     # 只用已落盘 CSV 重建 result_view.html
产物：a2_ctrl50_random.csv / a2_loo.csv / engine_check_summary.csv / result_view.html
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]                      # <PROJ>/01_data_analysis/analysis_019/
sys.path.insert(0, str(PROJ / "02_strategy_iteration" / "strategy_008"))
sys.path.insert(0, str(PROJ / "shared"))

from expand_targets_daily import expand_to_daily   # noqa: E402
import ab_engine_controls as A                     # noqa: E402

SEED = 20261016
N_SEED_DEFAULT = 50
# 参照（冻结件）
R_BASE = (3.6001, 0.9034, -0.2431)
R_007 = (4.5663, 1.1449, -0.2252)
R_008 = (4.5535, 1.2754, -0.1836)
R_A2 = (7.3276, 1.1395, -0.2142)

# ── 配色（dataviz 参考调色板：slot1 蓝 / slot2 橙 / 中性文本色；validate_palette 全项 PASS）──
C_SERIES = "#2a78d6"
C_REAL = "#eb6834"
C_NEUTRAL = "#52514e"
C_GRID = "#e4e8ee"
LAYOUT = dict(
    font=dict(family="Microsoft YaHei, Arial, sans-serif", size=13, color="#0b0b0b"),
    paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
    margin=dict(l=60, r=30, t=48, b=50),
    xaxis=dict(gridcolor=C_GRID, zeroline=False),
    yaxis=dict(gridcolor=C_GRID, zeroline=False),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)


# ── 引擎（进程内调用，行情只读一次）──
def build_engine():
    print("[1] 建全开表（一次）…", flush=True)
    sig, meta, cal = A.build_sig_full()
    mk = pd.read_parquet(A.CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])
    cfg = A.eng.WeightBacktestConfig(initial_cash=500_000.0, buy_bps=3.0,
                                     sell_bps=13.0, min_cost=5.0)
    period = A.eng.TradingDaysRebalance(1)
    sig_dates = list(sig["date"].unique())
    s = sig.copy()
    s["_wk"] = s["date"].map({d: i + 1 for i, d in enumerate(sig_dates)})
    w_tag = expand_to_daily(s[["date", "instrument", "_wk"]].rename(columns={"_wk": "weight"}), cal)
    w_wgt = expand_to_daily(s[["date", "instrument", "weight"]], cal)
    assert (w_tag[["date", "instrument"]].values == w_wgt[["date", "instrument"]].values).all()
    ep = w_tag["weight"].values.astype(int) - 1      # 每行的贡献周下标（周界残留 = 旧周）
    w0 = w_wgt["weight"].values
    daily = w_wgt.rename(columns={"instrument": "symbol"})

    def run(flags: dict):
        d = daily.copy()
        d["weight"] = w0 * np.array([flags.get(t, 1) for t in sig_dates], dtype=float)[ep]
        _, tr, _ = A.eng.run_weight_backtest(mk, d, cfg, period)
        _, m = A.eng.nav_from_trades(mk, tr, cfg.initial_cash)
        return float(m["final_nav"]), float(m["sharpe"]), float(m["max_drawdown"])

    return run, sig_dates, meta


def flags_007(meta, sig_dates):
    """007：稳定性过滤 AND NOT(动量周 & sc_mean<2)。"""
    IN = set(sig_dates)
    f = {t: (0 if (not meta[t]["stable"] or (meta[t]["regime"] == "momentum"
                                             and pd.notna(meta[t]["sc_mean"])
                                             and meta[t]["sc_mean"] < 2.0)) else 1)
         for t in meta if t in IN}
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=N_SEED_DEFAULT)
    ap.add_argument("--skip-loo", action="store_true")
    ap.add_argument("--view-only", action="store_true")
    args = ap.parse_args()

    if args.view_only:
        build_view(pd.read_csv(HERE / "a2_ctrl50_random.csv"),
                   pd.read_csv(HERE / "a2_loo.csv"),
                   pd.read_csv(HERE / "engine_check_summary.csv"),
                   pd.read_csv(HERE / "combo_ab_metrics.csv"))
        return

    run, sig_dates, meta = build_engine()
    f7 = flags_007(meta, sig_dates)
    pool = [t for t in sig_dates if meta[t]["regime"] == "reversal" and f7[t] == 0]
    real = [t for t in pool if meta[t]["n_common"] >= 2]
    n_low = int(sum(1 for t in pool if meta[t]["n_common"] <= 1))
    fA2 = dict(f7)
    for t in real:
        fA2[t] = 1

    print("[2] 自检 …", flush=True)
    n_real, sh_real, dd_real = run(fA2)
    ok = abs(n_real - R_A2[0]) < 5e-4 and abs(sh_real - R_A2[1]) < 5e-4 and abs(dd_real - R_A2[2]) < 5e-4
    print(f"    A2 nav {n_real:.4f} sharpe {sh_real:.4f} dd {dd_real:.4f}"
          f"  （期望 {R_A2[0]}/{R_A2[1]}/{R_A2[2]}）→ {'✓' if ok else '✗ 不一致！'}"
          f"  开 {len(real)}/{len(pool)} 周（nc≤1 共 {n_low} 周）", flush=True)
    if not ok:
        print("    ⚠ 自检不通过，停止（口径漂移）", flush=True)
        return

    rows = [{"item": "自检_基线", "nav": R_BASE[0], "sharpe": R_BASE[1], "dd": R_BASE[2]},
            {"item": "自检_007", "nav": R_007[0], "sharpe": R_007[1], "dd": R_007[2]},
            {"item": "自检_008", "nav": R_008[0], "sharpe": R_008[1], "dd": R_008[2]},
            {"item": f"真实A2(开{len(real)}周)", "nav": n_real, "sharpe": sh_real, "dd": dd_real},
            {"item": "池大小", "nav": len(pool), "sharpe": np.nan, "dd": np.nan}]

    # ── Q1/Q2 随机开同数量周 ──
    rng = np.random.default_rng(SEED)
    idx = {t: i for i, t in enumerate(sig_dates)}
    ids = np.array([idx[t] for t in pool])
    print(f"[3] Q1/Q2 随机开同数量 {len(real)} 周 × {args.seeds} 种子 …", flush=True)
    rnd = []
    for k in range(args.seeds):
        pick = rng.choice(ids, size=len(real), replace=False)
        f = dict(f7)
        for i in pick:
            f[sig_dates[i]] = 1
        n, sh, dd = run(f)
        rnd.append({"seed": k, "nav": n, "sharpe": sh, "dd": dd})
        if (k + 1) % 10 == 0:
            print(f"    … {k+1}/{args.seeds}", flush=True)
    rnd = pd.DataFrame(rnd)
    rnd.to_csv(HERE / "a2_ctrl50_random.csv", index=False)
    pct = {}
    for col, real_v in (("nav", n_real), ("sharpe", sh_real), ("dd", dd_real)):
        v = rnd[col].values
        pct[col] = float((v < real_v).mean() * 100)
        print(f"    {col:<7} 真实 {real_v:>8.4f} | 随机 中位 {np.median(v):>8.4f} "
              f"P5 {np.percentile(v, 5):>8.4f} P95 {np.percentile(v, 95):>8.4f} "
              f"min {v.min():>8.4f} max {v.max():>8.4f} | 分位 {pct[col]:.0f}%", flush=True)

    # ── Q4 安慰剂（开 n_common 最小的同数量周）──
    order = sorted(pool, key=lambda t: meta[t]["n_common"])
    placebo = order[:len(real)]
    fP = dict(f7)
    for t in placebo:
        fP[t] = 1
    n_p, sh_p, dd_p = run(fP)
    print(f"[4] Q4 安慰剂（开 n_common 最小的 {len(placebo)} 周）"
          f" nav {n_p:.4f} sharpe {sh_p:.4f} dd {dd_p:.4f}", flush=True)
    rows.append({"item": "安慰剂(开最低n_common)", "nav": n_p, "sharpe": sh_p, "dd": dd_p})
    rows.append({"item": "随机中位", "nav": float(rnd["nav"].median()),
                 "sharpe": float(rnd["sharpe"].median()), "dd": float(rnd["dd"].median())})
    for col in ("nav", "sharpe", "dd"):
        rows.append({"item": f"随机P95_{col}", "nav": float(np.percentile(rnd[col], 95)),
                     "sharpe": np.nan, "dd": np.nan})
        rows.append({"item": f"分位_{col}", "nav": pct[col], "sharpe": np.nan, "dd": np.nan})

    # ── Q3 留一 ──
    if args.skip_loo:
        loo = pd.DataFrame()
    else:
        print(f"[5] Q3 留一（逐个关掉新增周之一，共 {len(real)} 次）…", flush=True)
        out = []
        for j, t0 in enumerate(real):
            f = dict(fA2)
            f[t0] = 0
            n, sh, dd = run(f)
            out.append({"keep_out": str(pd.Timestamp(t0).date()), "nav": n, "sharpe": sh, "dd": dd})
            if (j + 1) % 20 == 0:
                print(f"    … {j+1}/{len(real)}", flush=True)
        loo = pd.DataFrame(out).sort_values("sharpe")
        loo.to_csv(HERE / "a2_loo.csv", index=False)
        print(f"    Sharpe: min {loo['sharpe'].min():.4f} 中位 {loo['sharpe'].median():.4f} "
              f"max {loo['sharpe'].max():.4f} | >007 的 {int((loo['sharpe'] > R_007[1]).sum())}"
              f"/{len(loo)} | >008 的 {int((loo['sharpe'] > R_008[1]).sum())}/{len(loo)}", flush=True)
        print(f"    nav: min {loo['nav'].min():.4f} 中位 {loo['nav'].median():.4f} "
              f"max {loo['nav'].max():.4f}", flush=True)

    pd.DataFrame(rows).to_csv(HERE / "engine_check_summary.csv", index=False)
    build_view(rnd, loo, pd.DataFrame(rows), pd.read_csv(HERE / "combo_ab_metrics.csv"))


# ── 视图 ──
def build_view(rnd, loo, summ, combo):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    figs = []

    # F1 随机对照三联（nav / Sharpe / DD）
    f1 = make_subplots(rows=1, cols=3, subplot_titles=("净值 nav", "Sharpe", "最大回撤 DD"))
    for i, (col, real_v, unit) in enumerate((("nav", R_A2[0], "x"), ("sharpe", R_A2[1], ""),
                                             ("dd", R_A2[2], ""))):
        v = rnd[col].values
        f1.add_trace(go.Histogram(x=v, nbinsx=12, marker_color=C_SERIES, opacity=0.85,
                                  name="随机开同数量周", showlegend=(i == 0),
                                  hovertemplate="随机 " + col + " %{x:.3f}<br>%{y} 个种子<extra></extra>"),
                     row=1, col=i + 1)
        f1.add_vline(x=real_v, line_color=C_REAL, line_width=2)
        f1.add_vline(x=float(np.percentile(v, 95)), line_color=C_NEUTRAL, line_width=2,
                     line_dash="dash")
        f1.add_annotation(x=real_v, y=1.02, yref="paper", showarrow=False, text=f"真实 {real_v:.3f}",
                          font=dict(color=C_REAL, size=12))
    f1.update_layout(**LAYOUT, title="Q1/Q2 随机对照：真实 A2 vs 随机开同样多周（虚线 = 随机 P95）",
                     height=380, bargap=0.08)
    figs.append(f1)

    # F2 留一
    if len(loo):
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=np.arange(1, len(loo) + 1), y=loo["sharpe"].values,
                                mode="markers", marker=dict(color=C_SERIES, size=8,
                                                            line=dict(color="#fcfcfb", width=2)),
                                name="留一 Sharpe", hovertemplate="%{text}<br>Sharpe %{y:.4f}<extra></extra>",
                                text=loo["keep_out"].values))
        f2.add_hline(y=R_007[1], line_color=C_NEUTRAL, line_width=2, line_dash="dash",
                     annotation_text=f"007 = {R_007[1]:.4f}", annotation_position="bottom right")
        f2.add_hline(y=R_008[1], line_color=C_NEUTRAL, line_width=2, line_dash="dot",
                     annotation_text=f"008 = {R_008[1]:.4f}", annotation_position="top right")
        f2.update_layout(**LAYOUT, title=f"Q3 留一：逐个关掉新增周之一（共 {len(loo)} 次）的 Sharpe",
                         xaxis_title="按 Sharpe 升序排名", yaxis_title="Sharpe", height=420)
        figs.append(f2)

    # F3 收益风险前沿
    f3 = go.Figure()
    fam = combo[combo["variant"].isin(["007", "008 = 007+B", "B后叠A(严格序)", "007+A"])]
    f3.add_trace(go.Scatter(x=fam["vol"], y=fam["ann"], mode="lines+markers+text",
                            line=dict(color=C_NEUTRAL, width=1, dash="dash"),
                            marker=dict(color=C_SERIES, size=12, line=dict(color="#fcfcfb", width=2)),
                            text=fam["variant"], textposition="top center",
                            textfont=dict(color=C_NEUTRAL, size=12), name="007 族",
                            hovertemplate="%{text}<br>年化 %{y:.2%}<br>波动 %{x:.2%}<extra></extra>"))
    b = combo[combo["variant"] == "基线"]
    f3.add_trace(go.Scatter(x=b["vol"], y=b["ann"], mode="markers+text",
                            marker=dict(color=C_NEUTRAL, size=12, symbol="diamond",
                                        line=dict(color="#fcfcfb", width=2)),
                            text=b["variant"], textposition="top center",
                            textfont=dict(color=C_NEUTRAL, size=12), name="基线",
                            hovertemplate="%{text}<br>年化 %{y:.2%}<br>波动 %{x:.2%}<extra></extra>"))
    lay3 = {**LAYOUT,
            "title": "收益风险前沿（引擎口径 · trades 指标）",
            "xaxis": {**LAYOUT["xaxis"], "title": "年化波动", "tickformat": ".0%"},
            "yaxis": {**LAYOUT["yaxis"], "title": "年化收益", "tickformat": ".0%"},
            "height": 460}
    f3.update_layout(**lay3)
    figs.append(f3)

    # F4 在场周数 + 安慰剂
    f4 = make_subplots(rows=1, cols=2, subplot_titles=("反转周在场周数", "安慰剂 vs 真实（nav）"),
                       specs=[[{"type": "xy"}, {"type": "xy"}]])
    f4.add_trace(go.Bar(x=["基线/007", "008", "A2(方向A)"], y=[54, 31, 166],
                        marker_color=[C_SERIES, C_SERIES, C_REAL],
                        hovertemplate="%{x}：%{y} 周<extra></extra>", showlegend=False),
                 row=1, col=1)
    f4.add_trace(go.Bar(x=["安慰剂\n(最低 n_common)", "随机中位", "真实 A2", "007"],
                        y=[n_p_v(summ), median_v(summ, "nav"), R_A2[0], R_007[0]],
                        marker_color=[C_NEUTRAL, C_SERIES, C_REAL, C_NEUTRAL],
                        hovertemplate="%{x}：nav %{y:.4f}<extra></extra>", showlegend=False),
                 row=1, col=2)
    f4.update_layout(**LAYOUT, title="Q4 在场规模与安慰剂", height=420, bargap=0.35)
    figs.append(f4)

    # 数字表（表格视图 = 可及性要求）
    tab = summ.copy()
    tab.columns = ["项目", "nav", "sharpe", "dd"]
    body = "".join(
        "<tr>" + "".join(f"<td>{('' if pd.isna(v) else (f'{v:.4f}' if isinstance(v, float) else v))}</td>"
                         for v in r) + "</tr>"
        for r in tab.itertuples(index=False))
    figs_html = figs[0].to_html(full_html=False, include_plotlyjs=True) + "".join(
        f.to_html(full_html=False, include_plotlyjs=False) for f in figs[1:])
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>analysis_019 — 方向 A（反转周在场率）引擎终审</title>
<style>
 body{{font-family:"Microsoft YaHei",Arial,sans-serif;margin:24px;background:#fcfcfb;color:#0b0b0b}}
 h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px}}
 .note{{color:#52514e;font-size:13px;margin:8px 0 18px}}
 table{{border-collapse:collapse;margin:12px 0}} th,td{{border:1px solid #e4e8ee;padding:6px 10px;font-size:13px}}
 th{{background:#f3f5f8}} .verdict{{background:#fff4ee;border-left:4px solid {C_REAL};padding:12px 16px;margin:16px 0}}
</style></head><body>
<h1>analysis_019 — 方向 A（反转周在场率）的引擎终审</h1>
<div class="note">规则：<b>007 + 反转周 n_common≥2 即开仓</b>（基线稳定性过滤要求 top3 与上周完全相同）。
口径：权重引擎 local_weight_backtest.py（trades 指标）；自检 A2 = 7.3276 / 1.1395 / −0.2142。</div>
<div class="verdict"><b>判决：方向 A 清洁关闭</b> —— Sharpe 随机分位 92%（&lt; P95 1.2084），
留一仅 41/112 高于 007，且最大贡献为单周（2024-09-20，关掉后 nav 7.3276 → 4.8222）。
唯一亮点 = 回撤 98 分位（随机开同样多周的中位回撤 −39%）。</div>
{figs_html}
<h2>数字表</h2>
<table><tr><th>项目</th><th>nav</th><th>sharpe</th><th>dd</th></tr>{body}</table>
<div class="note">产物：a2_ctrl50_random.csv（50 种子）· a2_loo.csv（112 次留一）·
engine_check_summary.csv · combo_ab_metrics.csv</div>
</body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(f"→ {HERE/'result_view.html'}（{len(figs)} 图）", flush=True)


def n_p_v(summ):
    return float(summ.loc[summ["item"] == "安慰剂(开最低n_common)", "nav"].iloc[0])


def median_v(summ, col):
    return float(summ.loc[summ["item"] == "随机中位", col].iloc[0])


if __name__ == "__main__":
    main()
