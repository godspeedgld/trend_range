"""analysis_016 — 反转周在场率：稳定性过滤与反转 regime 的语义错配检验。

**现象（2026-10-16 诊断发现）**：基线的「稳定性过滤」（本周 top3 行业集合 == 上周 → 满仓，
否则空仓一周）在两类 regime 下的**在场率差异极大**：

    regime      周数   满仓周   在场率
    momentum     240     127    52.5%
    reversal     254      54    21.3%     ← 跨年稳定（2017-2026 每年 14%~29%）

**机制假说**：稳定性过滤要求「行业排序**不变**」，而反转 regime 的定义（变盘指数 T′ ≥ 0）
恰恰是「行业排序**在重排**」——两个部件语义冲突，反转周被系统性清空。
但反转周的行业指数是**正收益**（+0.222%/周），怀疑这笔钱被白扔。

**四步检验**：
  A. 被跳过的反转周是「保护」还是「白扔」—— 反转周按 top3 稳定/不稳定分组，
     比行业指数收益 与 理想化组合收益（均值/波动/胜率/逐年）
  B. 候选在场规则（★只改反转周，动量周一字不动）—— 四种规则的理想化 nav 对比
  C. 随机对照 —— 从被跳过的反转周里随机挑同样多的周满仓 × 20 种子 → 候选规则是否只是「多在场」
  D. 风险侧 —— 多在场的周波动/最差周/回撤路径是否更差

**口径（★nav 级理想化，与 analysis_009-D 同级，只作方向参考）**：
  理想化周收益 = 目标持仓股（weekly_targets_baseline_weekly_indpre_rawpx，**空仓周也含股单**，
  权重归一到 Σ=1）× 原始价 exec_open(t) → exec_open(t+1)。
  **无成本、无 lot 约束、无停牌顺延** ⇒ 结果**不是**基线的 3.600x，只与同一引擎下的 R0 对照。
  正式检验须进 local_weight_backtest.py + 过 analysis_004 随机门槛。

数据全部本地（零云端、零回测重跑）：
  shared/_cache/{weekly_targets_baseline_weekly_indpre_rawpx, weekly_plan,
                 engine_market_weekly_indpre_rawpx, industry_index, industry_crowding_weekly}.parquet

用法：python analysis.py
产物：rule_grid.csv / regime_weeks.csv / result_view.html（records.md 手写）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
CACHE = PROJ / "shared" / "_cache"

SEED = 20261016
N_SEED = 20
WPY = 52.18                     # 每年周数（年化用）
BL = PROJ / "02_strategy_iteration/strategy_007"     # 冻结基线对照（self-check 3.6001）

# 视图配色（与 analysis_009 同一套）
C_BASE, C_ALT = "#2a78d6", "#eb6834"
C_POS, C_NEG = "#2a78d6", "#e34948"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


# ══════════════════════════════════════════════════════════════════════
# ① 理想化周收益：目标持仓 × exec_open(t) → exec_open(t+1)
# ══════════════════════════════════════════════════════════════════════
def build_weekly_returns() -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (周面板, 行业指数面板)。周面板每行一个信号日。

    ★ 权重口径：空仓周的冻结 targets **weight 全 0**（exposure 因子），但股单仍在。
      这里用 `signal_panel_weekly_indpre.vol_20` 按**基线的同一公式**重建 1/vol 行业内权重
      （inv = 1/vol.clip(1e-4) 行业内归一 / N_IND；vol 缺失按行业内中位数兜底）。
      已自检：重建权重与 174 个满仓周的冻结权重 **逐值一致（最大绝对差 0.0）**。
    """
    tgt = pd.read_parquet(CACHE / "weekly_targets_baseline_weekly_indpre_rawpx.parquet")
    mk = pd.read_parquet(CACHE / "engine_market_weekly_indpre_rawpx.parquet")
    mk["date"] = pd.to_datetime(mk["date"])
    op = mk.pivot(index="date", columns="symbol", values="open")

    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")[
        ["date", "symbol", "vol_20"]].rename(columns={"date": "signal_date"})
    tgt = tgt.merge(panel, on=["signal_date", "symbol"], how="left")

    def _w(g: pd.DataFrame) -> pd.Series:
        v = g["vol_20"].fillna(g["vol_20"].median())
        inv = 1.0 / v.clip(lower=1e-4)
        return (inv / inv.sum() / 3.0).values

    tgt["w"] = tgt.groupby(["signal_date", "ind_name"], group_keys=False).apply(
        lambda g: pd.Series(_w(g), index=g.index), include_groups=False)

    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    plan["exec_date"] = pd.to_datetime(plan["exec_date"])
    plan = plan.sort_values("signal_date").reset_index(drop=True)
    sd, ed = plan["signal_date"].tolist(), dict(zip(plan["signal_date"], plan["exec_date"]))
    nxt = dict(zip(sd[:-1], sd[1:]))

    rows = []
    for d, g in tgt.groupby("signal_date"):
        d = pd.Timestamp(d)
        nd = nxt.get(d)
        if nd is None or ed[d] not in op.index or ed[nd] not in op.index:
            continue
        w = g.set_index("symbol")["w"]
        w = w / w.sum()                                # 归一（满仓周本就 Σ=1；空仓周变成"若有持仓"）
        p1 = op.loc[ed[d]].reindex(w.index)
        p2 = op.loc[ed[nd]].reindex(w.index)
        ok = p1.notna() & p2.notna()
        if ok.sum() == 0:
            continue
        r = float((w[ok] / w[ok].sum() * (p2[ok] / p1[ok] - 1)).sum())
        rows.append({"signal_date": d, "exec_date": ed[d], "r": r,
                     "n_stock": int(ok.sum()), "n_miss": int((~ok).sum())})
    w = pd.DataFrame(rows)
    w = w.merge(plan[["signal_date", "regime", "exposure", "T_prime", "top3"]],
                on="signal_date", how="left")
    # 前一信号日 top3（稳定性过滤的原子量）
    prev = plan["top3"].shift(1)
    plan["prev_top3"] = prev
    plan["n_common"] = [len(set(str(a).split(",")) & set(str(b).split(",")))
                        if isinstance(b, str) else 3
                        for a, b in zip(plan["top3"], prev)]
    plan["stable"] = plan["n_common"] == 3          # 与基线 exposure 同义（首周视为稳定）
    w = w.drop(columns=["top3"]).merge(
        plan[["signal_date", "top3", "prev_top3", "n_common", "stable"]],
        on="signal_date", how="left")

    # 行业指数面板（同期）
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    px = ind.pivot(index="date", columns="ind_name", values="close").sort_index()
    irows = []
    for d in w["signal_date"]:
        nd = nxt.get(d)
        if nd is None:
            continue
        top3 = str(plan.loc[plan["signal_date"] == d, "top3"].iloc[0]).split(",")
        irows.append({"signal_date": d,
                      "r_ind": float(np.mean([px.at[nd, i] / px.at[d, i] - 1 for i in top3]))})
    iw = pd.DataFrame(irows)
    w = w.merge(iw, on="signal_date", how="left")

    # ★ 冻结基线的**实际周收益**（同一周网格：nav[t+1]/nav[t] − 1）——混合口径的基数
    frz = pd.read_csv(BL / "backtest_strategy_baseline/backtest_logs/nav_from_trades.csv",
                      parse_dates=["date"]).set_index("date")["nav"]
    fr = [frz[nd] / frz[d] - 1 if (d in frz.index and nd in frz.index) else np.nan
          for d, nd in zip(w["signal_date"], [nxt.get(d) for d in w["signal_date"]])]
    w["frozen"] = fr
    return w, plan


