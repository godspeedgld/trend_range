"""analysis_014 · depth_duration — 深度/久度特征对 v4 阻力带突破的区分力（人工经验 R2 第一步）。

样本：analysis_012/v4_backtest/detail_v4.parquet（11100 笔已判定，纯算法无闸门——同 R1 基座）。

两特征（信号日 t 收盘可知，rolling 因果无未来）：
  DD  深度 = close[t]/max(high,252)[t] − 1   （距 252 日最高价的回撤；0 = 突破日即新高）
  AGE 久度 = t − argmax(high,252)[t]          （距 252 日最高点多少交易日；0 = 今日创新高）
  ⚠ 两者相关但不等同：慢跌后反弹（DD 浅 AGE 长）vs 急跌后反弹（DD 深 AGE 短）是不同形态。

分析（R1 同款）：各十分位（等频，rank 法保 10 档）→ n/失败率/成功率/肥尾率/均值/中位；
分时段 2017-2020 vs 2021-26 稳定性。先验（analysis_004）：深非单调好、追高（浅回撤+近期
已大涨）极差、甜点回撤 5~25%——本步验证先验在 v4 样本是否复现。
（注：十分位边界用全样本分位，属分析层展示口径；上组合前一律改 expanding 因果——R1 教训。）
"""
from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                      # hs300-enh-2017-2021
warnings.filterwarnings("ignore")

DETAIL = PROJ / "01_data_analysis/analysis_012/v4_backtest/detail_v4.parquet"
PANEL = PROJ / "_market_hs300_panel.parquet"


def stat(g: pd.DataFrame) -> pd.Series:
    r = g["ret"] * 100
    fail, fat = (r <= 0).mean() * 100, (r >= 30).mean() * 100
    return pd.Series({"n": len(g), "失败率%(ret≤0)": round(fail, 1), "成功率%(ret>0)": round((r > 0).mean() * 100, 1),
                      "肥尾率%(ret≥30)": round(fat, 1), "均值%": round(r.mean(), 2), "中位%": round(r.median(), 2)})


def main():
    det = pd.read_parquet(DETAIL)
    det["date"] = pd.to_datetime(det["date"])
    print(f"样本 {len(det)} 笔（{det['date'].min().date()} ~ {det['date'].max().date()}）")
    print("== 全体基线 ==\n", stat(det).to_string())

    pan = pd.read_parquet(PANEL, columns=["date", "symbol", "close", "high"])
    pan["date"] = pd.to_datetime(pan["date"])
    pan = pan.sort_values(["symbol", "date"])
    g = pan.groupby("symbol")
    roll = g["high"].transform(lambda h: h.rolling(252, min_periods=60).max())
    argmax = g["high"].transform(lambda h: h.rolling(252, min_periods=60).apply(np.argmax, raw=True))
    cnt = g["high"].cumcount()                                   # 该股截至当日的 bar 序（0 起）
    wlen = np.minimum(cnt + 1, 252)                              # 当日实际窗长
    pan["high252"] = roll
    pan["DD"] = pan["close"] / roll - 1.0                        # ≤0；0=新高
    # AGE = 窗长−1−argmax（高点在窗内的相对位置→距今交易日数；两套坐标勿混）
    pan["AGE"] = wlen - 1 - argmax
    pan.loc[cnt < 60, "AGE"] = np.nan
    feats = pan.set_index(["symbol", "date"])[["DD", "AGE", "high252"]]
    det = det.join(feats, on=["symbol", "date"])
    d = det.dropna(subset=["DD", "AGE", "ret"]).copy()
    print(f"可配特征 {len(d)} 笔（缺 {len(det)-len(d)}：252 窗不足）")
    d.to_parquet(HERE / "dd_features.parquet")

    out = {}
    for col, name in [("DD", "深度 DD=close/high252−1"), ("AGE", "久度 AGE=距252高点点数")]:
        d["dec"] = pd.qcut(d[col].rank(method="first"), 10, labels=False) + 1
        t = d.groupby("dec").apply(stat, include_groups=False)
        t["区间"] = d.groupby("dec")[col].agg(["min", "max"]).apply(
            lambda r: f"[{r['min']:+.3f},{r['max']:+.3f}]" if col == "DD" else f"[{r['min']:.0f},{r['max']:.0f}]天", axis=1)
        out[col] = t[["区间", "n", "失败率%(ret≤0)", "成功率%(ret>0)", "肥尾率%(ret≥30)", "均值%", "中位%"]]
        out[col].to_csv(HERE / f"{col}_decile.csv", encoding="utf-8-sig")
        print(f"\n== {name} 十档 ==\n", out[col].to_string())

    # 分时段失败率
    rows = []
    for seg, lo, hi in [("2017-2020", "2017-01-01", "2020-12-31"), ("2021-2026", "2021-01-01", "2099-01-01")]:
        s = d[(d["date"] >= lo) & (d["date"] <= hi)].copy()
        for col in ("DD", "AGE"):
            s["dec"] = pd.qcut(s[col].rank(method="first"), 10, labels=False) + 1
            t = s.groupby("dec").apply(stat, include_groups=False)
            rows.append({"时段": seg, "特征": col,
                         **{f"D{k}失败率%": t.loc[k, "失败率%(ret≤0)"] for k in range(1, 11)},
                         "D1均值%": t.loc[1, "均值%"], "D10均值%": t.loc[10, "均值%"]})
    per = pd.DataFrame(rows)
    per.to_csv(HERE / "period_split.csv", index=False, encoding="utf-8-sig")
    print("\n== 分时段失败率%（D1..D10）==\n", per.to_string(index=False))
    (HERE / "baseline.txt").write_text(stat(det).to_string(), encoding="utf-8")


if __name__ == "__main__":
    main()
