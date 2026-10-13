"""analysis_005 — 全库因子扫描：在「策略真实执行条件」下找比基线四因子更好的因子。

承接四步计划：analysis_003（基线四因子强度标尺）→ analysis_004（随机对照，证明选股层有真实 alpha）
→ **analysis_005 = 第 3 步：候选筛选（遍历 QuantSkills 库全部 512 个因子）**。

口径（逐字沿用 analysis_003，不改）：
  · 池：每周当周 top3 行业内候选股（`analysis_003.load_pool`），154,548 行 / 494 信号日 / 313 只·周
  · 收益：池内 ret_ww = exec_open(t) → exec_open(下一信号日) 的开-开周收益
  · 指标：逐周截面 Spearman 方向化 IC / ICIR / t / |IC|≥0.02 占比 / 五分位单调性 ρ / 累计 IC 拟合

已定口径（用户 2026-10-13）：
  · **方向**：每因子取 |IC| 更强的方向（= 让 IC 均值为正的符号）；★ 样本内选择，报告中明写。
    ★★ 注意：IC/ICIR/t/|ρ|/|IC|≥0.02 占比/R² **全部与方向无关**（翻符号只翻 IC 的正负，不改绝对值），
       所以"取更强方向"对**这六项判定**其实没有影响——只有绘制 IC 曲线/年度正负时才用到符号。
  · **入选门槛**：六项指标逐项与**最强的基线因子**比（严格大于），**至少过 3 项**
  · **正交**：与基线四因子（方向化）+ 复合分、以及其他入选者的池内逐周截面 Spearman 均值
           |ρ| < 0.7 才保留；≥0.7 视为冗余 → 只留指标更好的

产物（本目录）：scan_metrics.csv / candidates.csv / orthogonality.csv / finalists.csv /
                result_view.html / records.md
用法：python analysis.py
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
A003 = PROJ / "01_data_analysis" / "analysis_003" / "analysis.py"
REPO = PROJ.parents[1]
DB = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

BASELINE = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]     # 基线四因子（策略方向 −1）
BASE_LBL = {"turn_ratio": "换手比(5/60周)", "px_ma20": "乖离MA20(20周)",
            "mom_20": "动量(20周)", "liq_amount": "均额(20周)", "_score": "复合分"}
CRIT = ["IC绝对值", "ICIR绝对值", "t绝对值", "单调性ρ绝对值", "|IC|≥0.02占比", "累计IC_R2"]
K_PASS = 3          # 六项里至少过几项 → 入选候选
RHO_MAX = 0.7       # 正交阈值：|ρ| ≥ 0.7 视为冗余


def load_mod(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ═══════════════════ ① 数据 ═══════════════════
def load_all(a003, bfw) -> tuple[pd.DataFrame, dict]:
    pool = a003.load_pool()
    con = duckdb.connect(str(DB), read_only=True)
    fcols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='v_factor_1w'").fetchall()
        if r[0] not in ("date", "instrument", "year")]
    con.register("k", pool[["date", "symbol"]].rename(columns={"symbol": "instrument"}))
    sel = ", ".join(f'f."{c}"' for c in fcols)
    got = con.execute(f"""
        SELECT f.date, f.instrument AS symbol, {sel}
        FROM v_factor_1w f JOIN k ON f.instrument = k.instrument AND f.date = k.date
    """).df()
    con.close()
    got["date"] = pd.to_datetime(got["date"])
    print(f"并入库因子 {len(fcols)} 列：池内 {len(pool):,} 行，命中 {len(got):,}（{len(got)/len(pool):.1%}）")
    for c in fcols:
        got[c] = got[c].astype("float32")
    pool = pool.merge(got, on=["date", "symbol"], how="left")

    meta = {}
    for lib in ("dir", "volstat"):
        for s in bfw.load_specs(lib):
            col = f"{s['base']}_{int(s['params'].get('window', 20))}w_{s['transform']}"
            meta[col] = {"库": lib, "因子ID": s["factor_id"], "中文名": s.get("name_cn", ""),
                         "算法公式": s.get("formula_cn", ""), "base": s["base"],
                         "window": int(s["params"].get("window", 20)), "transform": s["transform"]}
    return pool, meta, fcols


# ═══════════════════ ② 指标（向量化）═══════════════════
def ic_by_date(rank_v, rr_v, codes, K):
    """逐日 Spearman(rank(f), rank(ret))。秩在整列上算 → 与 pandas corr(spearman) 同义。"""
    m = ~np.isnan(rank_v) & ~np.isnan(rr_v)
    c, x, y = codes[m], rank_v[m], rr_v[m]
    n = np.bincount(c, minlength=K).astype(float)
    sx = np.bincount(c, weights=x, minlength=K); sy = np.bincount(c, weights=y, minlength=K)
    sxx = np.bincount(c, weights=x * x, minlength=K); syy = np.bincount(c, weights=y * y, minlength=K)
    sxy = np.bincount(c, weights=x * y, minlength=K)
    with np.errstate(invalid="ignore", divide="ignore"):
        num = sxy - sx * sy / n
        den = np.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n))
        ic = num / den
    ic[(n < 3) | (den == 0)] = np.nan
    return ic


def quintile_rho(v, ret_v, codes, K, sign, q=5):
    """池内五分位（按因子秩切）平均下周收益的单调性 ρ（池化口径，同 analysis_003）。

    ★ 秩在**掩码子集内**现算（因子与收益都非空的行）—— 否则「整列秩 ÷ 掩码内 n」> 1，
      最后一组会吞掉溢出行、ρ 假性 = 1.0（踩过）。
    ★ 方向用 sign 处理：反向后秩 = (组内 n + 1) − 秩；直接取 −秩 会把百分位 clip 进第 1 组（也踩过）。
    """
    m = ~np.isnan(v) & ~np.isnan(ret_v)
    if m.sum() < 50:
        return np.nan
    rk = pd.Series(v[m]).groupby(codes[m]).rank().to_numpy()             # 掩码子集内的秩
    cnt = np.bincount(codes[m], minlength=K).astype(float)[codes[m]]     # 组内 n
    eff = rk if sign > 0 else (cnt + 1.0 - rk)
    qi = np.clip(np.ceil(eff / cnt * q).astype(int), 1, q) - 1
    code2 = codes[m] * q + qi
    s = np.bincount(code2, weights=ret_v[m], minlength=K * q).reshape(K, q)
    c2 = np.bincount(code2, minlength=K * q).reshape(K, q).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        qm = np.nansum(s, axis=0) / np.where(c2.sum(axis=0) > 0, c2.sum(axis=0), np.nan)
    ok = ~np.isnan(qm)
    if ok.sum() < 3:
        return np.nan
    # ★ 与 analysis_003 一致：**Pearson**（组号 vs 组均收益）—— 不是 Spearman。
    #   （Spearman 在严格单调时恒 = 1.0，会把这个指标变成死门槛；Pearson 才反映"接不接近直线"。）
    return float(pd.Series(qm[ok]).corr(pd.Series(np.arange(q)[ok].astype(float))))


def metrics_of(v, rr_v, codes, K, ret_v, uniq, sign=None):
    """六项指标（+ 若干辅助）。`sign=None` ⇒ **自动取 |IC| 更强的方向**（= 让 IC 均值为正）；
    给具体 ±1 ⇒ 用该固定方向（基线四因子 = −1，复合分 = +1）。
    返回 (指标 dict, 方向化 IC 序列, 整列秩向量)。"""
    rank_v = pd.Series(v).groupby(codes).rank().to_numpy()                # 整列秩（对齐 pandas IC）
    ic = ic_by_date(rank_v, rr_v, codes, K)
    if sign is None:
        sign = 1 if np.nanmean(ic) >= 0 else -1
    s = pd.Series(sign * ic, index=uniq).dropna()
    if len(s) < 10:
        return None, None, rank_v
    mean, sd = s.mean(), s.std()
    cum = s.cumsum().to_numpy()
    ti = np.arange(len(cum))
    r2 = (1 - ((cum - np.polyval(np.polyfit(ti, cum, 1), ti)) ** 2).sum()
          / ((cum - cum.mean()) ** 2).sum()) if cum.std() > 0 else np.nan
    rho = quintile_rho(v, ret_v, codes, K, sign)
    yr = s.groupby(s.index.year).mean()
    d = {"方向": sign, "IC周数": len(s), "IC均值": mean, "ICIR": mean / sd if sd else np.nan,
         "t值": mean / sd * np.sqrt(len(s)) if sd else np.nan,
         "|IC|≥0.02占比": float((s.abs() >= 0.02).mean()),
         "累计IC终值": float(cum[-1]), "累计IC_R2": r2, "单调性ρ": rho,
         "IC绝对值": abs(mean), "ICIR绝对值": abs(mean / sd) if sd else np.nan,
         "t绝对值": abs(mean / sd * np.sqrt(len(s))) if sd else np.nan,
         "单调性ρ绝对值": abs(rho) if rho == rho else np.nan,
         "年度IC为正年数": int((yr > 0).sum()), "年度数": len(yr)}
    return d, s, rank_v


def prep(pool):
    codes, uniq = pd.factorize(pool["date"])
    codes = np.asarray(codes)
    uniq = pd.DatetimeIndex(uniq)
    ret_v = pool["ret_ww"].to_numpy(dtype=float)
    rr_v = pd.Series(ret_v).groupby(codes).rank().to_numpy()
    return codes, uniq, ret_v, rr_v


# ═══════════════════ ③ 正交（逐周截面 Spearman 均值）═══════════════════
def cross_rank(rank_v, other_rank_v, codes, K):
    """两个已方向化的秩向量 → 池内逐周截面 Spearman 的均值。"""
    m = ~np.isnan(rank_v) & ~np.isnan(other_rank_v)
    c, x, y = codes[m], rank_v[m], other_rank_v[m]
    n = np.bincount(c, minlength=K).astype(float)
    sx = np.bincount(c, weights=x, minlength=K); sy = np.bincount(c, weights=y, minlength=K)
    sxx = np.bincount(c, weights=x * x, minlength=K); syy = np.bincount(c, weights=y * y, minlength=K)
    sxy = np.bincount(c, weights=x * y, minlength=K)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = (sxy - sx * sy / n) / np.sqrt((sxx - sx * sx / n) * (syy - sy * sy / n))
    r[(n < 3)] = np.nan
    return float(np.nanmean(r))


# ═══════════════════ ④ 主流程 ═══════════════════
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None,
                    help="只跑单个因子列（先把整条流程冒烟跑通，再全量）；产物另存 smoke_* 不覆盖正式件")
    a = ap.parse_args()
    tag = "smoke_" if a.only else ""

    t0 = time.time()
    a003 = load_mod(A003, "a003")
    bfw = load_mod(REPO / "data_cache/bigquant_warehouse/build_factor_weekly.py", "bfw")
    pool, meta, fcols = load_all(a003, bfw)
    codes, uniq, ret_v, rr_v = prep(pool)
    K = len(uniq)

    # ── 扫库因子（--only 时只扫一个，用于流程冒烟）──
    lib_cols = [c for c in sorted(meta) if c in pool.columns]
    if a.only:
        assert a.only in lib_cols, f"{a.only} 不在库里（共 {len(lib_cols)} 个）"
        lib_cols = [a.only]
        print(f"★ 冒烟模式：只跑 {a.only}")
    rows, ic_store, rank_store = [], {}, {}
    print(f"待扫 {len(lib_cols)} 个库因子 …")
    for i, col in enumerate(lib_cols):
        d, s, rv = metrics_of(pool[col].to_numpy(dtype=float), rr_v, codes, K, ret_v, uniq, None)
        if d is None:
            continue
        rows.append({"列名": col, "类型": "库因子", **meta[col], **d})
        ic_store[col], rank_store[col] = s, rv
        if (i + 1) % 64 == 0:
            print(f"    {i+1}/{len(lib_cols)} … {time.time()-t0:.0f}s", flush=True)
    scan = pd.DataFrame(rows).set_index("列名")

    # ── 基线四因子（方向 −1）+ 复合分（方向 +1）──
    base_rows = {}
    for c in BASELINE + ["_score"]:
        sg = 1 if c == "_score" else -1
        d, s, rv = metrics_of(pool[c].to_numpy(dtype=float), rr_v, codes, K, ret_v, uniq, sg)
        base_rows[c] = d
        ic_store[c], rank_store[c] = s, rv
    print(f"\n扫描完成 {time.time()-t0:.0f}s；基线四因子 + 复合分已算")

    # ── 回归锚点：必须等于 analysis_003 ──
    anchor = {"px_ma20": 0.0605, "turn_ratio": 0.0520, "mom_20": 0.0387, "liq_amount": 0.0290,
              "_score": 0.0598}
    bad = {k: (round(base_rows[k]["IC均值"], 4), v) for k, v in anchor.items()
           if abs(base_rows[k]["IC均值"] - v) > 1e-3}
    assert not bad, f"✗ 与 analysis_003 锚点不符 {bad}"
    rho_anchor = {"px_ma20": 0.973, "turn_ratio": 0.889, "mom_20": 0.969,
                  "liq_amount": 0.846, "_score": 0.967}
    rho_bad = {k: (round(base_rows[k]["单调性ρ"], 3), v) for k, v in rho_anchor.items()
               if abs(abs(base_rows[k]["单调性ρ"]) - v) > 0.03}
    print("✓ 回归锚点通过（IC 与 analysis_003 一致）；单调性 ρ 对照：" +
          " / ".join(f"{k} {abs(base_rows[k]['单调性ρ']):.3f}(原 {v})" for k, v in rho_anchor.items()))
    if rho_bad:
        print(f"  ⚠ ρ 与 analysis_003 有出入（分箱口径微差）：{rho_bad}")

    # ── Step 2 比较：六项逐项 vs 最强基线 ──
    best = {c: max(base_rows[b][c] for b in BASELINE) for c in CRIT}
    print("\n② 最强基线（六项门槛）：" + " / ".join(f"{c} {best[c]:.4f}" for c in CRIT))
    scan["通过项数"] = [sum(scan.loc[i, k] > best[k] for k in CRIT) for i in scan.index]
    scan["通过指标"] = [",".join(k for k in CRIT if scan.loc[i, k] > best[k]) for i in scan.index]
    scan.to_csv(HERE / f"{tag}scan_metrics.csv", encoding="utf-8-sig")
    print(f"① scan_metrics.csv：{len(scan)} 个库因子 × {scan.shape[1]} 列")
    cand = scan[scan["通过项数"] >= K_PASS].copy()
    # 强度分（六项在全库 512 个里的百分位均值）→ 正交环节「相关就留更好的」的判据
    cand["强度分"] = scan[CRIT].rank(pct=True).mean(axis=1).reindex(cand.index)
    cand = cand.sort_values(["通过项数", "强度分"], ascending=False)
    cand.to_csv(HERE / f"{tag}candidates.csv", encoding="utf-8-sig")
    print(f"   入选候选（过 ≥{K_PASS} 项）：{len(cand)} 个 → candidates.csv")

    # ── Step 3 正交 ──
    base_ranked = {c: rank_store[c] if c == "_score" else -rank_store[c]
                   for c in BASELINE + ["_score"]}
    bl = BASELINE + ["_score"]
    ortho = pd.DataFrame(index=cand.index, columns=[BASE_LBL[c] for c in bl], dtype=float)
    for c in cand.index:
        rv = rank_store[c] if cand.loc[c, "方向"] > 0 else -rank_store[c]
        for b in bl:
            ortho.loc[c, BASE_LBL[b]] = cross_rank(rv, base_ranked[b], codes, K)
    ortho["与基线最大|ρ|"] = ortho.abs().max(axis=1)
    # 候选×候选
    cand_ranked = {c: (rank_store[c] if cand.loc[c, "方向"] > 0 else -rank_store[c]) for c in cand.index}
    cc = pd.DataFrame(index=cand.index, columns=cand.index, dtype=float)
    for a in cand.index:
        for b in cand.index:
            cc.loc[a, b] = 1.0 if a == b else cross_rank(cand_ranked[a], cand_ranked[b], codes, K)
    ortho.to_csv(HERE / f"{tag}orthogonality.csv", encoding="utf-8-sig")
    cc.to_csv(HERE / f"{tag}orthogonality_candidates.csv", encoding="utf-8-sig")

    # ── 贪心：按强度分**从高到低**过一遍 ⇒ 互相冗余时**先到（更强）的留下**，
    #    即「相关性大就选绩效更好的」这条原则（下面有自检断言）──
    keep, dropped = [], []
    for c in cand.sort_values("强度分", ascending=False).index:
        if ortho.loc[c, "与基线最大|ρ|"] >= RHO_MAX:
            dropped.append((c, f"与基线 ρ={ortho.loc[c,'与基线最大|ρ|']:.2f}", None)); continue
        dup = next((k for k in keep if abs(cc.loc[c, k]) >= RHO_MAX), None)
        if dup is not None:
            # 自检：留下的（dup）必须比被剔的（c）强度分更高？——不是的话就是排序/逻辑错了
            w = cand.loc[dup, "强度分"] >= cand.loc[c, "强度分"]
            dropped.append((c, f"与已选 {dup} ρ={abs(cc.loc[c,dup]):.2f}"
                             f"（强度分 {cand.loc[c,'强度分']:.3f} vs {cand.loc[dup,'强度分']:.3f}"
                             f"{'✓留强者' if w else '✗异常'}）", dup))
            assert w, f"✗ 「留更好的」规则失效：{c} 比 {dup} 更强却被剔"
            continue
        keep.append(c)
    fin = cand.loc[keep].sort_values("强度分", ascending=False)
    fin.to_csv(HERE / f"{tag}finalists.csv", encoding="utf-8-sig")
    print(f"   正交后保留 {len(keep)} 个（剔除 {len(dropped)}）：")
    for c, why, _ in dropped:
        print(f"     − {c}  {why}")
    print(f"   → finalists.csv")

    # ── Step 4 图表 ──
    render(scan, base_rows, cand, fin, ic_store, ortho, bl, best, tag)
    print(f"\n完成 {time.time()-t0:.0f}s")
    return 0


def render(scan, base_rows, cand, fin, ic_store, ortho, bl, best, tag):
    import plotly.graph_objects as go

    def tbl(df, title, h=None):
        d = df.reset_index()
        fig = go.Figure(go.Table(
            header=dict(values=list(d.columns), fill_color="#f3f5f8", align="left"),
            cells=dict(values=[d[c].round(4) if d[c].dtype.kind == "f" else d[c] for c in d.columns],
                       align="left", height=26)))
        fig.update_layout(title=title, height=h or 220 + 28 * len(d))
        return fig

    # ① 512 因子 IC 排序（标出基线）
    top = scan.sort_values("IC绝对值", ascending=False)
    fig1 = go.Figure(go.Bar(x=top.index, y=top["IC绝对值"], marker_color="#7fb3d5", name="库因子"))
    for b in bl:
        fig1.add_hline(y=abs(base_rows[b]["IC均值"]),
                       line=dict(color="crimson", dash="dot"),
                       annotation_text=BASE_LBL[b], annotation_position="top left")
    fig1.update_layout(title="① 512 个库因子 IC 绝对值排序（红线 = 基线四因子 + 复合分）",
                       template="plotly_white", height=520, xaxis=dict(showticklabels=False,
                                                                      title="因子（按 IC 降序）"))
    # ② 六项对比：候选 vs 最强基线
    cols = ["IC绝对值", "ICIR绝对值", "t绝对值", "单调性ρ绝对值", "|IC|≥0.02占比", "累计IC_R2"]
    lab = ["IC绝对值", "ICIR", "t", "单调性ρ", "|IC|≥0.02", "累计IC R²"]
    fig2 = go.Figure()
    fig2.add_bar(name="最强基线", x=lab, y=[best[c] for c in cols], marker_color="crimson")
    for c in fin.index[:6]:
        fig2.add_bar(name=c, x=lab, y=[fin.loc[c, k] for k in cols])
    fig2.update_layout(title="② 最终入选 vs 最强基线（每项须严格超过红线才算过）",
                       barmode="group", template="plotly_white", height=520)

    # ③ 累计 IC 曲线：入选 + 基线
    fig3 = go.Figure()
    for b in bl:
        s = base_rows[b]
        fig3.add_scatter(x=ic_store[b].index, y=ic_store[b].cumsum(), name=f"基线 {BASE_LBL[b]}",
                         line=dict(dash="dot"))
    for c in fin.index:
        fig3.add_scatter(x=ic_store[c].index, y=ic_store[c].cumsum(), name=c)
    fig3.update_layout(title="③ 累计 IC（候选池内 · 周频 · 方向化）", template="plotly_white",
                       height=560, hovermode="x unified")

    # ④ 正交热力图
    fig4 = go.Figure(go.Heatmap(z=ortho[[BASE_LBL[b] for b in bl]].values,
                                x=[BASE_LBL[b] for b in bl], y=list(ortho.index),
                                colorscale="RdBu_r", zmid=0, zmin=-1, zmax=1,
                                text=np.round(ortho[[BASE_LBL[b] for b in bl]].values, 2),
                                texttemplate="%{text}"))
    fig4.update_layout(title=f"④ 正交热力图（入选 × 基线；|ρ|≥{RHO_MAX} 判冗余）",
                       template="plotly_white", height=200 + 26 * len(ortho))

    figs = [("① IC 排序（512 因子里基线在哪）", fig1),
            ("② 入选 vs 最强基线（六项）", fig2),
            ("③ 累计 IC 曲线", fig3),
            ("④ 正交热力图", fig4),
            ("⑤ 入选名单", tbl(fin[["因子ID", "中文名", "算法公式", "方向", "通过项数"] + cols],
                                "⑤ 最终入选名单（因子ID / 名称 / 算法公式 / 六项指标）", None)),
            ("⑥ 全部候选", tbl(cand[["因子ID", "中文名", "算法公式", "方向", "通过项数", "通过指标"] + cols],
                                f"⑥ 候选清单（过 ≥{K_PASS} 项，共 {len(cand)} 个）", None))]
    parts = ["<h2>analysis_005 — 全库 512 因子扫描（候选池内 · 周频 · 开-开收益）</h2>"]
    for k, (name, f) in enumerate(figs):
        parts.append(f"<h3>{name}</h3>" + f.to_html(full_html=False, include_plotlyjs=(k == 0)))
    (HERE / f"{tag}result_view.html").write_text(
        '<html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
        + "".join(parts) + "</body></html>", encoding="utf-8")
    print("④ result_view.html 已写（6 张图）")


if __name__ == "__main__":
    raise SystemExit(main())
