"""analysis_003 — 基线四因子在「候选池内 · 周频 · 下周收益」口径下的强度标尺。

背景（承接 strategy_002 基线 = 云端原版复现，2026-10-13）：
  在挑「更好的反转因子」之前，先立标尺——当前口径下基线的四个反转因子各自多强？
  这是四步计划的第 1 步：标尺 → 随机对照 → 候选筛选 → 组合验证。

口径（= 策略真实执行的条件，不是泛全市场检验）：
  · 候选池：每周信号日，**当周 top3 行业内**的全部候选股（面板自带云端 CTE 过滤：
             st=0 / 未停牌 / list_days>252 / amount>2e7 / 有行业归属）
  · 因子：signal_panel_weekly_indpre 的**周频窗口**因子（窗口起点 2016-12-30 = 云端对齐；
          turn_ratio 需 60 周 → 2018-03 起才有值，px/mom/liq 需 20 周 → 2017-05 起）
  · 未来收益：exec_open(t) → exec_open(t')（t' = 下一信号日）——即策略的下周一开盘买、
              持有一周、下个下周一开盘卖的**开-开收益**；下一行不是下一信号日的置 NaN
  · 指标约定（与 scripts/factor_validation_local.py 一致）：
      IC = 逐周截面 Spearman(因子·策略方向, 下周收益)（**方向化**：正值 = 策略方向有效）
      ICIR = mean(IC)/std(IC)；t = ICIR × √N；分组 = 池内五分位平均下周收益 + 单调性 ρ
  · 复合分（第 5 条"因子"）：完全复刻策略打分——行业内 rank(pct)(-f) 的均值(skipna)，
      直接量化「选股层排序」本身的信息量（为第 2 步随机对照做基准）

为什么不直接跑 factor_validation_local 流水线：它的池是**静态**指数成分，而本分析需要
**逐周随 regime 变化的 top3 行业候选池**；且因子必须用云端对齐窗口起点的现成面板
（用日线重算会得到不同的窗口历史）。IC/ICIR/t 的计算约定与其保持一致。

产物：result_view.html（自包含 plotly：汇总表 / 年度 IC 表 / 分组表 / IC 累计曲线 / 分组柱图）
用法：python analysis.py
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

FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]   # 基线四因子（策略方向恒为 -1）
LABELS = {"turn_ratio": "换手比(5周/60周)", "px_ma20": "乖离MA20(20周)",
          "mom_20": "动量(20周)", "liq_amount": "均额(20周)", "_score": "复合分(策略打分)"}


# ─────────────────────── ① 数据：面板 + 计划 → 候选池 ───────────────────────
def load_pool() -> pd.DataFrame:
    panel = pd.read_parquet(CACHE / "signal_panel_weekly_indpre.parquet")
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")

    # 开-开下周收益：本行 exec_open → 下一**信号日**行的 exec_open（防"跳周到更晚"污染）
    panel = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    g = panel.groupby("symbol", sort=False)
    panel["ret_ww"] = g["exec_open"].shift(-1) / panel["exec_open"] - 1
    sig = sorted(plan["signal_date"])
    nxt = dict(zip(sig, sig[1:]))
    nd = g["date"].shift(-1)
    panel.loc[nd.values != panel["date"].map(nxt).values, "ret_ww"] = np.nan

    # 候选池：每周只留当周 top3 行业的候选股（= build_weekly_targets 的 cand 选择）
    panel_by_day = {d: x for d, x in panel.groupby("date")}
    pools = []
    for r in plan.itertuples():
        day = panel_by_day.get(r.signal_date)
        if day is None:
            continue
        top3 = set(str(r.top3).split(","))
        pools.append(day[day["ind_name"].isin(top3)])
    pool = pd.concat(pools, ignore_index=True)

    # 复合分（完全复刻策略打分）：行业内 rank(pct)(-f) 的均值，skipna
    parts = [pool.groupby(["date", "ind_name"])[f].transform(lambda s: (-s).rank(pct=True))
             for f in FACTORS]
    pool["_score"] = pd.concat(parts, axis=1).mean(axis=1)
    return pool


# ─────────────────────── ② 指标：IC / ICIR / t / 分组 ───────────────────────
def ic_series(pool: pd.DataFrame, col: str, within_ind: bool = False) -> pd.Series:
    """逐周（或逐周×行业）截面 Spearman(方向化因子, 下周收益)。"""
    grp = pool.groupby(["date", "ind_name"] if within_ind else "date")
    s = grp.apply(lambda x: (-x[col] if not col.startswith("_") else x[col])
                  .corr(x["ret_ww"], method="spearman"), include_groups=False)
    return s.dropna()


def stats_table(pool: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    rows = []
    for c in cols:
        s = ic_series(pool, c)                      # 池内 IC（策略方向）
        sw = ic_series(pool, c, within_ind=True)    # 行业内 IC（策略 rank 的真实粒度）
        rows.append({
            "因子": LABELS[c], "IC周数": len(s),
            "IC均值": s.mean(), "IC标准差": s.std(),
            "ICIR": s.mean() / s.std(), "t值": s.mean() / s.std() * np.sqrt(len(s)),
            "IC>0占比": (s > 0).mean(), "|IC|≥0.02": (s.abs() >= 0.02).mean(),
            "行业内IC均值": sw.mean(),
        })
    return pd.DataFrame(rows).set_index("因子")


def yearly_ic(pool: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = {}
    for c in cols:
        s = ic_series(pool, c)
        out[LABELS[c]] = s.groupby(s.index.get_level_values("date").year).mean()
    df = pd.DataFrame(out)
    df.index.name = "年份"
    return df.round(4)


def group_table(pool: pd.DataFrame, cols: list[str], q: int = 5) -> pd.DataFrame:
    """池内逐周五分位（Q高 = 策略越偏爱）→ 平均下周收益（周均值，%）+ 单调性。"""
    rows = {}
    for c in cols:
        # 方向化：策略偏爱 = 因子取负（复合分本身已是策略方向）
        qq = pool.groupby("date")[c].apply(
            lambda x: pd.qcut(-x if not c.startswith("_") else x, q, labels=False,
                              duplicates="drop")).droplevel(0)   # 丢掉 date 层，对齐 pool 索引
        tmp = pd.DataFrame({"g": qq, "ret": pool["ret_ww"]}).dropna()
        m = tmp.groupby("g")["ret"].mean()
        base = pd.Series([m.get(i, np.nan) for i in range(q)], index=range(q))
        rows[LABELS[c]] = base
    df = pd.DataFrame(rows).rename(index=lambda i: f"Q{i+1}")
    df.loc["Q5−Q1(bp/周)"] = (df.loc["Q5"] - df.loc["Q1"]) * 1e4
    df.loc["单调性ρ"] = [np.nan] * df.shape[1]
    for j, c in enumerate(df.columns):
        y = df.loc[[f"Q{i+1}" for i in range(q)], c].astype(float)
        df.loc["单调性ρ", c] = pd.Series(range(q)).corr(pd.Series(y.values))
    return df


# ─────────────────────── ③ 输出：HTML（自包含）+ 控制台 ───────────────────────
def render(pool: pd.DataFrame, stats: pd.DataFrame, yearly: pd.DataFrame,
           groups: pd.DataFrame, cols: list[str], out: Path):
    import plotly.graph_objects as go

    def _tbl(df, title, h=None):
        d = df.reset_index()
        f = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8",
                                           align="left"),
                               cells=dict(values=[d[c].round(4) if d[c].dtype.kind == "f"
                                                  else d[c] for c in d.columns],
                                          align="left", height=26)))
        f.update_layout(title=title, height=h or 200 + 30 * len(d))
        return f

    fig_cum = go.Figure()
    for c in cols:
        s = ic_series(pool, c)
        fig_cum.add_scatter(x=s.index.get_level_values("date"), y=s.cumsum(),
                            name=LABELS[c], mode="lines")
    fig_cum.update_layout(title="IC 累计曲线（候选池内 · 周频 · 方向化）", template="plotly_white",
                          height=520, hovermode="x unified")

    fig_grp = go.Figure()
    qcols = [f"Q{i+1}" for i in range(5)]
    for c in groups.columns:
        fig_grp.add_bar(x=qcols, y=groups.loc[qcols, c].values * 100, name=c)
    fig_grp.update_layout(title="五分位平均下周收益（%，Q5 = 策略最偏爱）", barmode="group",
                          template="plotly_white", height=520)

    figs = [("① 四因子 + 复合分：IC/ICIR/t 汇总", _tbl(stats, "① IC 汇总（池内 · 策略方向）", 320)),
            ("② 年度 IC", _tbl(yearly, "② 年度 IC 均值", 520)),
            ("③ 五分位分组", _tbl(groups, "③ 五分位平均下周收益 / Q5−Q1 / 单调性", 460)),
            ("④ IC 累计曲线", fig_cum), ("⑤ 分组柱图", fig_grp)]
    parts = [f"<h2>analysis_003 — 基线四因子强度标尺（候选池内 · 周频 · 下周收益）</h2>"]
    for k, (name, f) in enumerate(figs):
        parts.append(f"<h3>{name}</h3>"
                     + f.to_html(full_html=False, include_plotlyjs=(True if k == 0 else False)))
    out.write_text('<html><head><meta charset="utf-8"></head>'
                   '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
                   + "".join(parts) + "</body></html>", encoding="utf-8")
    print(f"\n图表已写 {out}")


def main() -> int:
    pool = load_pool()
    n_days = pool["date"].nunique()
    print(f"候选池 {len(pool):,} 行 / {n_days} 个信号日 / 平均 {len(pool)/n_days:.0f} 只·周"
          f" / ret_ww 非空 {pool['ret_ww'].notna().mean():.1%}")

    cols = FACTORS + ["_score"]
    stats = stats_table(pool, cols)
    yearly = yearly_ic(pool, cols)
    groups = group_table(pool, cols)

    print("\n① IC 汇总（池内 · 策略方向化，正 = 有效）：")
    print(stats.round(4).to_string())
    print("\n② 年度 IC：")
    print(yearly.to_string())
    print("\n③ 五分位（Q5 = 策略最偏爱，数值 = 平均下周收益）：")
    print(groups.to_string(float_format=lambda v: f"{v:.5f}"))

    render(pool, stats, yearly, groups, cols, HERE / "result_view.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
