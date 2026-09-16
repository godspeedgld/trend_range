"""analysis_014 · volume — 量能特征对 v4 阻力带突破的区分力（人工经验 R1 定量检验）。

样本：analysis_012/v4_backtest/detail_v4.parquet（11100 笔已判定，2017-2026，**纯 v4 算法
无任何闸门/形态过滤**——静态4ATR止损+前日ATR吊灯出场，deg≥2 为 v4 锁定配置的一部分）。

两个量能特征（信号日 t 收盘可知，无未来）：
  RV  放量比  = vol[t] / ma_vol20[t]（ma_vol20 含 t 当日）——"突破日放量"
  UDVR 涨量占比 = Σ(涨日 vol, 近20日含t) / Σ(全部 vol, 近20日含t)——"上涨量能比下跌量能多"
                 （0.5 中性，>0.5 = 涨日量占比高）

分析（用户指定 + 增值）：
  1) RV / UDVR 各分十档（等频）→ 每档 n/失败率(ret≤0)/成功率(ret>0)/肥尾率(ret≥30%)/均值/中位
  2) 交互 3×3（RV×UDVR 低中高）——检验"涨量结构×突破放量"组合（缩量整理+启动放量 vs 放量出货）
  3) 分时段稳定性 2017-2020 vs 2021-2026（项目惯例防过拟合）
  4) 对照桥：ma_vol20 绝对水平分位（analysis_012 已知"低量好"，验证新旧结论衔接）

产物：rv_decile.csv / udvr_decile.csv / interaction.csv / period_split.csv / vol_features.parquet /
result_view.html
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # hs300-enh-2017-2021（volume 在 analysis_014 下一层）
sys.path.insert(0, str(PROJ))
warnings.filterwarnings("ignore")

DETAIL = PROJ / "01_data_analysis/analysis_012/v4_backtest/detail_v4.parquet"
PANEL = PROJ / "_market_hs300_panel.parquet"


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    return pd.Series({
        "n": len(g),
        "失败率%(ret≤0)": round((r <= 0).mean() * 100, 1),
        "成功率%(ret>0)": round((r > 0).mean() * 100, 1),
        "肥尾率%(ret≥30)": round((r >= 30).mean() * 100, 1),
        "均值%": round(r.mean(), 2),
        "中位%": round(r.median(), 2)})


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    print(f"样本 {len(det)} 笔（{det['date'].min().date()} ~ {det['date'].max().date()}）")
    base = stat(det)
    print("== 全体基线 ==\n", base.to_string())

    # ── 量能特征（逐股滚动，causal；信号日收盘可知当日量）──
    pan = pd.read_parquet(PANEL, columns=["date", "symbol", "close", "volume"])
    pan["date"] = pd.to_datetime(pan["date"])
    pan = pan.sort_values(["symbol", "date"])
    pan["ma_vol20"] = pan.groupby("symbol")["volume"].transform(
        lambda v: v.rolling(20).mean())
    up = pan["close"] > pan.groupby("symbol")["close"].shift(1)
    pan["up_vol"] = np.where(up, pan["volume"], 0.0)
    g = pan.groupby("symbol")
    pan["sum_vol20"] = g["volume"].transform(lambda v: v.rolling(20).sum())
    pan["sum_upvol20"] = g["up_vol"].transform(lambda v: v.rolling(20).sum())
    pan["RV"] = pan["volume"] / pan["ma_vol20"]
    pan["UDVR"] = pan["sum_upvol20"] / pan["sum_vol20"]
    feats = pan.set_index(["symbol", "date"])[["RV", "UDVR", "ma_vol20"]]

    det = det.join(feats, on=["symbol", "date"])
    d = det.dropna(subset=["RV", "UDVR"]).copy()
    d["ma_vol20_pct"] = d.groupby(d["date"].dt.year // 5 * 5)["ma_vol20"].rank(pct=True)  # 粗水平分位(组内)
    print(f"可配量能特征 {len(d)} 笔（缺 {len(det)-len(d)}）")
    d.to_parquet(HERE / "vol_features.parquet")

    # ── ① 十档 ──
    out = {}
    for col, name in [("RV", "放量比 vol/ma_vol20"), ("UDVR", "涨量占比 UDVR")]:
        d["dec"] = pd.qcut(d[col], 10, labels=False, duplicates="drop") + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["区间"] = d.groupby("dec")[col].agg(["min", "max"]).apply(
            lambda r: f"[{r['min']:.2f},{r['max']:.2f}]" if col == "RV" else f"[{r['min']:.3f},{r['max']:.3f}]", axis=1)
        out[col] = t[["区间", "n", "失败率%(ret≤0)", "成功率%(ret>0)", "肥尾率%(ret≥30)", "均值%", "中位%"]]
        out[col].to_csv(HERE / f"{col}_decile.csv", encoding="utf-8-sig")
        print(f"\n== {name} 十档 ==\n", out[col].to_string())

    # ── ② 交互 3×3 ──
    d["rv3"] = pd.qcut(d["RV"], 3, labels=["低RV", "中RV", "高RV"])
    d["ud3"] = pd.qcut(d["UDVR"], 3, labels=["低UDVR", "中UDVR", "高UDVR"])
    inter = d.groupby(["ud3", "rv3"], observed=True).apply(stat, include_groups=False)
    inter.to_csv(HERE / "interaction.csv", encoding="utf-8-sig")
    print("\n== 交互 3×3（行=UDVR 列内=RV）==\n", inter.to_string())

    # ── ③ 分时段 ──
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        s["dec"] = pd.qcut(s["RV"], 10, labels=False, duplicates="drop") + 1
        t = s.groupby("dec").apply(stat, include_groups=False)
        rows.append({"时段": seg, "特征": "RV", **{f"D{k}失败率%": t.loc[k, "失败率%(ret≤0)"] if k in t.index else None
                                                for k in range(1, 11)}})
        s["dec"] = pd.qcut(s["UDVR"], 10, labels=False, duplicates="drop") + 1
        t = s.groupby("dec").apply(stat, include_groups=False)
        rows.append({"时段": seg, "特征": "UDVR", **{f"D{k}失败率%": t.loc[k, "失败率%(ret≤0)"] if k in t.index else None
                                                   for k in range(1, 11)}})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段失败率%（D1..D10）==\n", per.to_string(index=False))
    (HERE / "baseline.txt").write_text(base.to_string(), encoding="utf-8")


if __name__ == "__main__":
    main()
