"""analysis_018 — 「长期底部 + 短期动量」双条件行业轮动：**分市场状态**检验（熊市是否可行）

**来源**：广发 2022-02-25《考虑预期改善及底部特征的行业轮动策略》
（提取件 `research_report/行业轮动框架-广发/expectation_improvement_bottom_feature_guangfa_20220225_main.md`）。
原文四因子取交集：长期均线（底部）后 40 / 短期均线（动量）前 35 / 一致预期 ROE 增速前 40 / 资金流向前 35。

**本分析的取舍**：
  · **只用前两个因子**（长期底部 + 短期动量）—— 后两个（一致预期 ROE、北上资金/净主动买入额）
    **本地无数据**（见提取件 §7），用户指示本轮先不看。
  · 行业池：申万 **L1 31 个**（主，有真实指数 close）；**L2 125 个**（稳健性，由成分股等权日收益复利合成）。
  · **★ 硬约束**：报告原参数 MA1100 ≈ 4.4 年，本地行业数据 2015-01 起 ⇒ MA1100 首个有效日 **2019-07-09**，
    原参数样本只有 **86 期**。故并列一个**等比缩短版**（长期 60/360、短期 20/90，比例同原文 1:6 / 1:4.5）
    以覆盖 2016-06 起（115 期）。

**核心问题（用户）**：**熊市环境下这个思路可行吗？** 熊市 = 沪深300 收盘 < MA200。

**检验**：
  A. 双条件策略的分市场状态表现（全期 / 牛市 / 熊市）：平均超额、胜率、期数
  B. 单条件对照：只长期底部 / 只短期动量 / 双条件
  C. 随机对照：随机选同样多行业 × 20 种子（分市场状态）
  D. 参数稳健性：窗口（原比例 vs 缩短）× 分位（后/前 1/3、1/2）
  E. L2 池稳健性

**口径铁律**：所有指标在信号日 t 只用 ≤t 数据（MA、排名、市场状态都用 t 日收盘）；
  收益为 t → t+1 月末；空集按原文口径**配全行业等权**（此时超额记 0）。
  无交易成本（原文亦未提）。**只做观测，不改任何冻结件。**

用法：python analysis.py
产物：perf_by_state.csv / param_grid.csv / result_view.html（records.md 手写）
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
CACHE = PROJ / "shared" / "_cache"
REPO = PROJ.parents[1]
DB = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

# 视图配色（与 009/016/017 同一套）
C_BASE, C_ALT, C_POS, C_NEG = "#2a78d6", "#eb6834", "#2a78d6", "#e34948"
INK, INK2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"

# 报告的筛选比例：82 个池 → 长期后 40（48.8%）、短期前 35（42.7%）
Q_LONG, Q_SHORT = 0.488, 0.427
# 报告原参数（长期 180/1100，短期 40/180）与等比缩短版
PARAMS = {
    "原参数 180/1100 + 40/180": dict(L1=180, L2=1100, S1=40, S2=180),
    "缩短版 60/360 + 20/90":   dict(L1=60, L2=360, S1=20, S2=90),
}


def load_l1() -> pd.DataFrame:
    d = pd.read_parquet(CACHE / "industry_index.parquet")
    d["date"] = pd.to_datetime(d["date"])
    return d.pivot(index="date", columns="ind_name", values="close").sort_index()


def load_l2() -> pd.DataFrame:
    """L2 无 close，只有等权日收益 → 复利合成指数；并过滤覆盖不足/成分股太少的行业。"""
    d = pd.read_parquet(CACHE / "industry_l2_daily.parquet")
    d["date"] = pd.to_datetime(d["date"])
    px_cnt = d.pivot_table(index="date", columns="l2", values="ret").sort_index()
    n_cnt = d.pivot_table(index="date", columns="l2", values="n").sort_index()
    keep = [c for c in px_cnt.columns
            if px_cnt[c].notna().mean() >= 0.98 and n_cnt[c].mean() >= 8]
    px_cnt = px_cnt[keep].fillna(0.0)
    return (1 + px_cnt).cumprod()


def market_state(ds: pd.DatetimeIndex) -> pd.Series:
    """熊市 = 沪深300 收盘 < MA200（信号日 t 收盘口径，无前视）。"""
    con = duckdb.connect(str(DB), read_only=True)
    hs = con.execute("SELECT date, close FROM index_bar1d WHERE instrument='000300.SH' "
                     "ORDER BY date").fetchdf()
    con.close()
    hs["date"] = pd.to_datetime(hs["date"])
    s = hs.set_index("date")["close"].sort_index()
    ma = s.rolling(200, min_periods=200).mean()
    st = s.reindex(ds).ffill()
    m = ma.reindex(ds).ffill()
    return (st < m)          # True = 熊市


def monthly_signals(px: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(px.index.to_series().groupby(px.index.to_period("M")).last().values)


def eval_rule(px: pd.DataFrame, sig_dates, long_sel, short_sel, use_long=True,
              use_short=True, n_seed=0, seed=20261016, q_long=Q_LONG, q_short=Q_SHORT):
    """返回逐期明细 DataFrame。

    选行业：长期因子比值 **后 q_long** 名 ∩ 短期因子比值 **前 q_short** 名（交集）。
    下期收益 = px[t_next]/px[t] − 1（等权平均）。超额 = 组合 − 全行业等权。
    """
    L, Sm = long_sel, short_sel
    rng = np.random.default_rng(seed)
    rows = []
    for i, t in enumerate(sig_dates[:-1]):
        tn = sig_dates[i + 1]
        if t not in px.index or tn not in px.index:
            continue
        fL, fS = L.loc[t].dropna(), Sm.loc[t].dropna()
        if len(fL) < 10 or len(fS) < 10:
            continue
        nL = max(1, int(round(len(fL) * q_long)))
        nS = max(1, int(round(len(fS) * q_short)))
        if use_long:
            cand = set(fL.nsmallest(nL).index)           # 底部：比值小
        else:
            cand = set(fL.index)
        if use_short:
            cand &= set(fS.nlargest(nS).index)           # 动量：比值大
        if not use_long:
            cand = set(fS.nlargest(nS).index)
        ret_all = (px.loc[tn] / px.loc[t] - 1).dropna()
        if n_seed:                                        # 随机对照：随同数量行业
            k = len(cand) if cand else 1
            pick = list(rng.choice(ret_all.index.values, size=min(k, len(ret_all)), replace=False))
            r_pick = ret_all[pick].mean()
            n_pick = k
        else:
            pick = [c for c in cand if c in ret_all.index]
            r_pick = ret_all[pick].mean() if pick else ret_all.mean()   # 空集 → 全行业等权
            n_pick = len(pick)
        rows.append({"signal_date": t, "n_pick": n_pick,
                     "r_pick": r_pick, "r_all": ret_all.mean(),
                     "excess": r_pick - ret_all.mean()})
    out = pd.DataFrame(rows)
    if len(out):
        out["bear"] = market_state(pd.DatetimeIndex(out["signal_date"])).values
    return out


def summarize(d: pd.DataFrame, name: str, cal: str = "", rule: str = "") -> list[dict]:
    rows = []
    for lab, sub in [("全期", d),
                     ("牛市(沪深300>MA200)", d[~d["bear"]]),
                     ("熊市(沪深300<MA200)", d[d["bear"]])]:
        if not len(sub):
            continue
        rows.append({"口径": cal or name.split("·")[0], "规则": rule or name.split("·")[-1],
                     "标签": name, "段": lab, "期数": len(sub),
                     "平均超额%": sub["excess"].mean() * 100,
                     "超额胜率%": (sub["excess"] > 0).mean() * 100,
                     "超额波动%": sub["excess"].std() * 100,
                     "信息比": (sub["excess"].mean() / sub["excess"].std()
                              * np.sqrt(12)) if sub["excess"].std() else np.nan,
                     "累积超额%": ((1 + sub["excess"]).prod() - 1) * 100,
                     "平均持仓数": sub["n_pick"].mean()})
    return rows


def main():
    px1 = load_l1()
    px2 = load_l2()
    print(f"L1 池 {px1.shape[1]} 行业 / {px1.shape[0]} 交易日 / "
          f"{px1.index.min().date()} ~ {px1.index.max().date()}")
    print(f"L2 池 {px2.shape[1]} 行业（覆盖/成分股过滤后）/ "
          f"{px2.index.min().date()} ~ {px2.index.max().date()}")

    sig1 = monthly_signals(px1)
    sig2 = monthly_signals(px2)
    all_rows, grid = [], []

    for pname, P in PARAMS.items():
        L1f = px1.rolling(P["L1"]).mean() / px1.rolling(P["L2"]).mean()
        S1f = px1.rolling(P["S1"]).mean() / px1.rolling(P["S2"]).mean()
        start = max(L1f.first_valid_index(), S1f.first_valid_index())
        sd = [d for d in sig1 if d >= start]
        print(f"\n== L1 · {pname} ==  有效起点 {start.date()}  月末信号 {len(sd)} 期")

        rules = {}
        rules["双条件(底部+动量)"] = eval_rule(px1, sd, L1f, S1f, True, True)
        rules["仅长期底部"] = eval_rule(px1, sd, L1f, S1f, True, False)
        rules["仅短期动量"] = eval_rule(px1, sd, L1f, S1f, False, True)
        if pname.startswith("原参数"):
            for k in range(5):
                rules[f"随机{k+1}"] = eval_rule(px1, sd, L1f, S1f, True, True,
                                                n_seed=1, seed=1000 + k)
        for rn, d in rules.items():
            if rn.startswith("随机"):
                continue
            all_rows += summarize(d, f"L1·{pname.split()[0]}·{rn}", "L1·" + pname.split()[0], rn)
        if pname.startswith("原参数"):
            rd = pd.concat([rules[f"随机{k+1}"] for k in range(5)])
            all_rows += summarize(rd, "L1·原参数·★随机对照(5种子合并)", "L1·原参数", "★随机对照(5种子合并)")
            rules["双条件(底部+动量)"].to_csv(HERE / f"periods_{pname.split()[0]}.csv",
                                        index=False)

    # 参数网格（窗口 × 分位）
    for ql, qs in [(0.33, 0.33), (0.488, 0.427), (0.50, 0.50)]:
        for pname, P in PARAMS.items():
            L1f = px1.rolling(P["L1"]).mean() / px1.rolling(P["L2"]).mean()
            S1f = px1.rolling(P["S1"]).mean() / px1.rolling(P["S2"]).mean()
            start = max(L1f.first_valid_index(), S1f.first_valid_index())
            sd = [d for d in sig1 if d >= start]
            d = eval_rule(px1, sd, L1f, S1f, True, True, q_long=ql, q_short=qs)
            for r in summarize(d, f"L1·{pname.split()[0]}·q={ql}/{qs}",
                                   "L1·" + pname.split()[0], f"双条件 q={ql}/{qs}"):
                grid.append(r)

    # L2 稳健性（原比例，缩短版窗口）
    P = PARAMS["缩短版 60/360 + 20/90"]
    L2f = px2.rolling(P["L1"]).mean() / px2.rolling(P["L2"]).mean()
    S2f = px2.rolling(P["S1"]).mean() / px2.rolling(P["S2"]).mean()
    start = max(L2f.first_valid_index(), S2f.first_valid_index())
    sd2 = [d for d in sig2 if d >= start]
    d2 = eval_rule(px2, sd2, L2f, S2f, True, True)
    for r in summarize(d2, "L2·缩短版·双条件", "L2·缩短版", "双条件(底部+动量)"):
        all_rows.append(r)

    A = pd.DataFrame(all_rows)
    G = pd.DataFrame(grid)
    A.to_csv(HERE / "perf_by_state.csv", index=False)
    G.to_csv(HERE / "param_grid.csv", index=False)
    print("\n== 主表：分市场状态（超额口径）==")
    print(A.round(3).to_string(index=False))

    html = build_view(A, G, rules, sig1)
    (HERE / "result_view.html").write_text(html, encoding="utf-8")
    print(f"\n产物 → {HERE}")
    return A, G


def build_view(A, G, rules, sig1) -> str:
    import plotly.graph_objects as go
    NOL = dict(template="plotly_white", margin=dict(l=60, r=20, t=56, b=50),
               font=dict(family="Arial,'Microsoft YaHei'", color=INK))
    LAY = dict(NOL, legend=dict(orientation="h", y=-0.22))
    figs = []

    # 图1 分状态平均超额 对比
    f1 = go.Figure()
    states = ["全期", "牛市(沪深300>MA200)", "熊市(沪深300<MA200)"]
    for rn, color in [("双条件(底部+动量)", C_BASE), ("仅长期底部", C_ALT),
                      ("仅短期动量", "#8a6fd1"), ("★随机对照(5种子合并)", MUTED)]:
        s = A[(A["口径"] == "L1·原参数") & (A["规则"] == rn)]
        if not len(s):
            continue
        s = s.set_index("段").reindex(states)
        f1.add_trace(go.Bar(x=states, y=s["平均超额%"], name=rn, marker_color=color,
                            customdata=s["期数"], hovertemplate="%{x}: %{y:.3f}%/月 (n=%{customdata})<extra></extra>"))
    f1.add_hline(y=0, line=dict(color=MUTED))
    f1.update_layout(height=380, barmode="group", **LAY,
                     title="图1 · 分市场状态：月均超额收益（%，L1 池）")
    f1.update_yaxes(title_text="月均超额(%)")
    figs.append(f1.to_html(full_html=False, include_plotlyjs=True))

    # 图2 双条件逐期超额 + 熊市底纹
    d = rules["双条件(底部+动量)"]
    f2 = go.Figure()
    f2.add_trace(go.Scatter(x=d["signal_date"], y=d["excess"].cumsum() * 100,
                            name="双条件 累积超额", line=dict(color=C_BASE, width=2.5)))
    for t in d[d["bear"]]["signal_date"]:
        f2.add_vline(x=t, line=dict(color=C_NEG, width=0.6))
    f2.add_hline(y=0, line=dict(color=MUTED))
    f2.update_layout(height=400, **LAY,
                     title="图2 · 双条件策略累积超额（%，竖线=熊市月，L1·原参数）")
    f2.update_yaxes(title_text="累积超额(%)")
    figs.append(f2.to_html(full_html=False, include_plotlyjs=False))

    # 图3 每期持仓数分布
    f3 = go.Figure()
    f3.add_trace(go.Histogram(x=d["n_pick"], marker_color=C_ALT, nbinsx=16))
    f3.update_layout(height=320, **LAY,
                     title=f"图3 · 每期入选行业数分布（均值 {d['n_pick'].mean():.1f}，"
                           f"空集期 {(d['n_pick']==0).sum()}）")
    f3.update_xaxes(title_text="入选行业数")
    figs.append(f3.to_html(full_html=False, include_plotlyjs=False))

    # 图4 参数网格（熊市 vs 牛市）
    f4 = go.Figure()
    for st, color in [("牛市(沪深300>MA200)", C_POS), ("熊市(沪深300<MA200)", C_NEG)]:
        s = G[G["段"] == st]
        f4.add_trace(go.Bar(x=s["规则"], y=s["平均超额%"], name=st, marker_color=color,
                            customdata=s["期数"], hovertemplate="%{x}<br>%{y:.3f}%/月 (n=%{customdata})<extra></extra>"))
    f4.add_hline(y=0, line=dict(color=MUTED))
    f4.update_layout(height=400, barmode="group", **LAY,
                     title="图4 · 参数网格（窗口 × 分位）：牛/熊 月均超额（%）")
    f4.update_yaxes(title_text="月均超额(%)")
    figs.append(f4.to_html(full_html=False, include_plotlyjs=False))

    # 图5 全期 vs 分状态 累积超额条
    f5 = go.Figure()
    sub = A[(A["规则"] == "双条件(底部+动量)")]
    for st, color in [("全期", C_BASE), ("牛市(沪深300>MA200)", C_POS), ("熊市(沪深300<MA200)", C_NEG)]:
        s = sub[sub["段"] == st]
        f5.add_trace(go.Bar(x=s["规则"], y=s["累积超额%"], name=st, marker_color=color,
                            customdata=s["期数"], hovertemplate="%{x}<br>累积超额 %{y:.1f}% (n=%{customdata})<extra></extra>"))
    f5.update_layout(height=380, barmode="group", **LAY,
                     title="图5 · 双条件策略：各口径下的累积超额（%）")
    f5.update_yaxes(title_text="累积超额(%)")
    figs.append(f5.to_html(full_html=False, include_plotlyjs=False))

    parts = "".join(f"<div class='fig'>{f}</div>" for f in figs)
    css = f"""<style>
      body {{ font-family:Arial,'Microsoft YaHei',sans-serif; margin:24px; background:{SURFACE}; color:{INK}; }}
      .fig {{ margin:8px 0 28px 0; }}
      div.warn {{ border-left:4px solid {C_NEG}; background:#fff; padding:10px 14px; color:{INK2}; font-size:13px; }}
    </style>"""
    return (f"<html><head><meta charset='utf-8'>{css}</head><body>"
            f"<h2>analysis_018 — 「长期底部 + 短期动量」分市场状态检验</h2>"
            f"<div class='warn'>只做观测、<b>无交易成本</b>（原文亦未提）；行业池=申万一级 31 / 二级 125 个；"
            f"<b>有意不含</b>原文的「一致预期 ROE 增速」与「资金流向」两因子（本地无数据）。"
            f"熊市 = 沪深300 收盘 &lt; MA200（信号日 t 口径）。"
            f"行情图片：原参数 MA1100 需 4.4 年 ⇒ 本地样本自 2019-07 起（86 期）。</div>"
            f"{parts}</body></html>")


if __name__ == "__main__":
    main()
