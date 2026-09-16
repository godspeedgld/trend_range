"""analysis_015 · industry — 行业热门度（二级行业）对 v4 阻力带突破的区分力。

样本：analysis_012/v4_backtest/detail_v4.parquet
      （11100 笔已判定，2017-2026，**纯 v4 算法无闸门/无形态过滤**——
       与 analysis_014 同源同脚手架，保证可比）

三个行业热度指标（用户指定，均为 **sw2021 二级** 的日频横截面排名，再取 20 日均值）：
  HEAT_RET  = ma( 日收益率截面排名 , 20 )   —— 行业收益强度（相对强弱）
  HEAT_TURN = ma( 日换手率截面排名 , 20 )   —— 行业资金活跃度
  HEAT_VOL  = ma( 日成交量截面排名 , 20 )   —— 行业成交体量

横截面排名每天在 **117 个 sw2021 二级行业**（component 涉及的、有 HS300 成员的行业）上做，
取值 0~1；再对每个行业滚动 20 日取均值 → 每个行业每天一个 0~1 热度分。
每笔交易按其 **信号日 t（asof）所属二级行业** 取热度值。

口径备忘（数据侧已实测确认）：
  - bar1d 只有 6 位叶子行业；4 位前缀 = sw2021 二级（实测 118 名 ↔ 117 前缀，基本一一对应）
  - bar1d 的 volume/amount 是**加总**（全叶子加总 ≈ 全市场成交额），turn/change_ratio 是**平均**
  - 自反馈：t 日行业值含该股自身（20 日均值下权重 ≤5%），主口径按 t，另出 t-1 对照

分析：
  1) 三个指标各分十档（等频）→ n/失败率/成功率/肥尾率/均值/中位 + 单调性 Spearman
  2) 三指标相关矩阵（看冗余）
  3) 分时段稳定性 2017-2020 vs 2021-2026
  4) t-1 对照（自反馈敏感性）

产物：industry_panel.parquet / heat_features.parquet / *_decile.csv / corr.csv /
period_split.csv / baseline.txt
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # hs300-enh-2017-2021
sys.path.insert(0, str(PROJ))
warnings.filterwarnings("ignore")

DETAIL = PROJ / "01_data_analysis/analysis_012/v4_backtest/detail_v4.parquet"
WH = PROJ.parents[2] / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
PANEL20 = 20


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    return pd.Series({
        "n": len(g),
        "失败率%(ret≤0)": round((r <= 0).mean() * 100, 1),
        "成功率%(ret>0)": round((r > 0).mean() * 100, 1),
        "肥尾率%(ret≥30)": round((r >= 30).mean() * 100, 1),
        "均值%": round(r.mean(), 2),
        "中位%": round(r.median(), 2)})


def build_industry_panel(con) -> pd.DataFrame:
    """sw2021 二级行业日线：收益/换手取平均，成交量取加总。"""
    # component 涉及的二级前缀（117 个）
    pre = con.execute("""SELECT DISTINCT substr(industry_instrument,1,4) p
                         FROM stock_industry_component WHERE industry='sw2021'""").df()
    plist = "','".join(sorted(pre["p"]))
    pan = con.execute(f"""
        SELECT substr(instrument,1,4) AS ind2, date,
               avg(change_ratio) AS chg, avg(turn) AS turn, sum(volume) AS vol
        FROM stock_industry_bar1d
        WHERE substr(instrument,1,4) IN ('{plist}')
        GROUP BY 1, 2 ORDER BY 1, 2""").df()
    pan["date"] = pd.to_datetime(pan["date"])
    print(f"行业面板 {len(pan):,} 行 | {pan['ind2'].nunique()} 个二级 | "
          f"{pan['date'].min().date()} ~ {pan['date'].max().date()}")
    return pan


def heat_metrics(pan: pd.DataFrame) -> pd.DataFrame:
    """日频横截面排名 → 20 日均值；另算 t-1 版本。"""
    pan = pan.sort_values(["ind2", "date"]).copy()
    for col, name in [("chg", "RET"), ("turn", "TURN"), ("vol", "VOL")]:
        pan[f"r_{name}"] = pan.groupby("date")[col].rank(pct=True)      # 当日截面排名 0~1
    g = pan.groupby("ind2")
    for name in ["RET", "TURN", "VOL"]:
        pan[f"HEAT_{name}"] = g[f"r_{name}"].transform(
            lambda s: s.rolling(PANEL20).mean())
        pan[f"HEAT_{name}_lag1"] = g[f"HEAT_{name}"].shift(1)
    return pan


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    print(f"样本 {len(det)} 笔（{det['date'].min().date()} ~ {det['date'].max().date()}）")
    base = stat(det)
    print("== 全体基线 ==\n", base.to_string())

    con = duckdb.connect(str(WH), read_only=True)
    pan = build_industry_panel(con)

    # ── 交易 → 信号日所属二级行业（asof）──
    syms = "','".join(sorted(det["symbol"].unique()))
    asof = con.execute(f"""
        SELECT instrument AS symbol, date,
               substr(industry_instrument,1,4) AS ind2, industry_level2_name AS ind_name
        FROM stock_industry_component_daily
        WHERE instrument IN ('{syms}')""").df()
    con.close()
    asof["date"] = pd.to_datetime(asof["date"])
    asof = asof.drop_duplicates(["symbol", "date"])
    print(f"asof 行业归属 {len(asof):,} 行 | 覆盖 {asof['symbol'].nunique()} 只")

    pan = heat_metrics(pan)
    pan.to_parquet(HERE / "industry_panel.parquet")

    d = det.merge(asof, on=["symbol", "date"], how="left")
    print(f"行业归属匹配 {d['ind2'].notna().sum()} / {len(d)}（缺 {d['ind2'].isna().sum()}）")
    d = d.merge(pan, on=["date", "ind2"], how="left")
    d = d.dropna(subset=[f"HEAT_{n}" for n in ["RET", "TURN", "VOL"]]).copy()
    print(f"可配热度特征 {len(d)} 笔 | 涉及 {d['ind2'].nunique()} 个二级行业")
    d.to_parquet(HERE / "heat_features.parquet")

    # ── ① 十档（等频）──
    tr = []
    for name, label in [("RET", "收益率排名均值"), ("TURN", "换手率排名均值"), ("VOL", "成交量排名均值")]:
        col = f"HEAT_{name}"
        d["dec"] = pd.qcut(d[col], 10, labels=False, duplicates="drop") + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["区间"] = d.groupby("dec")[col].agg(lambda s: f"[{s.min():.3f},{s.max():.3f}]")
        t = t[["区间", "n", "失败率%(ret≤0)", "成功率%(ret>0)", "肥尾率%(ret≥30)", "均值%", "中位%"]]
        # 单调性：档位 vs 均值 / 失败率
        sp_mu = t["均值%"].corr(pd.Series(t.index, index=t.index), method="spearman")
        sp_fail = t["失败率%(ret≤0)"].corr(pd.Series(t.index, index=t.index), method="spearman")
        t.to_csv(HERE / f"HEAT_{name}_decile.csv", encoding="utf-8-sig")
        print(f"\n== {label} 十档 ==  (Spearman 档位↔均值 {sp_mu:+.2f} / 档位↔失败率 {sp_fail:+.2f})")
        print(t.to_string())
        tr.append({"特征": label, "档位↔均值": round(sp_mu, 2), "档位↔失败率": round(sp_fail, 2),
                   "D1均值%": t.loc[1, "均值%"], "D10均值%": t.loc[10, "均值%"],
                   "D1失败率%": t.loc[1, "失败率%(ret≤0)"], "D10失败率%": t.loc[10, "失败率%(ret≤0)"]})
    pd.DataFrame(tr).to_csv(HERE / "decile_summary.csv", index=False, encoding="utf-8-sig")

    # ── ② 相关矩阵（三指标冗余度）──
    cols = [f"HEAT_{n}" for n in ["RET", "TURN", "VOL"]]
    print("\n== 三指标相关（Spearman）==\n", d[cols].corr(method="spearman").round(3).to_string())
    d[cols].corr(method="spearman").round(4).to_csv(HERE / "corr.csv", encoding="utf-8-sig")
    raws = [f"r_{n}" for n in ["RET", "TURN", "VOL"]]
    d[raws].corr(method="spearman").round(4).to_csv(HERE / "corr_daily_rank.csv", encoding="utf-8-sig")

    # ── ③ 分时段 ──
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"),
                        ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        for name, label in [("RET", "收益率"), ("TURN", "换手率"), ("VOL", "成交量")]:
            s["dec"] = pd.qcut(s[f"HEAT_{name}"], 5, labels=False, duplicates="drop") + 1
            t = s.groupby("dec").apply(stat, include_groups=False)
            rows.append({"时段": seg, "特征": label,
                         **{f"Q{k}均值%": t.loc[k, "均值%"] for k in range(1, 6)},
                         **{f"Q{k}失败率%": t.loc[k, "失败率%(ret≤0)"] for k in range(1, 6)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段（五分位 Q1低 → Q5高）==\n", per.to_string(index=False))

    # ── ④ 行业内中性化（诊断：剥离行业固定效应）──
    # 注意：此处用**全样本行业均值**去均值，有轻微前视；仅作机理诊断，
    # 因果版（rolling/expanding 基线）留待后续 update 确认。
    flips, comps = [], []
    for name, label in [("RET", "收益率"), ("TURN", "换手率"), ("VOL", "成交量")]:
        col = f"HEAT_{name}"
        d[col + "_dm"] = d[col] - d.groupby("ind2")[col].transform("mean")
        d["dec"] = pd.qcut(d[col + "_dm"], 10, labels=False, duplicates="drop") + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["区间"] = d.groupby("dec")[col + "_dm"].agg(lambda s: f"[{s.min():.3f},{s.max():.3f}]")
        t = t[["区间", "n", "失败率%(ret≤0)", "成功率%(ret>0)", "肥尾率%(ret≥30)", "均值%", "中位%"]]
        t.to_csv(HERE / f"HEAT_{name}_decile_dm.csv", encoding="utf-8-sig")
        sp_dm = t["均值%"].corr(pd.Series(t.index, index=t.index), method="spearman")
        sp_raw = pd.read_csv(HERE / f"HEAT_{name}_decile.csv", index_col=0)["均值%"].corr(
            pd.Series(range(1, 11), index=range(1, 11)), method="spearman")
        flips.append({"特征": label, "原始_档↔均值": round(sp_raw, 2),
                      "行业内_档↔均值": round(sp_dm, 2)})
        s = d[d["dec"] == 10]["ind_name"].value_counts(normalize=True).head(5)
        comps.append({"指标": label, "档": "D10(去均值后最高)", "行业": " | ".join(s.index),
                      "占比%": " | ".join(f"{v*100:.0f}" for v in s.values)})
    flip = pd.DataFrame(flips)[["特征", "原始_档↔均值", "行业内_档↔均值"]]
    flip.to_csv(HERE / "sign_flip.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(comps).to_csv(HERE / "d10_composition.csv", index=False, encoding="utf-8-sig")
    print("\n== 符号翻转（档↔均值 Spearman）==\n", flip.to_string(index=False))

    # 原始口径的 D10 行业构成（看是不是被少数行业塞满）
    comp_raw = []
    for name, label in [("RET", "收益率"), ("TURN", "换手率"), ("VOL", "成交量")]:
        col = f"HEAT_{name}"
        d["dec"] = pd.qcut(d[col], 10, labels=False, duplicates="drop") + 1
        s = d[d["dec"] == 10]["ind_name"].value_counts(normalize=True).head(5)
        comp_raw.append({"指标": label, "档": "D10(原始最高)", "行业": " | ".join(s.index),
                         "占比%": " | ".join(f"{v*100:.0f}" for v in s.values)})
    pd.DataFrame(comp_raw).to_csv(HERE / "d10_composition_raw.csv", index=False, encoding="utf-8-sig")

    # ── ⑤ t-1 对照（自反馈敏感性）──
    print("\n== t-1 对照（各指标 D1/D10 均值%）==")
    for name, label in [("RET", "收益率"), ("TURN", "换手率"), ("VOL", "成交量")]:
        for suf in ["", "_lag1"]:
            col = f"HEAT_{name}{suf}"
            if col not in d.columns or d[col].isna().all():
                continue
            dd = d.dropna(subset=[col]).copy()
            dd["dec"] = pd.qcut(dd[col], 10, labels=False, duplicates="drop") + 1
            t = dd.groupby("dec").apply(stat, include_groups=False)
            print(f"  {label}{'(t-1)' if suf else '(t)':<6} D1 {t.loc[1,'均值%']:+.2f}%  D10 {t.loc[10,'均值%']:+.2f}%")

    (HERE / "baseline.txt").write_text(base.to_string(), encoding="utf-8")


if __name__ == "__main__":
    main()
