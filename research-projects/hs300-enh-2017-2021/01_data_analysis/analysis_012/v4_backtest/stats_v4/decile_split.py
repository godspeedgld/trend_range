"""v4 记录 8 组分桶统计：成功/失败 × 各按特征十分位 → 均值/中位/最大/最小。

1. 成功组按 degree
2. 失败组按 degree
3. 成功组按 价格过去一年 decile（原始信号已有）
4. 失败组按 decile
5. 成功组按 ma_turn20 十分位
6. 失败组按 ma_turn20 十分位
7. 成功组按 股息率 十分位
8. 失败组按 股息率 十分位
9. 成功组按 ma_vol10 十分位
10. 失败组按 ma_vol10 十分位

（用户 1-8，ma_vol10 替代 ma_vol20 作为量特征；dividend 即股息率）
统计：每组内按特征十分位（十分位=组内该特征 rank 10 等分）→ 均值/中位/max/min。
成功=ret>0；失败=ret≤0。ma_vol10 需从 bar volume rolling(10) 现算。
输出 decile_split.csv（长表）+ 可视化。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
V4 = HERE.parent / "detail_v4.parquet"
PROJ = HERE.parents[3]
PANEL = PROJ / "_market_hs300_panel.parquet"

FEATS = ["degree", "decile", "ma_turn20", "dividend_yield_ratio", "ma_vol10"]
FEAT_LABEL = {"degree": "degree", "decile": "price_decile", "ma_turn20": "ma_turn20",
              "dividend_yield_ratio": "div_yield", "ma_vol10": "ma_vol10"}


def main():
    det = pd.read_parquet(V4)
    det["date"] = pd.to_datetime(det["date"])
    dec = det[det["result"].isin(["success", "fail"])].copy()
    dec["ok"] = dec["ret"] > 0
    dec["ret_pct"] = dec["ret"] * 100

    # 特征表（features_v4 已有 degree? 无 → degree 用 det 本身；其余从 features_v4 取）
    fx = pd.read_parquet(HERE / "features_v4.parquet")
    fx["date"] = pd.to_datetime(fx["date"])
    dec = dec.merge(fx[["symbol", "date", "turn", "ma_turn20", "vol", "decile",
                        "dividend_yield_ratio"]],
                    on=["symbol", "date"], how="left", suffixes=("", "_f"))
    dec["ma_turn20"] = dec["ma_turn20"]
    # ma_vol10 现算
    bar = pd.read_parquet(PANEL)
    bar["date"] = pd.to_datetime(bar["date"])
    mv10 = {s: x.set_index("date")["volume"].rolling(10).mean()
            for s, x in bar.groupby("symbol")}
    dec["ma_vol10"] = [float(mv10[r.symbol].get(pd.Timestamp(r.date), np.nan))
                       if r.symbol in mv10 else np.nan for r in dec.itertuples()]

    rows = []
    for group, gname in [(True, "success"), (False, "fail")]:
        sub = dec[dec["ok"] == group]
        for col in FEATS:
            disp = FEAT_LABEL[col]
            s = sub[[col, "ret_pct"]].dropna().copy()
            if len(s) < 100:
                continue
            if col == "decile":          # price_decile 本身 1-10，直接用原始档
                s["q"] = s[col].astype(int) - 1
            else:                        # 其余等频 rank 十分位
                s["q"] = (s[col].rank(pct=True) * 10).astype(int).clip(0, 9)
            for d in range(10):
                g = s[s["q"] == d]["ret_pct"]
                if len(g):
                    rows.append({"group": gname, "feature": disp, "decile": d + 1,
                                "n": len(g), "mean": g.mean(), "median": g.median(),
                                "max": g.max(), "min": g.min()})
    out = pd.DataFrame(rows)
    out.to_csv(HERE / "decile_split.csv", index=False, encoding="utf-8-sig")
    # 打印摘要
    for gname in ("success", "fail"):
        print(f"\n═══ {gname} ═══")
        for feat in FEATS:
            disp = FEAT_LABEL[feat]
            s = out[(out["group"] == gname) & (out["feature"] == disp)]
            if len(s):
                print(f"\n[{disp}]")
                print(s[["decile", "n", "mean", "median", "max", "min"]].round(2).to_string(index=False))
    return out


if __name__ == "__main__":
    main()
