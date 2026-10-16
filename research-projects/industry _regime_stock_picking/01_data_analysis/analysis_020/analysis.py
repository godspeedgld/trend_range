"""analysis_020 — 行业聚类（广发之十）能否改进本工程行业层：**可行性预检归档**。

承研报 `research_report/行业轮动框架-广发/industry_clustering_guangfa_20211117_main.md`
（广发「重构行业轮动框架之十」：层次聚类 + 余弦距离 + 全链 + K=5 + 1 年窗）。

**待答问题**：把"申万一级行业"按统计相关性聚成板块，再用板块信息改进行业层，**哪条路活着？**

预检把候选形态砍到只剩一条（见 §A/§C）：
  · 「先选板块、再选板块内最强」的两阶段**重排**形态 ⇒ **C 表否决**（板块内排序 IC 只有全截面的一半）
  · 「维持全截面排序不变，只在三个行业落进同一簇时把末位换成簇外最优」的**分散约束** ⇒ 本分析要归档的形态
  · 「放宽稳定性过滤以增加在场」早已被 analysis_016/019 关闭（无关聚类）

**★ 事前判据（先写门槛，再看数；通过 ⇒ 允许申报 strategy_009，不通过 ⇒ 关闭这条线）**

| # | 门槛 | 含义 |
|---|---|---|
| G1 | 被约束改动的周 ≥ 25 周（≈5%） | 触发面太小则效应不可测 |
| G2 | 触发周的"最大簇占比"中位 ≤ 50% | 簇不均衡时"同簇"语义失真（会变成任意板块倾斜） |
| G3 | 换入行业的全截面排名中位 ≤ 8 / 31 | 替换代价不能太大（否则等于破坏排序信号） |
| G4 | 相邻周聚类标签 ARI 中位 ≥ 0.70 | 聚类本身要稳定 |
| G5 | K=5 快照能复现原文至少两处分组表述 | 方法可搬到本工程 31 个 SW2021 一级 |

> ★★ **重要声明**：**分析层通过 ≠ 策略层采纳**。本分析全部是"行业层事件级"证据，
> 本工程已三度目睹「事件级成立 → 组合级失效」（008/011/016）。策略层是否采纳**必须**过引擎
> 对照（随机替换臂 / 留一 / 安慰剂 / 参数网格 + 在场率诊断），本分析**不能替代**引擎判决
> （04_delivery 陷阱第 7 条：nav 级/方向级论证只能筛进，不能杀掉）。

**口径**：特征 = 截至信号日的**前 252 个交易日日收益率**（31 行业 × 252 维）；
距离余弦、类间全链（原文结论；平均链在 E 表被证更差）；K 网格 {3,4,5,6,7}。
聚类是**周频动态**（每周一个调仓点，用调仓日前 1 年窗），无前视。

数据：`shared/_cache/industry_index.parquet`（31 行业日频 close，2015-01-05 起，含 mom_240/mom_60）
     `shared/_cache/weekly_plan.parquet`（基线每周 top3）、`regime.parquet`（变盘指数 T′）
只读缓存；产物全部写本目录。

用法：python analysis.py            # 全量（约 2~3 分钟）
      python analysis.py --view-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
CACHE = PROJ / "shared" / "_cache"

WIN = 252
K_GRID = [3, 4, 5, 6, 7]
LINKAGES = ["complete", "average"]
# 配色：dataviz 参考调色板 slot1/2/3（validate_palette 3 色全项 PASS；aqua 有 contrast WARN
# ⇒ 本视图已配可见标签 + 数字表，满足 relief 要求）
C1, C2, C3, C_NEUTRAL, C_GRID = "#2a78d6", "#eb6834", "#1baf7a", "#52514e", "#e4e8ee"
LAYOUT = dict(font=dict(family="Microsoft YaHei, Arial, sans-serif", size=13, color="#0b0b0b"),
              paper_bgcolor="#fcfcfb", plot_bgcolor="#fcfcfb",
              margin=dict(l=60, r=30, t=48, b=50),
              xaxis=dict(gridcolor=C_GRID, zeroline=False),
              yaxis=dict(gridcolor=C_GRID, zeroline=False),
              legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0))


def load_data():
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    ind["date"] = pd.to_datetime(ind["date"])
    px = ind.pivot(index="date", columns="ind_name", values="close").sort_index()
    ret = px.pct_change()
    mom = {c: ind.pivot(index="date", columns="ind_name", values=c).sort_index()
           for c in ("mom_240", "mom_60")}
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    plan = plan.sort_values("signal_date").reset_index(drop=True)
    plan["t3"] = plan["top3"].map(lambda s: str(s).split(","))
    plan["t3key"] = plan["top3"].map(lambda s: ",".join(sorted(str(s).split(","))))
    reg = pd.read_parquet(CACHE / "regime.parquet").set_index("date")
    return px, ret, mom, plan, reg


def cluster_labels(ret, px, plan, K, linkage) -> pd.DataFrame:
    """逐周标签（词=信号日, 列=行业）。命中缓存则不重算。"""
    f = HERE / f"labels_K{K}_{linkage}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    dates = list(px.index)
    rows = {}
    for t in plan["signal_date"]:
        if t not in px.index:
            continue
        pos = dates.index(t)
        if pos + 1 < WIN:
            continue
        X = ret.iloc[pos - WIN + 1: pos + 1].T.dropna()
        if X.shape[0] < 10:
            continue
        lb = AgglomerativeClustering(n_clusters=K, metric="cosine", linkage=linkage).fit_predict(X.values)
        rows[t] = pd.Series(lb, index=X.index)
    lab = pd.DataFrame(rows).T
    lab.to_parquet(f)
    return lab


def regime_of(reg, t) -> str:
    return "momentum" if float(reg.at[t, "T_prime"]) < 0 else "reversal"


def score_of(mom, t, regime) -> pd.Series:
    """行业评分：越大越好（动量周用 mom_240，反转周用 −mom_60）。"""
    m = mom["mom_240" if regime == "momentum" else "mom_60"].loc[t]
    return m if regime == "momentum" else -m


def top3_replaced(lab_t: pd.Series, top3: list, key: pd.Series, mode: str):
    """返回 (新 top3, 换入行业 or None)。mode='last' 只换末位；mode='all' 拆成 3 簇。"""
    n_dist = len({lab_t.get(x, -1) for x in top3})
    if mode == "last":
        if n_dist != 1:
            return top3, None
        outside = key[lab_t != lab_t[top3[0]]].dropna()
        if outside.empty:
            return top3, None
        return [top3[0], top3[1], outside.idxmax()], outside.idxmax()
    if n_dist >= 3:
        return top3, None
    new, used = [], set()
    for x in top3:
        if lab_t.get(x, -1) not in used:
            new.append(x)
            used.add(lab_t.get(x, -1))
    rest = key[~key.index.isin(new)].dropna().sort_values(ascending=False)
    for nm in rest.index:
        if lab_t.get(nm, -1) not in used:
            new.append(nm)
            used.add(lab_t.get(nm, -1))
        if len(new) == 3:
            break
    return new[:3], (new[2] if len(new) > 2 and new[2] not in top3 else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--view-only", action="store_true")
    args = ap.parse_args()
    if args.view_only:
        return build_view()

    px, ret, mom, plan, reg = load_data()
    labs = {(K, lg): cluster_labels(ret, px, plan, K, lg) for K in K_GRID for lg in LINKAGES}
    lc = {(K, "complete"): labs[(K, "complete")] for K in K_GRID}
    weeks = list(lc[(5, "complete")].index)
    planw = plan.set_index("signal_date")
    n_ind = lc[(5, "complete")].shape[1]
    print(f"聚类周数 {len(weeks)}（{weeks[0].date()} ~ {weeks[-1].date()}），行业数 {n_ind}，窗宽 {WIN} 日")

    # ── A 基线 top3 的板块集中度（K 网格）──
    A = []
    for K in K_GRID:
        lab = lc[(K, "complete")]
        cnt = {1: 0, 2: 0, 3: 0}
        for t in weeks:
            ids = [lab.loc[t].get(x, -1) for x in planw.loc[t, "t3"]]
            ids = [i for i in ids if i >= 0]
            if len(ids) == 3:
                cnt[len(set(ids))] += 1
        tot = sum(cnt.values())
        A.append({"K": K, "同簇": cnt[1], "两簇": cnt[2], "三簇全异": cnt[3],
                  "同簇占比": cnt[1] / tot, "三簇全异占比": cnt[3] / tot})
    A = pd.DataFrame(A)
    A.to_csv(HERE / "A_concentration.csv", index=False)
    print("\n== A. 基线 top3 的板块集中度 ==")
    print(A.round(3).to_string(index=False))

    # ── B 在场率代价（重排形态）：集合全等 = 稳定性过滤满仓条件 ──
    base_prev, base_n3 = None, 0
    for t in weeks:
        cur = planw.loc[t, "t3key"]
        if base_prev is not None and cur == base_prev:
            base_n3 += 1
        base_prev = cur
    B = [{"形态": "基线（现有 top3）", "K": "-", "集合全等周数": base_n3,
          "占比": base_n3 / (len(weeks) - 1)}]
    for K in K_GRID:
        lab, prev, n3 = lc[(K, "complete")], None, 0
        for t in weeks:
            new, _ = top3_replaced(lab.loc[t], planw.loc[t, "t3"],
                                   score_of(mom, t, regime_of(reg, t)), "all")
            cur = ",".join(sorted(new))
            if prev is not None and cur == prev:
                n3 += 1
            prev = cur
        B.append({"形态": f"每簇选最强（重排, K={K}）", "K": K, "集合全等周数": n3,
                  "占比": n3 / (len(weeks) - 1)})
    B = pd.DataFrame(B)
    B.to_csv(HERE / "B_inmarket.csv", index=False)
    print("\n== B. 在场率代价（重排形态 vs 基线）==")
    print(B.round(3).to_string(index=False))

    # B2：分散约束形态（只换末位）自身的在场率代价 —— 与稳定性过滤是否冲突
    B2 = []
    for K in K_GRID:
        lab, prev, n3 = lc[(K, "complete")], None, 0
        for t in weeks:
            new, _ = top3_replaced(lab.loc[t], planw.loc[t, "t3"],
                                   score_of(mom, t, regime_of(reg, t)), "last")
            cur = ",".join(sorted(new))
            if prev is not None and cur == prev:
                n3 += 1
            prev = cur
        B2.append({"K": K, "集合全等周数": n3, "占比": n3 / (len(weeks) - 1),
                   "相对基线(0.365)变化": n3 / (len(weeks) - 1) - base_n3 / (len(weeks) - 1)})
    B2 = pd.DataFrame(B2)
    B2.to_csv(HERE / "B2_inmarket_constraint.csv", index=False)
    print("\n== B2. 分散约束形态（只换末位）的在场率代价（基线 = 0.365）==")
    print(B2.round(3).to_string(index=False))

    # ── C IC 标尺：全截面 vs 板块内（对下一周行业收益）──
    def next_ret(t):
        i = weeks.index(t)
        if i + 1 >= len(weeks):
            return None
        return px.loc[weeks[i + 1]] / px.loc[t] - 1

    C = []
    for K in K_GRID:
        lab, ic_raw, ic_in = lc[(K, "complete")], [], []
        for t in weeks[:-1]:
            key = score_of(mom, t, regime_of(reg, t))
            y = next_ret(t)
            lg = lab.loc[t]
            s = key.reindex(lg.index).astype(float)
            df = pd.DataFrame({"s": s, "y": y.reindex(lg.index).astype(float),
                               "g": lg.values}).dropna()
            if len(df) < 10:
                continue
            r1, _ = spearmanr(df["s"].values, df["y"].values)
            r2, _ = spearmanr(df.groupby("g")["s"].rank(pct=True).values, df["y"].values)
            if np.isfinite(r1) and np.isfinite(r2):
                ic_raw.append(r1)
                ic_in.append(r2)
        st = lambda v: (np.mean(v), np.mean(v) / (np.std(v, ddof=1) / np.sqrt(len(v))))
        m1, t1 = st(ic_raw)
        m2, t2 = st(ic_in)
        C.append({"K": K, "IC_全截面": m1, "t_全截面": t1, "IC_板块内": m2, "t_板块内": t2, "n周": len(ic_raw)})
    C = pd.DataFrame(C)
    C.to_csv(HERE / "C_ic.csv", index=False)
    print("\n== C. 排序 IC（对下一周行业收益，Spearman；越大越好）==")
    print(C.round(4).to_string(index=False))

    # ── D 聚类稳定性（ARI）──
    D = []
    for K in K_GRID:
        lab = lc[(K, "complete")]
        aris = [adjusted_rand_score(lab.loc[weeks[i]].values, lab.loc[weeks[i + 1]].values)
                for i in range(len(weeks) - 1)]
        D.append({"K": K, "ARI中位": np.median(aris), "ARI均值": np.mean(aris),
                  "ARI<0.5占比": np.mean(np.array(aris) < 0.5)})
    D = pd.DataFrame(D)
    D.to_csv(HERE / "D_ari.csv", index=False)
    print("\n== D. 相邻周聚类标签稳定性 ==")
    print(D.round(3).to_string(index=False))

    # ── E 簇均衡度（K × 链式）—— G2 的判据来源 ──
    E = []
    for (K, lg), lab in labs.items():
        maxshare = lab.apply(lambda r: r.value_counts().max() / n_ind, axis=1)
        E.append({"K": K, "链式": lg, "最大簇占比中位": float(maxshare.median()),
                  "最大簇占比P90": float(maxshare.quantile(.9)),
                  "半壁簇周占比": float((maxshare >= 0.5).mean())})
    E = pd.DataFrame(E).sort_values(["K", "链式"])
    E.to_csv(HERE / "E_balance.csv", index=False)
    print("\n== E. 簇均衡度（最大簇占行业数比例）==")
    print(E.round(3).to_string(index=False))

    # ── F 约束的触发面与替换代价（分散约束形态）──
    F, trig = [], []
    for K in K_GRID:
        lab = lc[(K, "complete")]
        maxshare = lab.apply(lambda r: r.value_counts().max() / n_ind, axis=1)
        n_bind = n_m = n_r = 0
        rows = []
        for t in weeks:
            top3 = planw.loc[t, "t3"]
            if len({lab.loc[t].get(x, -1) for x in top3}) != 1:
                continue
            rg = regime_of(reg, t)
            key = score_of(mom, t, rg)
            rk = key.rank(ascending=False)
            outside = rk[lab.loc[t] != lab.loc[t][top3[0]]].dropna()
            new, repl = top3_replaced(lab.loc[t], top3, key, "last")
            n_bind += 1
            n_m += rg == "momentum"
            n_r += rg == "reversal"
            rows.append({"周": str(t.date()), "regime": rg, "换入": repl,
                         "换入排名": float(outside.min()), "原第3名排名": float(rk[top3[2]]),
                         "最大簇占比": float(maxshare[t])})
            trig.append({"K": K, **rows[-1]})
        rf = pd.DataFrame(rows)
        F.append({"K": K, "触发周": n_bind, "触发占比": n_bind / len(weeks),
                  "动量周": n_m, "反转周": n_r,
                  "触发周最大簇占比中位": float(rf["最大簇占比"].median()) if len(rf) else np.nan,
                  "换入排名中位": float(rf["换入排名"].median()) if len(rf) else np.nan,
                  "换入排名最差": float(rf["换入排名"].max()) if len(rf) else np.nan,
                  "排名推后中位": float((rf["换入排名"] - rf["原第3名排名"]).median()) if len(rf) else np.nan})
    F = pd.DataFrame(F)
    F.to_csv(HERE / "F_replace_cost.csv", index=False)
    pd.DataFrame(trig).to_csv(HERE / "F_trigger_detail.csv", index=False)
    print("\n== F. 分散约束的触发面与替换代价 ==")
    print(F.round(3).to_string(index=False))

    # ── G 快照复现（K=5，距 2021-10-31 最近的信号日）──
    t_snap = [t for t in weeks if t <= pd.Timestamp("2021-10-31")][-1]
    snap = []
    for c in sorted(lc[(5, "complete")].loc[t_snap].unique()):
        lb = lc[(5, "complete")].loc[t_snap]
        snap.append({"簇": int(c), "行业数": int((lb == c).sum()),
                     "成员": "、".join(sorted(lb.index[lb.values == c]))})
    pd.DataFrame(snap).to_csv(HERE / "G_snapshot_K5.csv", index=False)
    print(f"\n== G. 快照 {t_snap.date()}（K=5）—— 对照原文 ==")
    for s in snap:
        print(f"  簇{s['簇']}（{s['行业数']}）: {s['成员']}")

    # ── H 触发例子（K=7，最自洽配置）──
    K_H = 7
    lab = lc[(K_H, "complete")]
    H = []
    for t in weeks:
        top3 = planw.loc[t, "t3"]
        if len({lab.loc[t].get(x, -1) for x in top3}) != 1:
            continue
        rg = regime_of(reg, t)
        key = score_of(mom, t, rg)
        new, repl = top3_replaced(lab.loc[t], top3, key, "last")
        if len(H) < 8:
            H.append({"周": str(t.date()), "regime": rg,
                      "原top3": "、".join(top3), "换入": repl, "新top3": "、".join(new)})
    H = pd.DataFrame(H)
    H.to_csv(HERE / "H_examples.csv", index=False)
    print(f"\n== H. 触发例子（K={K_H}，只换末位）==")
    print(H.to_string(index=False))

    # ── 事前判据判定 ──
    cand = F[F["K"] == K_H].iloc[0]
    e_cand = E[(E["K"] == K_H) & (E["链式"] == "complete")].iloc[0]
    # G5：快照复现原文的分组表述（真算，不硬编码）
    sl = lc[(5, "complete")].loc[t_snap]
    same = lambda names: len({sl.get(x, -99) for x in names}) == 1
    g5 = {"大金融(房地产/银行/非银金融)": same(["房地产", "银行", "非银金融"]),
          "周期(钢铁/煤炭同簇)": sl.get("钢铁") == sl.get("煤炭"),
          "消费链(食品饮料/家用电器/医药生物)": same(["食品饮料", "家用电器", "医药生物"])}
    n_g5 = int(sum(g5.values()))
    gates = [
        ("G1 触发面 ≥25 周", f"K={K_H}: {int(cand['触发周'])} 周（{cand['触发占比']:.1%}）",
         bool(cand["触发周"] >= 25)),
        ("G2 触发周最大簇占比 ≤50%", f"{cand['触发周最大簇占比中位']:.1%}",
         bool(cand["触发周最大簇占比中位"] <= 0.5)),
        ("G3 换入排名中位 ≤8/31", f"{cand['换入排名中位']:.0f}（最差 {cand['换入排名最差']:.0f}）",
         bool(cand["换入排名中位"] <= 8)),
        ("G4 ARI 中位 ≥0.70", f"{D[D['K']==K_H]['ARI中位'].iloc[0]:.3f}",
         bool(D[D["K"] == K_H]["ARI中位"].iloc[0] >= 0.7)),
        ("G5 快照复现原文 ≥2 处", f"{n_g5}/3 处：" + "、".join(k for k, v in g5.items() if v),
         bool(n_g5 >= 2)),
        ("G0 候选 K 的簇均衡度（E 表, K=7+全链）",
         f"最大簇占比中位 {e_cand['最大簇占比中位']:.1%}、半壁簇周 {e_cand['半壁簇周占比']:.1%}",
         bool(e_cand["最大簇占比中位"] <= 0.45)),
    ]
    G = pd.DataFrame(gates, columns=["门槛", "实测", "通过"])
    G.to_csv(HERE / "gates_summary.csv", index=False)
    print("\n== 事前判据 ==")
    print(G.to_string(index=False))
    ok = bool(G["通过"].all())
    print(f"\n{'✓ 全部门槛通过 → 允许申报 strategy_009（策略层仍须过引擎对照）' if ok else '✗ 有门槛未过 → 按预登记关闭这条线'}")

    build_view()


# ── 视图 ──
def _lay(title, height, xover=None, yover=None, **extra):
    """合并 LAYOUT 与轴覆盖（避免 update_layout 重复传 xaxis/yaxis 的坑）。"""
    d = dict(LAYOUT)
    d["title"] = title
    d["height"] = height
    if xover:
        d["xaxis"] = {**LAYOUT["xaxis"], **xover}
    if yover:
        d["yaxis"] = {**LAYOUT["yaxis"], **yover}
    d.update(extra)
    return d


def build_view():
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    A = pd.read_csv(HERE / "A_concentration.csv")
    C = pd.read_csv(HERE / "C_ic.csv")
    E = pd.read_csv(HERE / "E_balance.csv")
    F = pd.read_csv(HERE / "F_replace_cost.csv")
    G = pd.read_csv(HERE / "gates_summary.csv")
    trig = pd.read_csv(HERE / "F_trigger_detail.csv")
    figs = []

    # F1 top3 集中度（堆叠柱）
    f1 = go.Figure()
    for col, nm, cc in (("同簇", "三行业同簇", C1), ("两簇", "两簇", C2), ("三簇全异", "三簇全异", C3)):
        f1.add_trace(go.Bar(x=[f"K={k}" for k in A["K"]], y=A[col], name=nm, marker_color=cc,
                            hovertemplate="%{x} " + nm + "：%{y} 周<extra></extra>"))
    f1.update_layout(**_lay("A 基线 top3 的板块集中度（同簇 = 同质暴露）", 400,
                            yover={"title": "周数"}, barmode="stack", bargap=0.35))
    figs.append(f1)

    # F2 IC 全截面 vs 板块内（两色 + 直标）
    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=[f"K={k}" for k in C["K"]], y=C["IC_全截面"], name="全截面排序（现行做法）",
                            mode="lines+markers+text", text=[f"{v:+.4f}" for v in C["IC_全截面"]],
                            textposition="top center", textfont=dict(color=C_NEUTRAL, size=12),
                            line=dict(color=C1, width=2), marker=dict(size=10, color=C1)))
    f2.add_trace(go.Scatter(x=[f"K={k}" for k in C["K"]], y=C["IC_板块内"], name="板块内排序（重排形态）",
                            mode="lines+markers+text", text=[f"{v:+.4f}" for v in C["IC_板块内"]],
                            textposition="bottom center", textfont=dict(color=C_NEUTRAL, size=12),
                            line=dict(color=C2, width=2), marker=dict(size=10, color=C2)))
    f2.update_layout(**LAYOUT, height=420, title="C 排序 IC：板块内排序把信息削掉一半（预检否决重排形态）",
                     yaxis_title="Spearman IC（对下一周行业收益）")
    figs.append(f2)

    # F3 簇均衡度（K=5 vs K=7，全链；两块堆叠柱）
    e5 = E[(E["K"] == 5) & (E["链式"] == "complete")].iloc[0]
    e7 = E[(E["K"] == 7) & (E["链式"] == "complete")].iloc[0]
    f3 = go.Figure()
    for nm, cc, key in (("K=5（原文选择）", C1, 5), ("K=7（本分析建议）", C2, 7)):
        r = e5 if key == 5 else e7
        f3.add_trace(go.Bar(x=[nm], y=[r["最大簇占比中位"]], name="最大簇占比 中位",
                            marker_color=cc, text=[f"{r['最大簇占比中位']:.0%}"],
                            textposition="inside", showlegend=(key == 5),
                            hovertemplate="%{x}<br>最大簇占比中位 %{y:.1%}<extra></extra>"))
        f3.add_trace(go.Bar(x=[nm], y=[r["半壁簇周占比"]], name="半壁簇周占比",
                            marker_color=C3, text=[f"{r['半壁簇周占比']:.0%}"],
                            textposition="inside", showlegend=(key == 5),
                            hovertemplate="%{x}<br>半壁簇周占比 %{y:.1%}<extra></extra>"))
    f3.update_layout(**_lay("E 簇均衡度：K=5 有近半的周出现「半壁簇」→ 同簇语义失真", 400,
                            yover={"tickformat": ".0%", "title": "占比"},
                            barmode="group", bargap=0.4))
    figs.append(f3)

    # F4 触发面构成（动量/反转）
    f4 = go.Figure()
    f4.add_trace(go.Bar(x=[f"K={k}" for k in F["K"]], y=F["动量周"], name="动量周", marker_color=C1,
                        hovertemplate="%{x} 动量周 %{y}<extra></extra>"))
    f4.add_trace(go.Bar(x=[f"K={k}" for k in F["K"]], y=F["反转周"], name="反转周", marker_color=C2,
                        hovertemplate="%{x} 反转周 %{y}<extra></extra>"))
    f4.update_layout(**LAYOUT, barmode="stack", bargap=0.35, height=400,
                     title="F 分散约束的触发面：主要落在反转周（本项目证据最弱的一侧）",
                     yaxis_title="被改动的周数")
    figs.append(f4)

    # F5 替换代价（K=7 触发周）
    t7 = trig[trig["K"] == 7]
    f5 = go.Figure()
    f5.add_trace(go.Histogram(x=t7["换入排名"], nbinsx=12, marker_color=C1, opacity=0.9,
                              name="换入行业排名", hovertemplate="第 %{x} 名：%{y} 周<extra></extra>"))
    f5.add_vline(x=float(t7["换入排名"].median()), line_color=C2, line_width=2,
                 annotation_text=f"中位 {t7['换入排名'].median():.0f}/31", annotation_position="top right")
    f5.update_layout(**_lay("F 替换代价（K=7 触发周）：换入行业在全截面的排名分布", 400,
                            xover={"title": "全截面排名（1 = 最好）"}, yover={"title": "周数"},
                            bargap=0.06))
    figs.append(f5)

    # 表格视图
    def tbl(df, cols=None):
        d = df[cols] if cols else df
        head = "".join(f"<th>{c}</th>" for c in d.columns)
        rows = ""
        for r in d.itertuples(index=False):
            cells = ""
            for v in r:
                if isinstance(v, float):
                    cells += f"<td>{v:.4f}</td>" if abs(v) < 10 else f"<td>{v:.1%}</td>"
                else:
                    cells += f"<td>{v}</td>"
            rows += f"<tr>{cells}</tr>"
        return f"<table><tr>{head}</tr>{rows}</table>"

    fig_html = figs[0].to_html(full_html=False, include_plotlyjs=True) + "".join(
        f.to_html(full_html=False, include_plotlyjs=False) for f in figs[1:])
    ok = bool(G["通过"].all())
    verdict = ("✓ 事前门槛全部通过 → 允许申报 strategy_009（策略层仍须过引擎对照）"
               if ok else "✗ 有门槛未过 → 按预登记关闭这条线")
    html = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>analysis_020 — 行业聚类可行性预检</title>
<style>
 body{{font-family:"Microsoft YaHei",Arial,sans-serif;margin:24px;background:#fcfcfb;color:#0b0b0b}}
 h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px}}
 .note{{color:#52514e;font-size:13px;margin:8px 0 18px}}
 table{{border-collapse:collapse;margin:12px 0}} th,td{{border:1px solid #e4e8ee;padding:6px 10px;font-size:13px}}
 th{{background:#f3f5f8}} .verdict{{background:#fff4ee;border-left:4px solid {C2};padding:12px 16px;margin:16px 0}}
</style></head><body>
<h1>analysis_020 — 行业聚类（广发之十）能否改进本工程行业层</h1>
<div class="note">形态：<b>维持全截面排序不变，只在三个行业落进同一簇时把末位换成簇外最优</b>（分散约束）。
聚类口径：31 个 SW2021 一级行业 × 前 252 个交易日日收益率，余弦距离 + 全链，周频动态、无前视。</div>
<div class="verdict"><b>{verdict}</b><br>
★ 分析层通过 ≠ 策略层采纳：本分析全是行业层事件级证据，本工程已三度目睹「事件级成立 → 组合级失效」，
策略层必须过引擎对照（随机替换臂 / 留一 / 安慰剂 / 网格 + 在场率诊断）。</div>
{fig_html}
<h2>事前判据</h2>
{tbl(G)}
<h2>F 触发面与替换代价</h2>
{tbl(F)}
<h2>E 簇均衡度</h2>
{tbl(E)}
<h2>C 排序 IC</h2>
{tbl(C)}
<h2>A 集中度 / D 稳定性</h2>
{tbl(A)}
{tbl(pd.read_csv(HERE / "D_ari.csv"))}
<div class="note">产物：A~H 各 CSV · labels_K*_*.parquet（逐周标签，供后续迭代复用）· gates_summary.csv</div>
</body></html>"""
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(f"→ {HERE/'result_view.html'}（{len(figs)} 图）", flush=True)


if __name__ == "__main__":
    main()