# ══════════════════════════════════════════════════════════════════════
# ② 在场规则：★只改反转周，动量周维持基线
# ══════════════════════════════════════════════════════════════════════
def apply_rule(w: pd.DataFrame, name: str) -> pd.Series:
    base = w["exposure"].astype(bool).copy()                 # 基线（两 regime 同规则）
    is_rev = w["regime"] == "reversal"
    if name == "R0 基线（集合相等）":
        return base
    if name == "R1 反转周恒满仓":
        return base | is_rev
    if name == "R2 反转周有交集(≥1 相同)":
        return base | (is_rev & (w["n_common"] >= 1))
    if name == "R3 反转周≥2 相同":
        return base | (is_rev & (w["n_common"] >= 2))
    if name == "R4 反转周≥1 相同 AND 不拥挤":
        return base | (is_rev & (w["n_common"] >= 1) & (w["sc_top3"] < 3))
    raise ValueError(name)


COST_SWAP = 0.0003 + 0.0013      # 买 3bps + 卖 13bps（与 config.json 一致）


def turnover_cost(w: pd.DataFrame, ex: pd.Series, base_ex: pd.Series) -> pd.Series:
    """新增在场周的**换手成本估算**（正数；只对「基线原本空仓、规则开了仓」的周计）。

    行业集合变动 (3 − n_common) 个 → 该比例的组合被换掉；每个换掉的行业 = 卖 2 只 + 买 2 只。
    本轮换成本 = (3 − n_common)/3 × (0.03% + 0.13%)。lot/最低佣金在小资金下可忽略。
    ★ 是估算，不是引擎口径（无 lot 取整、无停牌顺延、无部分成交）。
    """
    add = ex & ~base_ex
    return ((3 - w["n_common"]).clip(lower=0) / 3 * COST_SWAP).where(add, 0.0)


