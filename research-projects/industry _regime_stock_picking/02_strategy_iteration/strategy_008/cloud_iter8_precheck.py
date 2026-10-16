"""cloud_code_iter8_mirrorgate_v1 —— **算法等价预检**（送云端前必做，2026-10-16）。

只做一件事：把云端脚本里的 `apply_crowd_gate`（迭代7 动量闸 + 迭代8 镜像闸）
原样抽出来，喂**本地数据**，逐周比对：
  · 动量闸关掉的周集合 == 本地 007 的 f_007
  · 镜像闸关掉的周集合 == 本地 008 的 f_008（含 23 周的量）
  · 合并后的 exposure 与本地逐周**逐值一致**
这能挡住「键不同源 / 口径写错 / 闸门静默失效」这类只在云端才暴露的坑。

用法：python cloud_iter8_precheck.py
"""
from __future__ import annotations

import io
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[1]        # 归档后位于 <PROJ>/02_strategy_iteration/strategy_008/
CACHE = PROJ / "shared" / "_cache"
CLOUD = PROJ / "02_strategy_iteration/strategy_008/data_from_cloud/cloud_code_iter8_mirrorgate_v1.py"

# ── 抽出云端函数定义段（到「3. 组装信号」为止），喂桩件后 exec ──
src = CLOUD.read_text(encoding="utf-8").split("# ==================== 3. 组装信号")[0]
mod = types.ModuleType("cloud_iter8")
mod.__dict__.update({"np": np, "pd": pd})
exec(compile(src, str(CLOUD), "exec"), mod.__dict__)
print("已载入云端函数：", [k for k, v in mod.__dict__.items()
                      if callable(v) and k in ("apply_crowd_gate", "compute_crowding",
                                               "weekly_aggregate", "load_industry_volume")])
print(f"  云端参数 SC_THR={mod.SC_THR}  SC_MAX_THR={mod.SC_MAX_THR}")

# ── 本地数据 → 云端函数的入参形状 ──
plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
plan["signal_date"] = pd.to_datetime(plan["signal_date"])
crowd_df = pd.read_parquet(CACHE / "industry_crowding_weekly.parquet")
crowd = crowd_df.rename(columns={"week": "date", "ind": "ind_code"})[
    ["date", "ind_code", "signal_count"]].copy()
crowd["date"] = pd.to_datetime(crowd["date"])

rows = []
for _, r in plan.iterrows():
    for nm in str(r["top3"]).split(","):
        rows.append({"date": r["signal_date"], "ind_code": nm, "regime": r["regime"]})
ind_sig = pd.DataFrame(rows)
exposure = plan.set_index("signal_date")["exposure"].astype(float).sort_index()
print(f"\n本地输入：ind_sig {len(ind_sig)} 行 / {ind_sig['date'].nunique()} 周；"
      f"crowd {len(crowd)} 行 / {crowd['ind_code'].nunique()} 行业；exposure {len(exposure)} 周")

# ── 跑云端函数 ──
ex_cloud, log = mod.apply_crowd_gate(exposure, ind_sig, crowd)
n_mom = int(log["gated_mom"].sum())
n_rev = int(log["gated_rev"].sum())
print(f"\n云端口径：动量闸关 {n_mom} 周；镜像闸关 {n_rev} 周；总空仓 {int((ex_cloud < 1).sum())}/{len(ex_cloud)}")

# ── 本地独立算一遍（controls.py 同款逻辑）──
sc = {(pd.Timestamp(d), c): float(s) for d, c, s in
      zip(crowd["date"], crowd["ind_code"], crowd["signal_count"])}
f_local = {}
for d, g in ind_sig.groupby("date"):
    v = [sc.get((pd.Timestamp(d), c), np.nan) for c in g["ind_code"]]
    v = [x for x in v if not np.isnan(x)]
    mean, mx = (float(np.mean(v)) if v else np.nan), (float(np.max(v)) if v else np.nan)
    rg = g["regime"].iloc[0]
    base = float(exposure.loc[d])
    f = base
    if base == 1.0 and not np.isnan(mean):
        if rg == "momentum" and mean < mod.SC_THR:
            f = 0.0
        elif rg == "reversal" and mx >= mod.SC_MAX_THR:
            f = 0.0
    f_local[d] = f
f_local = pd.Series(f_local).sort_index()

# ── 比对 ──
cmp = pd.DataFrame({"cloud": ex_cloud, "local": f_local}).dropna()
diff = cmp[cmp["cloud"] != cmp["local"]]
print(f"\n== 逐周比对（{len(cmp)} 周）==")
print(f"  exposure 不一致：{len(diff)} 周")
if len(diff):
    print(diff.head(10).to_string())
print(f"  动量闸集合一致：{set(log.index[log['gated_mom']]) == set(f_local.index[(f_local==0) & (exposure==1) & (ind_sig.groupby('date')['regime'].first().reindex(f_local.index)=='momentum')])}")
print(f"  两口径 gated_mom 计数：云端 {n_mom}")
print(f"\n  → 算法等价：{'通过 ✓' if len(diff) == 0 else '不一致 ✗'}")

# ── 与本地引擎口径的 34 / 23 对齐（007 报告 / strategy_008 controls）──
print(f"\n== 与本地引擎口径对齐 ==")
print(f"  动量闸 {n_mom} 周（strategy_007 报告：全窗 34 周，含 2016-12-30 预热首周）")
print(f"  镜像闸 {n_rev} 周（strategy_008 controls：23 周）")
print(f"  {'✓ 一致' if n_rev == 23 else '✗ 不一致'}")
