"""analysis_011 — 基线四因子分 regime 检验：动量周 vs 反转周各因子还灵不灵。

问题（用户 2026-10-15）：基线在动量周用的四因子是什么、表现如何？
事实先行：基线**方向不随 regime 切换**——动量周与反转周用同一套四因子、同样恒取 −1
（买弱）。方向镜像版（动量期取 +1）= strategy_001/002 迭代一，已测：收益更高、Sharpe 更低、
回撤更深（高收益高风险，未采用）。
所以本分析回答的是：**恒反转四因子拆开看，动量周里谁在赚钱、谁在拖后腿**——
病灶定位到因子级，为 strategy_007（反向量能闸门）之后的因子层改造供弹药。

口径（与 analysis_003 逐字一致，只多一个 regime 分组维度）：
  · 候选池：每周信号日 top3 行业内全部候选股；收益 = exec_open → 下一信号日 exec_open（开-开）
  · IC = 逐周截面 Spearman(因子 × (−1), 下周收益)；ICIR/t/Q5−Q1/单调性同 003
  · _score = 复合分（行业内 rank(pct)(−f) 均值，skipna）= 策略真实打分
  · regime 按信号日取自 weekly_plan（momentum: T′<0 / reversal: T′≥0）

用法：python analysis.py
产物：result_view.html + records.md（手写）+ factor_regime_table.csv
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

FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]
LABELS = {"turn_ratio": "换手比(5w/60w)", "px_ma20": "乖离MA20",
          "mom_20": "动量(20w)", "liq_amount": "均额(20w)", "_score": "复合分"}

C_BASE, C_6F = "#2a78d6", "#eb6834"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
SURFACE = "#fcfcfb"


def load_pool() -> pd.DataFrame:
    """003 同款候选池 + regime 标签（含 _score 复合分）。"""
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")

    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = panel.groupby("symbol", sort=False)
    panel["ret_ww"] = g["exec_open"].shift(-1) / panel["exec_open"] - 1
    sig = sorted(plan["signal_date"])
    nxt = dict(zip(sig, sig[1:]))
    nd = g["date"].shift(-1)
    panel.loc[nd.values != panel["date"].map(nxt).values, "ret_ww"] = np.nan

    panel_by_day = {d: x for d, g_ in panel.groupby("date") for d, x in [(d, g_)]}
    pools = []
    regime_of = dict(zip(plan["signal_date"], plan["regime"]))
    for r in plan.itertuples():
        day = panel_by_day.get(r.signal_date)
        if day is None:
            continue
        top3 = set(str(r.top3).split(","))
        sub = day[day["ind_name"].isin(top3)].copy()
        sub["regime"] = regime_of[r.signal_date]
        # 复合分（003 同款）：行业内 rank(pct)(−f) 的均值
        sub["_score"] = pd.concat([-sub[f].rank(pct=True) for f in FACTORS],
                                  axis=1).mean(axis=1, skipna=True)
        pools.append(sub)
    return pd.concat(pools, ignore_index=True)


def one_pass(df: pd.DataFrame, col: str) -> dict:
    """一个因子在一个子样本上的 003 口径指标（方向恒 −1 已并入）。"""
    d = df.dropna(subset=[col, "ret_ww"])
    ic = d.groupby("date").apply(
        lambda x: x[col].corr(x["ret_ww"], method="spearman")
        if len(x) >= 20 and x[col].nunique() > 3 else np.nan, include_groups=False).dropna()
    if len(ic) < 10:
        return {}
    q = d.groupby("date").apply(
        lambda x: x.assign(b=pd.qcut(x[col].rank(method="first", ascending=False), 5,
                                     labels=False) if x[col].notna().sum() >= 20 else None)
        .groupby("b")["ret_ww"].mean(), include_groups=False)
    spread = (q[4] - q[0]).mean() if q is not None and 4 in q and 0 in q else np.nan
    return {"IC": ic.mean(), "ICIR": ic.mean() / ic.std(ddof=1) if ic.std(ddof=1) else np.nan,
            "t": ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic)) if ic.std(ddof=1) else np.nan,
            "Q5Q1_bp": spread * 1e4, "n_week": len(ic), "n": len(d)}


def main():
    pool = load_pool()
    print(f"候选池 {len(pool):,} 行 / {pool['date'].nunique()} 周")
    rows = []
    for scope_name, sub in (("全部", pool), ("momentum", pool[pool["regime"] == "momentum"]),
                            ("reversal", pool[pool["regime"] == "reversal"])):
        for f in FACTORS + ["_score"]:
            m = one_pass(sub, f)
            if m:
                rows.append({"scope": scope_name, "factor": LABELS[f], **m})
    t = pd.DataFrame(rows)
    t.to_csv(HERE / "factor_regime_table.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 200)
    print(t.round(4).to_string(index=False))

    # 动量周专项：单因子方向翻转敏感性（若把某因子在动量周取 +1 会怎样）
    print("\n动量周方向翻转敏感性（同一因子、方向取 +1 的 IC）：")
    pool_m = pool[pool["regime"] == "momentum"]
    flip = []
    for f in FACTORS:
        d = pool_m.dropna(subset=[f, "ret_ww"])
        ic = d.groupby("date").apply(
            lambda x: (-x[f]).corr(x["ret_ww"], method="spearman")
            if len(x) >= 20 and x[f].nunique() > 3 else np.nan, include_groups=False).dropna()
        flip.append({"factor": LABELS[f], "IC_pos_dir": -ic.mean(),
                     "t_pos_dir": -ic.mean() / ic.std(ddof=1) * np.sqrt(len(ic))})
    fl = pd.DataFrame(flip)
    print(fl.round(4).to_string(index=False))

    # ── 动量周头部预检（用户设想一 vs 证据对齐变体 vs 基线；008 头部检验口径）──
    print("\n动量周头部预检：各选股设计的 top2 下周收益（≥2017-05-12）：")
    CUTd = pd.Timestamp("2017-05-12")
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])

    def top2(sub, factors):
        sc = pd.concat([-sub[f].rank(pct=True) for f in factors], axis=1).mean(axis=1, skipna=True)
        s = sub.assign(_s=sc).dropna(subset=["_s"]).sort_values(
            ["_s", "symbol"], ascending=[False, True])
        return s["symbol"].tolist()[:2]

    hd = []
    for r in plan[plan["signal_date"] >= CUTd].itertuples():
        if r.regime != "momentum":
            continue
        day = pool[pool["date"] == r.signal_date]
        fwd = dict(zip(day["symbol"], day["ret_ww"]))
        for ind in str(r.top3).split(","):
            sub = day[(day["ind_name"] == ind)].dropna(subset=["ret_ww"])
            if len(sub) < 12:
                continue
            base = top2(sub, FACTORS)
            f3 = top2(sub, ["turn_ratio", "px_ma20", "mom_20"])
            f2 = top2(sub, ["turn_ratio", "px_ma20"])
            # 用户设想一：漏斗 = mom_20(+1) 前 10 → 换手/乖离(−1) 拥挤度最低 2 只
            s1 = sub.dropna(subset=["mom_20"]).sort_values(["mom_20", "symbol"], ascending=[False, True])
            surv = sub[sub["symbol"].isin(s1["symbol"].tolist()[:10])]
            fun = top2(surv, ["turn_ratio", "px_ma20"]) if len(surv) else []
            if base and f3:
                hd.append({"r_base": np.mean([fwd[s] for s in base if s in fwd]),
                           "r_3f": np.mean([fwd[s] for s in f3 if s in fwd]),
                           "r_2f": np.mean([fwd[s] for s in f2 if s in fwd]),
                           "r_funnel": np.mean([fwd[s] for s in fun if s in fwd]) if fun else np.nan})
    h = pd.DataFrame(hd)
    for col, lab in (("r_base", "基线四因子(−1)"), ("r_3f", "三因子 换手/乖离/动量(−1, 剔liq)"),
                     ("r_2f", "两因子 换手/乖离(−1)"), ("r_funnel", "设想一漏斗(动量+1→拥挤−1)")):
        vs = (h[col] - h["r_base"]).dropna()
        print(f"  {lab:<30s} {h[col].mean():+.4%}/周  胜率 {(h[col] > 0).mean():.0%}"
              f"  vs基线 {vs.mean():+.4%}  对基线胜率 {(vs > 0).mean():.0%}"
              + (f"（n={len(vs)}）" if col != "r_base" else ""))
    h.to_csv(HERE / "head_test_momentum.csv", index=False, encoding="utf-8-sig")

    html = build_view(t, fl)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print("完成。")


def build_view(t: pd.DataFrame, fl: pd.DataFrame) -> str:
    import plotly.graph_objects as go
    LAY = dict(font=dict(family="Arial,'Microsoft YaHei',sans-serif", color=INK2, size=13),
               paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
               xaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               yaxis=dict(gridcolor=GRID, zerolinecolor=GRID),
               margin=dict(l=56, r=24, t=56, b=44), showlegend=True)

    f1 = go.Figure()
    for scope, color in (("momentum", C_6F), ("reversal", C_BASE), ("全部", MUTED)):
        s = t[t["scope"] == scope]
        f1.add_trace(go.Bar(x=s["factor"], y=s["IC"], name=f"{scope}(n={int(s['n_week'].iloc[0])})",
                            marker_color=color))
    f1.update_layout(height=380, barmode="group", **LAY,
                     title="图1 · 各因子方向化 IC：动量周 vs 反转周 vs 全部（003 同口径，恒 −1 方向）")
    f1.update_yaxes(title_text="方向化 IC")

    f2 = go.Figure()
    for scope, color in (("momentum", C_6F), ("reversal", C_BASE), ("全部", MUTED)):
        s = t[t["scope"] == scope]
        f2.add_trace(go.Bar(x=s["factor"], y=s["Q5Q1_bp"], name=scope, marker_color=color))
    f2.update_layout(height=380, barmode="group", **LAY,
                     title="图2 · Q5−Q1 分位价差（bp/周，正=策略方向赚钱）")
    f2.update_yaxes(title_text="bp/周")

    tbl = go.Figure(go.Table(
        header=dict(values=list(t.columns), fill_color="#f3f5f8"),
        cells=dict(values=[t[c] for c in t.columns], height=24)))
    tbl.update_layout(title="因子 × regime 完整表", height=240 + 24 * len(t))

    parts = "".join(f"<div class='fig'>{f.to_html(full_html=False, include_plotlyjs=(i == 0))}</div>"
                    for i, f in enumerate([f1, f2, tbl]))
    css = f"""
    <style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      h2 {{ color:{INK}; }} .fig {{ margin:8px 0 28px 0; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_011 — 基线四因子分 regime 检验（动量周 vs 反转周）</h2>{parts}</body></html>")


if __name__ == "__main__":
    main()