def metrics(r: pd.Series, dates: pd.Series) -> dict:
    r = r.fillna(0.0).values
    nav = np.cumprod(1 + r)
    yrs = (pd.Timestamp(dates.iloc[-1]) - pd.Timestamp(dates.iloc[0])).days / 365.25
    ann = nav[-1] ** (1 / yrs) - 1
    vol = r.std(ddof=1) * np.sqrt(WPY)
    dd = float((nav / np.maximum.accumulate(nav) - 1).min())
    return {"nav": float(nav[-1]), "ann": float(ann), "vol": float(vol),
            "sharpe": float(ann / vol), "dd": dd, "n_weeks": int(len(r))}


def main():
    w, plan = build_weekly_returns()

    # 拥挤度（供 R4 用，也供分组表）
    crowd = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
    sc = {(pd.Timestamp(a), b): float(c) for a, b, c in
          zip(crowd["week"], crowd["ind"], crowd["signal_count"])}
    w["sc_top3"] = [np.mean([sc.get((d, i), np.nan) for i in str(t).split(",")])
                    for d, t in zip(w["signal_date"], w["top3"])]

    print(f"窗口 {w['signal_date'].min().date()} ~ {w['signal_date'].max().date()}  "
          f"{len(w)} 信号周（动量 {(w.regime=='momentum').sum()} / 反转 {(w.regime=='reversal').sum()}）")
    print(f"缺口单元格：{int(w['n_miss'].sum())} 个（占 "
          f"{w['n_miss'].sum()/ (w['n_miss']+w['n_stock']).sum():.3%}）")

    # ── A. 稳定 vs 不稳定（反转周）──
    A = (w.groupby(["regime", "stable"])
           .agg(n=("r", "size"), 组合=("r", "mean"), 行业指数=("r_ind", "mean"),
                胜率=("r", lambda s: (s > 0).mean()), 波动=("r", "std"),
                最差周=("r", "min"))
           .round(5))
    print("\n== A. regime × top3 稳定状态 ==")
    print(A.to_string())

    # ── B. 候选规则 ──
    rules = ["R0 基线（集合相等）", "R1 反转周恒满仓", "R2 反转周有交集(≥1 相同)",
             "R3 反转周≥2 相同", "R4 反转周≥1 相同 AND 不拥挤"]
    def hybrid(w: pd.DataFrame, ex: pd.Series, base_ex: pd.Series) -> pd.Series:
        """★ 混合口径（主口径）：基线满仓周 & 保持空仓的周用**冻结引擎实际收益**；
        新增周（基线空仓 → 规则满仓）用「理想化满仓收益 − 换手成本估算」。
        ⇒ 天然扣掉了基线空仓周里那笔**清仓滞后残差**（不能算进增量），且 R0 应逐值回到 3.6001。"""
        add = ex & ~base_ex
        c = turnover_cost(w, ex, base_ex)
        r = w["frozen"].fillna(0.0).copy()
        r[add] = (w["r"][add] - c[add])
        return r

    grid, navs = [], {}
    base_ex = w["exposure"].astype(bool)
    for nm in rules:
        ex = apply_rule(w, nm)
        c = turnover_cost(w, ex, base_ex)
        m = metrics(w["r"].where(ex, 0.0), w["signal_date"])
        mc = metrics(w["r"].where(ex, 0.0) - c, w["signal_date"])
        mh = metrics(hybrid(w, ex, base_ex), w["signal_date"])
        m.update({"rule": nm, "在场周": int(ex.sum()),
                  "反转在场": int((ex & (w.regime == "reversal")).sum()),
                  "新增周": int((ex & ~base_ex).sum()),
                  "nav_net": mc["nav"], "sharpe_net": mc["sharpe"], "dd_net": mc["dd"],
                  "nav_hyb": mh["nav"], "ann_hyb": mh["ann"], "sharpe_hyb": mh["sharpe"],
                  "dd_hyb": mh["dd"], "成本": float(c.sum())})
        grid.append(m)
        navs[nm] = hybrid(w, ex, base_ex)
    g = pd.DataFrame(grid)[["rule", "nav", "nav_net", "nav_hyb",
                            "ann", "sharpe", "sharpe_net", "sharpe_hyb",
                            "dd", "dd_net", "dd_hyb", "成本", "在场周", "反转在场", "新增周"]]
    print("\n== B. 候选规则（只改反转周）—— nav_hyb = 主口径（冻结基数 + 新增周替换）==")
    print(g.round(4).to_string(index=False))
    chk = float(g.loc[g.rule.str.startswith("R0"), "nav_hyb"].iloc[0])
    print(f"\n  ★ 自检：R0 混合口径 nav = {chk:.4f}（冻结基线 3.6001，"
          f"差 {abs(chk/3.60007516-1)*100:.3f}%）")

    # ── C. 随机对照（用混合口径）──
    skipped = np.where((w.regime == "reversal") & ~base_ex)[0]     # 被跳过的反转周
    rng = np.random.default_rng(SEED)
    ctrl = {}
    for nm in rules[1:]:
        ex = apply_rule(w, nm)
        k = int((ex & ~base_ex).sum())                            # 该规则新开了多少周
        if k >= len(skipped):
            continue                                              # R1 恒满仓 = 全开，无可随机
        vals = []
        for _ in range(N_SEED):
            pick = rng.choice(skipped, size=k, replace=False)
            exr = base_ex.copy()
            exr.iloc[pick] = True
            vals.append(metrics(hybrid(w, exr, base_ex), w["signal_date"])["nav"])
        ctrl[nm] = np.array(vals)
    print(f"\n== C. 随机对照（从 {len(skipped)} 个被跳过的反转周里随机开同样多的周 × {N_SEED} 种子；混合口径）==")
    for nm, v in ctrl.items():
        real = float(g.loc[g.rule == nm, "nav_hyb"].iloc[0])
        pct = (v < real).mean() * 100
        print(f"  {nm:<26} 真实 {real:.4f}  随机中位 {np.median(v):.4f}  "
              f"P95 {np.percentile(v,95):.4f}  分位 {pct:.0f}%")
    print(f"  {'R1 反转周恒满仓':<26} = 全开（k={len(skipped)}={len(skipped)}），无可随机 → N/A")

    # ── D. 风险侧 ──
    print("\n== D. 风险侧：新增在场周的收益分布 ==")
    for nm in rules[1:]:
        ex = apply_rule(w, nm)
        add = ex & ~base_ex
        rr = w.loc[add, "r"]
        print(f"  {nm:<26} 新增 {len(rr):>3} 周  均值 {rr.mean()*100:+.3f}%  "
              f"波动 {rr.std()*100:.2f}%  胜率 {(rr>0).mean():.1%}  最差 {rr.min()*100:+.2f}%")

    # ── E. 逐年稳健性：被跳过的反转周（= R1 新增的 195 周）──
    rev = w[w.regime == "reversal"].copy()
    rev["yr"] = rev["signal_date"].dt.year
    rev["跳过周"] = ~rev["stable"]
    Ey = (rev.groupby(["yr", "跳过周"])
             .agg(n=("r", "size"), 均值=("r", "mean"), 胜率=("r", lambda s: (s > 0).mean()))
             .reset_index())
    piv_n = Ey.pivot(index="yr", columns="跳过周", values="n")
    piv_m = Ey.pivot(index="yr", columns="跳过周", values="均值")
    print("\n== E. 反转周 逐年：被跳过的周（n / 周均收益%）vs 满仓的周 ==")
    for y in piv_m.index:
        a = piv_m.loc[y, True] * 100 if True in piv_m.columns and pd.notna(piv_m.loc[y].get(True, np.nan)) else np.nan
        b = piv_m.loc[y, False] * 100 if False in piv_m.columns and pd.notna(piv_m.loc[y].get(False, np.nan)) else np.nan
        na = int(piv_n.loc[y].get(True, 0)) if True in piv_n.columns else 0
        nb = int(piv_n.loc[y].get(False, 0)) if False in piv_n.columns else 0
        print(f"  {y}  跳过 n={na:>3} {a:+6.3f}%   |   满仓 n={nb:>3} {b:+6.3f}%")
    n_pos = int((Ey[Ey["跳过周"]]["均值"] > 0).sum())
    print(f"  → 被跳过的反转周里，按年看有 {n_pos}/{len(Ey[Ey['跳过周']])} 年是正收益")

    # ── 落盘 ──
    g.to_csv(HERE / "rule_grid.csv", index=False)
    A.reset_index().round(6).to_csv(HERE / "regime_weeks.csv", index=False)
    w.to_csv(HERE / "weekly_panel.csv", index=False)
    Ey.to_csv(HERE / "reversal_by_year.csv", index=False)

    html = build_view(w, A, g, ctrl, navs)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(f"\n产物 → {HERE}")
    return w, A, g, ctrl


