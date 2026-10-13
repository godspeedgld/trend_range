"""analysis_006 — 方案 B 的「六因子标尺 + 每个因子的逻辑解释」。

承接：analysis_003（基线四因子标尺）→ analysis_005（全库 512 因子扫描，选出 3 个新因子）→
      **analysis_006 = 把方案 B 的 6 个因子按 analysis_003 同一口径再测一遍，并把每个因子的
      "怎么算 / 什么意思 / 为什么用它" 讲清楚。**

方案 B（用户 2026-10-13 定）：
  基线四因子 **把 `mom_20` 换成 R076**（`smooth(breakdown,5)`），**再加 R221 / R222** ⇒ 共 6 个。
  为什么换 mom_20 而不是直接加：
    · `mom_20` 与 `px_ma20` 池内 ρ=**0.77**（同簇重复，见 analysis_005 结论）
    · R076 与 `px_ma20` 只有 **0.69**，且 IC 0.0638 vs mom_20 0.0387（**高 64%**）
    ⇒ 同一簇里换更强的那个：簇内信息不变、质量提升，也不额外稀释其他因子权重。

口径（逐字沿用 analysis_003，不改）：
  池 = 每周当周 top3 行业内候选股（`analysis_003.load_pool`）154,548 行 / 494 信号日 / 313 只·周
  收益 = 池内 ret_ww（exec_open(t) → exec_open 下一信号日）
  IC = 逐周截面 Spearman(方向化因子, 下周收益)（正 = 该方向有效）

产物：result_view.html（含**因子解释表** + IC 汇总 + 年度 IC + 五分位 + 累计 IC 曲线）/ records.md
用法：python analysis.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]
REPO = PROJ.parents[1]
A003 = PROJ / "01_data_analysis" / "analysis_003" / "analysis.py"
DB = REPO / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

# (列名, 方向, 短名, 算法, 含义, 策略怎么用)
SPEC = [
    ("turn_ratio", -1, "换手比(5周/60周)", "MA5(turn) / MA60(turn)",
     "近 5 周换手率相对近 60 周水平的倍数 —— 关注度是**升温还是降温**",
     "买**降温**的（换手萎缩 = 被冷落）"),
    ("px_ma20", -1, "乖离MA20(20周)", "close / MA20(close) − 1",
     "价格偏离 20 周均线的幅度 —— **站上还是跌破**均线",
     "买**跌破**均线的（负乖离）"),
    ("breakdown_5w_smooth", +1, "R076 破位平滑(5周)", "EMA3( 1 − close / min(low 前5周) )",
     "收盘价**跌破前 5 周最低点**的深度，再做 3 周指数平滑去噪",
     "买**刚破位**的（超卖反弹）"),
    ("liq_amount", -1, "均额(20周)", "MA20(amount)",
     "近 20 周平均成交额 —— 成交的**绝对活跃度**",
     "买**成交清淡**的（低流动性溢价）"),
    ("price_volume_corr_5w_confirm_volume", -1, "R221 量价相关×量能确认(5周)",
     "corr5( 周涨跌幅, 周量变化 ) × volume / MA20(volume)",
     "量价**配合(+)/背离(−)** × **放/缩量**（量能确认）",
     "买**量价背离 且 缩量**的"),
    ("obv_slope_5w_confirm_volume", -1, "R222 OBV斜率×量能确认(5周)",
     "( OBV 5周斜率 / MA5(volume) ) × volume / MA20(volume)",
     "OBV 的资金**流向趋势**（流入/流出）× **放/缩量**",
     "买**资金持续流出 且 缩量**的"),
]
NEW_COLS = [s[0] for s in SPEC if s[0] not in ("turn_ratio", "px_ma20", "liq_amount")]


def load_mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_pool(a003):
    pool = a003.load_pool()
    con = duckdb.connect(str(DB), read_only=True)
    con.register("k", pool[["date", "symbol"]].rename(columns={"symbol": "instrument"}))
    sel = ", ".join(f'f."{c}"' for c in NEW_COLS)
    got = con.execute(f"""SELECT f.date, f.instrument AS symbol, {sel}
        FROM v_factor_1w f JOIN k ON f.instrument=k.instrument AND f.date=k.date""").df()
    con.close()
    got["date"] = pd.to_datetime(got["date"])
    pool = pool.merge(got, on=["date", "symbol"], how="left")
    print(f"并入库新因子 {len(NEW_COLS)} 列：命中 {got[NEW_COLS[0]].notna().mean():.1%}")
    return pool


def composite(pool, pairs) -> pd.Series:
    """策略打分复刻：行业内 rank(pct)(方向化因子) 的等权平均。"""
    parts = [pool.groupby(["date", "ind_name"])[c].transform(lambda s: (d * s).rank(pct=True))
             for c, d in pairs]
    return pd.concat(parts, axis=1).mean(axis=1)


# ───────── 指标（同 analysis_003，只把方向参数化）─────────
def ic_series(pool, col, sign):
    return pool.groupby("date").apply(
        lambda x: (sign * x[col]).corr(x["ret_ww"], method="spearman"),
        include_groups=False).dropna()


def stats_table(pool, items):
    rows = []
    for col, sign, name, *_ in items:
        s = ic_series(pool, col, sign)
        rows.append({"因子": name, "IC周数": len(s), "IC均值": s.mean(), "IC标准差": s.std(),
                     "ICIR": s.mean() / s.std(), "t值": s.mean() / s.std() * np.sqrt(len(s)),
                     "IC>0占比": (s > 0).mean(), "|IC|≥0.02": (s.abs() >= 0.02).mean(),
                     "_ic": s})
    return pd.DataFrame(rows).set_index("因子")


def yearly_ic(pool, items):
    out = {}
    for col, sign, name, *_ in items:
        s = ic_series(pool, col, sign)
        out[name] = s.groupby(s.index.year).mean()
    return pd.DataFrame(out).round(4)


def group_table(pool, items, q=5):
    rows = {}
    for col, sign, name, *_ in items:
        qq = pool.groupby("date")[col].apply(
            lambda x: pd.qcut(sign * x, q, labels=False, duplicates="drop")).droplevel(0)
        tmp = pd.DataFrame({"g": qq, "ret": pool["ret_ww"]}).dropna()
        m = tmp.groupby("g")["ret"].mean()
        rows[name] = pd.Series([m.get(i, np.nan) for i in range(q)], index=range(q))
    df = pd.DataFrame(rows).rename(index=lambda i: f"Q{i+1}")
    df.loc["Q5−Q1(bp/周)"] = (df.loc["Q5"] - df.loc["Q1"]) * 1e4
    df.loc["单调性ρ"] = np.nan
    for c in df.columns:
        y = df.loc[[f"Q{i+1}" for i in range(q)], c].astype(float)
        df.loc["单调性ρ", c] = pd.Series(range(q)).corr(pd.Series(y.values))
    return df


def render(stats, stats_all, yearly, groups, ex_items, items, icmap, out: Path):
    import plotly.graph_objects as go

    def tbl(df, title, h=None, idx=True):
        d = df.reset_index() if idx else df.copy()
        f = go.Figure(go.Table(header=dict(values=list(d.columns), fill_color="#f3f5f8", align="left"),
                               cells=dict(values=[d[c].round(4) if d[c].dtype.kind == "f" else d[c]
                                                  for c in d.columns], align="left", height=26)))
        f.update_layout(title=title, height=h or 220 + 28 * len(d))
        return f

    # ⓪ 因子解释表（用户要求：每个因子解释清楚）
    ex = pd.DataFrame([{"因子": name, "方向": ("+1 买高值" if d > 0 else "−1 买低值"),
                        "算法": algo, "什么意思": mean, "策略怎么用": use}
                       for _, d, name, algo, mean, use in ex_items])
    fig0 = go.Figure(go.Table(
        header=dict(values=list(ex.columns), fill_color="#eaf2f8", align="left"),
        cells=dict(values=[ex[c] for c in ex.columns], align="left", height=40)))
    fig0.update_layout(title="⓪ 六个因子 —— 怎么算 / 什么意思 / 策略怎么用", height=150 + 46 * len(ex))

    fig1 = tbl(stats.drop(columns=["_ic"]),
               "① IC / ICIR / t 汇总（★ 共同区间 —— 六因子与新旧复合分可比）", 380)
    fig1b = tbl(stats_all.drop(columns=["_ic"])[["IC周数", "IC均值", "ICIR", "t值"]],
                "①b 全区间（各自有值的周；新因子窗口短 ⇒ 周数更多，仅参考）", 380)
    fig2 = tbl(yearly, "② 年度 IC", 520)
    fig3 = tbl(groups, "③ 五分位平均下周收益 / Q5−Q1 / 单调性", 460)

    fig4 = go.Figure()
    for _, _, name, *_ in items:
        s = icmap[name]
        fig4.add_scatter(x=s.index, y=s.cumsum(), name=name)
    fig4.update_layout(title="④ IC 累计曲线（六因子 + 新复[合]分）", template="plotly_white",
                       height=560, hovermode="x unified")

    fig5 = go.Figure()
    qcols = [f"Q{i+1}" for i in range(5)]
    for c in groups.columns:
        fig5.add_bar(x=qcols, y=groups.loc[qcols, c].values * 100, name=c)
    fig5.update_layout(title="⑤ 五分位平均下周收益（%，Q5 = 该方向最偏爱）", barmode="group",
                       template="plotly_white", height=540)

    figs = [("⓪ 因子解释", fig0), ("① IC 汇总（共同区间）", fig1), ("①b IC 汇总（全区间）", fig1b),
            ("② 年度 IC", fig2), ("③ 五分位", fig3), ("④ IC 累计曲线", fig4), ("⑤ 分组柱图", fig5)]
    parts = ["<h2>analysis_006 — 方案 B 六因子标尺（候选池内 · 周频 · 开-开收益）</h2>"]
    for k, (name, f) in enumerate(figs):
        parts.append(f"<h3>{name}</h3>" + f.to_html(full_html=False, include_plotlyjs=(k == 0)))
    out.write_text('<html><head><meta charset="utf-8"></head>'
                   '<body style="font-family:Arial,\'Microsoft YaHei\',sans-serif;margin:24px">'
                   + "".join(parts) + "</body></html>", encoding="utf-8")
    print(f"图表已写 {out}")


def main() -> int:
    a003 = load_mod(A003, "a003")
    pool = build_pool(a003)

    # 新复合分（6 因子）注入 pool，供 IC / 年度 / 分组统计复用
    pool["__new__"] = composite(pool, [(c, d) for c, d, *_ in SPEC])
    ex_items = list(SPEC)                       # 只解释 6 个真因子
    items = ex_items + [
        ("__new__", 1, "★新复合分(6因子)", "六因子行业内 rank(pct) 等权平均", "策略打分本身", "——"),
        ("_score", 1, "（参考）旧复合分(基线四因子)", "基线四因子行业内 rank(pct) 等权平均",
         "现行策略打分", "——")]

    n_days = pool["date"].nunique()
    print(f"候选池 {len(pool):,} 行 / {n_days} 信号日 / 平均 {len(pool)/n_days:.0f} 只·周 / "
          f"ret_ww 非空 {pool['ret_ww'].notna().mean():.1%}\n")

    # ★ 同区间对照：新 3 个因子窗口短(5周) ⇒ 比 20/60 周的基线早 ~19 周有值。
    #   直接比会高估新复合分。取「旧复合分有值」的周做**共同区间**（= 策略真实可交易的区间）。
    pool_c = pool[pool["_score"].notna()].copy()
    print(f"共同区间（旧复合分有值）：{pool_c['date'].nunique()} 周 / {len(pool_c):,} 行 "
          f"({pool_c['date'].min().date()}~{pool_c['date'].max().date()}）")

    stats_all = stats_table(pool, items)
    stats = stats_table(pool_c, items)              # ★ 主表 = 共同区间
    icmap = {name: r["_ic"] for name, r in stats.iterrows()}
    yearly = yearly_ic(pool_c, items)
    groups = group_table(pool_c, items)

    print("\n① IC 汇总（共同区间 = 主口径）："); print(stats.drop(columns=["_ic"]).round(4).to_string())
    print("\n①b IC 汇总（全区间，各自有值的周）：")
    print(stats_all.drop(columns=["_ic"])[
        ["IC周数", "IC均值", "ICIR", "t值"]].round(4).to_string())
    print("\n③ 五分位（共同区间）："); print(groups.to_string(float_format=lambda v: f"{v:.5f}"))
    for tag, st in (("共同区间", stats), ("全区间", stats_all)):
        n_, o_ = st.loc["★新复合分(6因子)"], st.loc["（参考）旧复合分(基线四因子)"]
        print(f"★ 新复合分(6) IC {n_['IC均值']:+.4f} / t {n_['t值']:+.2f}  vs  "
              f"旧复合分(4) IC {o_['IC均值']:+.4f} / t {o_['t值']:+.2f}   [{tag}]")

    render(stats, stats_all, yearly, groups, ex_items, items, icmap, HERE / "result_view.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
