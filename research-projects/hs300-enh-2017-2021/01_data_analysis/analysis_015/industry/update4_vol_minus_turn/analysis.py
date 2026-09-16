"""analysis_015/industry 更新四 — **规模/活跃度错配**指标：ma(成交量截面排名,10) − ma(换手率截面排名,10)。

语义：成交额/成交量排名受**行业规模**主导（大行业天然排前），换手率排名是**相对自身盘子**的活跃度。
  差值高 = 规模排名 > 活跃度排名 → **大而静**（大盘冷门行业）
  差值低 = 规模排名 < 活跃度排名 → **小而闹**（小盘活跃/资金拥挤）
分析：
  A) 更新三同款**反向框架**：按 `ret` 分十档 → 反查指标中位数（+ 成分分解 + 分时段）
  B) 用户指定的**正向框架**（本更新新增）：按**指标**分十档 → 看每档 失败率/成功率/肥尾率/均值/中位
     —— 这才是检验**预测力**的框架（反向框架只说明"构成差异"）

对照：窗口 10−10（主） vs 20−20；口径 原始 vs 行业内中性化（causal expanding 基线）。

产物：mismatch_panel.parquet / ret_decile_SPR.csv / decomposition.csv /
forward_decile_{variant}.csv / forward_summary.csv / period_split.csv / baseline.txt
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
UP = HERE.parent                                   # industry/
PROJ = HERE.parents[3]                             # hs300-enh-2017-2021
sys.path.insert(0, str(PROJ))
warnings.filterwarnings("ignore")

DETAIL = PROJ / "01_data_analysis/analysis_012/v4_backtest/detail_v4.parquet"
WH = PROJ.parents[2] / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
VARIANTS = [("S10_RAW", "10−10·原始"), ("S10_DM", "10−10·行业内"),
            ("S20_RAW", "20−20·原始"), ("S20_DM", "20−20·行业内")]


def ret_stat(g: pd.DataFrame, cols: list[str]) -> pd.Series:
    """反向框架：给定 ret 档，汇总指标本身。"""
    r = g["ret"] * 100
    row = {"n": len(g), "收益中位%": round(r.median(), 2),
           "收益区间%": f"[{r.min():.0f},{r.max():.0f}]",
           "失败率%": round((r <= 0).mean() * 100, 1),
           "肥尾率%": round((r >= 30).mean() * 100, 1)}
    for v in cols:
        row[f"{v}_中位"] = round(g[v].median(), 4)
        row[f"{v}_均值"] = round(g[v].mean(), 4)     # 均值可加，分解表用它
        row[f"{v}_P25"] = round(g[v].quantile(0.25), 4)
        row[f"{v}_P75"] = round(g[v].quantile(0.75), 4)
        row[f"{v}_正占比%"] = round((g[v] > 0).mean() * 100, 1)
    return pd.Series(row)


def perf_stat(g: pd.DataFrame) -> pd.Series:
    """正向框架：给定指标档，汇总突破绩效。"""
    r = g["ret"] * 100
    return pd.Series({"n": len(g),
                      "失败率%(ret≤0)": round((r <= 0).mean() * 100, 1),
                      "成功率%(ret>0)": round((r > 0).mean() * 100, 1),
                      "肥尾率%(ret≥30)": round((r >= 30).mean() * 100, 1),
                      "均值%": round(r.mean(), 2),
                      "中位%": round(r.median(), 2)})


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    base_fail = round((det["ret"] * 100 <= 0).mean() * 100, 1)
    base_fat = round((det["ret"] * 100 >= 30).mean() * 100, 1)
    base_mu = round(det["ret"].mean() * 100, 2)
    print(f"样本 {len(det)} 笔｜基线 失败率 {base_fail}% / 肥尾率 {base_fat}% / 均值 {base_mu:+.2f}%")

    # ── 错配指标面板 ──
    pan = pd.read_parquet(UP / "industry_panel.parquet")[["ind2", "date", "r_VOL", "r_TURN"]]
    pan = pan.sort_values(["ind2", "date"])
    allcols = []
    for w in (10, 20):
        pan[f"C_VOL{w}"] = pan.groupby("ind2")["r_VOL"].transform(lambda s: s.rolling(w).mean())
        pan[f"C_TURN{w}"] = pan.groupby("ind2")["r_TURN"].transform(lambda s: s.rolling(w).mean())
        raw = f"S{w}_RAW"
        pan[raw] = pan[f"C_VOL{w}"] - pan[f"C_TURN{w}"]
        base = pan.groupby("ind2")[raw].transform(
            lambda s: s.shift(1).expanding(min_periods=250).mean())      # causal 基线
        pan[f"S{w}_DM"] = pan[raw] - base
        allcols += [raw, f"S{w}_DM"]
    pan[["ind2", "date", "C_VOL10", "C_TURN10"] + allcols].to_parquet(HERE / "mismatch_panel.parquet")

    syms = "','".join(sorted(det["symbol"].unique()))
    con = duckdb.connect(str(WH), read_only=True)
    asof = con.execute(f"""SELECT instrument AS symbol, date,
                                  substr(industry_instrument,1,4) AS ind2
                           FROM stock_industry_component_daily
                           WHERE instrument IN ('{syms}')""").df()
    con.close()
    asof["date"] = pd.to_datetime(asof["date"])
    asof = asof.drop_duplicates(["symbol", "date"])

    d = det.merge(asof, on=["symbol", "date"], how="left").merge(pan, on=["date", "ind2"], how="left")
    d = d.dropna(subset=allcols).copy()
    d["ret_dec"] = pd.qcut(d["ret"], 10, labels=False, duplicates="drop") + 1
    ndec = d["ret_dec"].nunique()
    print(f"可配 {len(d)} 笔 | {d['ind2'].nunique()} 个二级行业 | 收益 {ndec} 档\n")

    # ══ A. 反向框架（更新三同款）══
    t = d.groupby("ret_dec").apply(
        ret_stat, cols=allcols + ["C_VOL10", "C_TURN10"], include_groups=False)
    t.index.name = "ret_dec"
    t.to_csv(HERE / "ret_decile_SPR.csv", encoding="utf-8-sig")
    idx = pd.Series(t.index, index=t.index)
    rsumm = []
    for v, label in VARIANTS:
        rsumm.append({"变体": label,
                      "档↔指标中位数": round(t[f"{v}_中位"].corr(idx, method="spearman"), 2),
                      "D1": t.loc[1, f"{v}_中位"], "D6": t.loc[6, f"{v}_中位"],
                      "D10": t.loc[ndec, f"{v}_中位"], "峰值档": int(t[f"{v}_中位"].idxmax()),
                      "D10−D1": round(t.loc[ndec, f"{v}_中位"] - t.loc[1, f"{v}_中位"], 4),
                      "D1−D6": round(t.loc[1, f"{v}_中位"] - t.loc[6, f"{v}_中位"], 4)})
    print("== A. 反向框架 · 按收益分档看指标 ==\n",
          pd.DataFrame(rsumm).to_string(index=False))

    # 用**均值**做分解（均值可加：mean(a−b)=mean(a)−mean(b) 精确成立；中位数不成立）
    dec = pd.DataFrame({"成交量排名均值(10日)": t["C_VOL10_均值"],
                        "换手率排名均值(10日)": t["C_TURN10_均值"],
                        "差值(=指标)": t["S10_RAW_均值"],
                        "校验:前两列之差": (t["C_VOL10_均值"] - t["C_TURN10_均值"]).round(4),
                        "差值(行业内)": t["S10_DM_均值"]})
    dec.to_csv(HERE / "decomposition.csv", encoding="utf-8-sig")
    print("\n== 成分分解（原始, 10日）==\n", dec.to_string())

    # ══ B. 正向框架（本更新新增）══
    fsumm = []
    print("\n" + "=" * 76 + "\n== B. 正向框架 · 按指标分档看突破绩效 ==")
    for v, label in VARIANTS:
        d["sdec"] = pd.qcut(d[v], 10, labels=False, duplicates="drop") + 1
        f = d.groupby("sdec").apply(perf_stat, include_groups=False)
        f["区间"] = d.groupby("sdec")[v].agg(lambda s: f"[{s.min():+.3f},{s.max():+.3f}]")
        f = f[["区间", "n", "失败率%(ret≤0)", "成功率%(ret>0)", "肥尾率%(ret≥30)", "均值%", "中位%"]]
        f.to_csv(HERE / f"forward_decile_{v}.csv", encoding="utf-8-sig")
        fi = pd.Series(f.index, index=f.index)
        sp_mu = f["均值%"].corr(fi, method="spearman")
        sp_fail = f["失败率%(ret≤0)"].corr(fi, method="spearman")
        fsumm.append({"变体": label, "档↔均值": round(sp_mu, 2), "档↔失败率": round(sp_fail, 2),
                      "D1均值%": f.loc[1, "均值%"], "D10均值%": f.loc[10, "均值%"],
                      "极差均值%": round(f["均值%"].max() - f["均值%"].min(), 2),
                      "最好档": int(f["均值%"].idxmax()), "最差档": int(f["均值%"].idxmin()),
                      "D1肥尾%": f.loc[1, "肥尾率%(ret≥30)"], "D10肥尾%": f.loc[10, "肥尾率%(ret≥30)"]})
        print(f"\n-- {label}（Spearman 档↔均值 {sp_mu:+.2f} / 档↔失败率 {sp_fail:+.2f}）--")
        print(f.to_string())
    fw = pd.DataFrame(fsumm)
    fw.to_csv(HERE / "forward_summary.csv", index=False, encoding="utf-8-sig")
    print("\n== B. 正向汇总 ==\n", fw.to_string(index=False))

    # ══ C. 分时段（两种框架）══
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"),
                        ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        s["rd"] = pd.qcut(s["ret"], 5, labels=False, duplicates="drop") + 1
        for v, label in VARIANTS:
            q = s.groupby("rd")[v].median()
            rows.append({"框架": "A反向", "时段": seg, "变体": label,
                         "档↔中位数": round(q.corr(pd.Series(q.index, index=q.index), method="spearman"), 2),
                         **{f"Q{k}": round(q.get(k, np.nan), 4) for k in range(1, 6)}})
        for v, label in VARIANTS:
            s["sd"] = pd.qcut(s[v], 5, labels=False, duplicates="drop") + 1
            q = s.groupby("sd")["ret"].mean() * 100
            rows.append({"框架": "B正向", "时段": seg, "变体": label,
                         "档↔中位数": round(q.corr(pd.Series(q.index, index=q.index), method="spearman"), 2),
                         **{f"Q{k}": round(q.get(k, np.nan), 2) for k in range(1, 6)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== C. 分时段（A=指标中位数 / B=各档均值%）==\n", per.to_string(index=False))

    (HERE / "baseline.txt").write_text(
        f"n={len(det)}\n失败率%(ret≤0)={base_fail}\n肥尾率%(ret≥30)={base_fat}\n"
        f"均值%={base_mu}\n中位%={det['ret'].median()*100:.2f}\n可配笔数={len(d)}\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