# ══════════════════════════════════════════════════════════════════════
# ③ 视图
# ══════════════════════════════════════════════════════════════════════
def build_view(w, A, g, ctrl, navs) -> str:
    import plotly.graph_objects as go
    NOL = dict(template="plotly_white", margin=dict(l=60, r=20, t=56, b=50),
               font=dict(family="Arial,'Microsoft YaHei'", color=INK))
    LAY = dict(NOL, legend=dict(orientation="h", y=-0.22))
    figs = []

    # 图1 · 在场率 逐年 × regime
    w2 = w.copy()
    w2["yr"] = w2["signal_date"].dt.year
    piv = (w2.assign(ex=w2["exposure"].astype(bool))
             .pivot_table(index="yr", columns="regime", values="ex", aggfunc="mean"))
    f1 = go.Figure()
    for rg, color in (("momentum", C_ALT), ("reversal", C_BASE)):
        if rg in piv:
            f1.add_trace(go.Bar(x=piv.index.astype(str), y=piv[rg] * 100,
                                name={"momentum": "动量周", "reversal": "反转周"}[rg],
                                marker_color=color))
    f1.update_layout(height=340, barmode="group", **LAY,
                     title="图1 · 基线在场率（稳定性过滤通过率）逐年 × regime（%）")
    f1.update_yaxes(title_text="在场率(%)")
    figs.append(f1.to_html(full_html=False, include_plotlyjs=True))

    # 图2 · 反转周 稳定 vs 不稳定 的周收益（理想化组合）
    f2 = go.Figure()
    rev = w[w.regime == "reversal"]
    for st, lb, color in ((True, "top3 不变 → 基线满仓", C_POS),
                          (False, "top3 变了 → 基线空仓", C_NEG)):
        gg = rev[rev.stable == st]["r"].clip(-0.15, 0.15)
        f2.add_trace(go.Box(y=gg.values, name=f"{lb}(n={len(gg)})", marker_color=color,
                            boxpoints="outliers", pointpos=-1.5))
    f2.update_layout(height=380, **LAY,
                     title="图2 · 反转周理想化组合周收益：稳定性过滤到底在挡什么（截尾 ±15%）")
    f2.update_yaxes(tickformat=".1%")
    figs.append(f2.to_html(full_html=False, include_plotlyjs=False))

    # 图3 · 候选规则 nav 曲线
    f3 = go.Figure()
    palette = [MUTED, C_POS, C_ALT, "#8a6fd1", "#1a9c7a"]
    for i, nm in enumerate(g["rule"]):
        f3.add_trace(go.Scatter(x=w["signal_date"], y=np.cumprod(1 + navs[nm].fillna(0)),
                                name=nm + "（含成本估算）",
                                line=dict(color=palette[i % len(palette)], width=3 if i == 0 else 2)))
    f3.update_layout(height=420, **LAY,
                     title="图3 · 候选在场规则净值（混合口径：冻结基数 + 新增周＝理想化满仓−成本）")
    f3.update_yaxes(title_text="净值")
    figs.append(f3.to_html(full_html=False, include_plotlyjs=False))

    # 图4 · 真实 vs 随机对照
    f4 = go.Figure()
    for i, nm in enumerate(ctrl.keys()):
        v = ctrl[nm]
        lbl = nm.replace("反转周", "")
        f4.add_trace(go.Box(y=v, name=lbl, marker_color=C_ALT,
                            boxpoints="all", jitter=0.5, pointpos=0))
        real = float(g.loc[g.rule == nm, "nav_hyb"].iloc[0])
        f4.add_trace(go.Scatter(x=[lbl], y=[real], mode="markers",
                                marker=dict(color=C_NEG, size=14, symbol="diamond"),
                                name="真实规则", showlegend=(i == 0),
                                hovertemplate="真实 %{y:.4f}<extra></extra>"))
    base_nav = float(g.loc[g.rule.str.startswith("R0"), "nav"].iloc[0])
    f4.add_hline(y=base_nav, line=dict(color=MUTED, dash="dash"),
                 annotation_text=f"基线 R0 {base_nav:.3f}")
    f4.update_layout(height=380, **LAY, title=f"图4 · 随机对照：随机关掉同数量的反转周 × {N_SEED} 种子")
    f4.update_yaxes(title_text="净值")
    figs.append(f4.to_html(full_html=False, include_plotlyjs=False))

    # 图5 · 被跳过的反转周：组合 vs 行业指数
    f5 = go.Figure()
    sk = rev[rev.stable == False]
    f5.add_trace(go.Scatter(x=sk["r_ind"], y=sk["r"], mode="markers",
                            marker=dict(color=C_BASE, size=5, opacity=0.5),
                            name=f"被跳过的反转周 (n={len(sk)})"))
    lim = 0.15
    f5.add_trace(go.Scatter(x=[-lim, lim], y=[-lim, lim], mode="lines",
                            line=dict(color=MUTED, dash="dash"), name="y=x"))
    f5.update_layout(height=380, **LAY,
                     title="图5 · 被跳过的反转周：行业指数收益 vs 组合收益（截尾 ±15%）")
    f5.update_xaxes(title_text="top3 行业指数收益", tickformat=".1%")
    f5.update_yaxes(title_text="组合收益", tickformat=".1%")
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
            f"<h2>analysis_016 — 反转周在场率（稳定性过滤 × 反转 regime 语义错配）</h2>"
            f"<div class='warn'><b>nav 级理想化</b>：周收益 = 目标持仓（空仓周按股单归一）× "
            f"exec_open→exec_open，<b>无成本/无 lot/无停牌顺延</b>，绝对水平<span>不可</span>与基线的 "
            f"3.600x 直接比；本页所有 y 轴只用于同引擎内的相对比较。"
            f"正式检验须进 weight 引擎 + 过 analysis_004 随机门槛。</div>"
            f"{parts}</body></html>")


if __name__ == "__main__":
    main()
