"""更新八交易记录统计：全案例/成功/失败 + 桶/degree/decile（复用 ret_stats 逻辑）。"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
A7 = HERE.parent
PROJ = A7.parents[1]
SHARED = PROJ / "shared"
import sys
sys.path.insert(0, str(SHARED))
from decile_precompute import _decile_at  # 复用（虽接受 series+idx，这里自行算更稳）

det = pd.read_parquet(HERE / "detail_atr4static.parquet")
det["date"] = pd.to_datetime(det["date"])
det["ret_pct"] = det["ret"] * 100
dec = det[det["result"].isin(["success", "fail"])].copy()
print(f"已判定 {len(dec)}：成功 {(dec.result=='success').sum()} / 失败 {(dec.result=='fail').sum()}")

# 十分位：用 sig_i + 面板 close
panel = pd.read_parquet(PROJ / "_market_hs300_panel.parquet")
panel["date"] = pd.to_datetime(panel["date"])
by_sym = {s: g["close"].to_numpy(float) for s, g in panel.groupby("symbol")}
W = 252
dcl = []
for r in dec.itertuples():
    arr = by_sym.get(r.symbol)
    if arr is None or pd.isna(r.sig_i):
        dcl.append(np.nan); continue
    i = int(r.sig_i); lo = max(0, i - W + 1)
    win = arr[lo:i + 1]
    dcl.append(min(int(float((win < arr[i]).mean()) * 10) + 1, 10))
dec["decile"] = dcl
dec["g_deg"] = dec["degree"].apply(lambda d: d if d <= 11 else 99)
dec["g_deg_lab"] = dec["g_deg"].map({**{i: str(i) for i in range(2, 12)}, 99: "12+"})
dec["ok"] = dec["ret_pct"] > 0

# 总体
w, l = dec.loc[dec.ret > 0, "ret"], dec.loc[dec.ret <= 0, "ret"]
print(f"胜率 {len(w)/len(dec)*100:.1f}% 期望 {dec['ret_pct'].mean():+.2f}% 盈亏比 "
      f"{w.mean()/abs(l.meahn()) if False else w.mean()/abs(l.mean()):.2f} 中位 {dec['ret_pct'].median():+.2f}%")

def grp_sum(df, key):
    g = df.groupby(key)["ret_pct"].agg(n="count", mean="mean", median="median")
    ok = df[df.ok].groupby(key)["ret_pct"].mean().rename("ok_mean")
    bad = df[~df.ok].groupby(key)["ret_pct"].mean().rename("bad_mean")
    return g.join(ok).join(bad)

for nm, sub in (("全案例", dec), ("成功组", dec[dec.ok]), ("失败组", dec[~dec.ok])):
    print(f"\n═══ {nm}（{len(sub)} 笔）═══")
    for key in ("g_deg_lab", "decile"):
        s = grp_sum(sub, key)
        print(s.round(2).to_string())

# 落盘供可视化
dec.to_parquet(HERE / "trades_stats.parquet", index=False)
dec.to_csv(HERE / "trades_stats.csv", index=False, encoding="utf-8-sig")
print("\n写出 trades_stats.parquet/csv")
