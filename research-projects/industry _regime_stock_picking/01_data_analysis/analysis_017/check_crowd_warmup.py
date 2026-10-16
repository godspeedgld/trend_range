import sys, io
from pathlib import Path
import numpy as np, pandas as pd
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
P = Path(__file__).resolve().parents[2]   # 归档后位于 <PROJ>/01_data_analysis/analysis_017/
sys.path.insert(0, str(P))
sys.path.insert(0, str(P / "shared"))
import importlib.util
spec = importlib.util.spec_from_file_location("bcs", P / "shared/build_crowding_signals.py")
m = importlib.util.module_from_spec(spec); sys.modules["bcs"] = m; spec.loader.exec_module(m)

base = m.build_industry_weekly()
print(f"[原始周网格] {len(base):,} 行 / {base['week'].nunique()} 周  "
      f"{base['week'].min().date()} ~ {base['week'].max().date()}")
full = m.add_crowding(base)
print(f"[加拥挤度] {len(full)} 行")
print(f"首个非零 sc 周 = {full.loc[full['signal_count']>0,'week'].min().date()}")
b0 = full[full['vol_bias_pct'].notna()]['week'].min()
print(f"bias 首个非 NaN 周 = {b0.date()}")
print()
d0 = pd.Timestamp("2016-12-30")
r = full[(full.week == d0) & (full['ind'] == '交通运输')]
print("2016-12-30 交通运输 行："); print(r.to_string(index=False))
print()
print("已交付文件同格（对比）:")
old = pd.read_parquet(P / "shared/_cache/industry_crowding_weekly.parquet")
old['week'] = pd.to_datetime(old['week'])
print(old[(old.week == d0) & (old['ind'] == '交通运输')].to_string(index=False))
print()
fully = full.groupby(full.week.dt.year)['signal_count'].mean().round(3)
sig = set(pd.to_datetime(pd.read_parquet(P/"shared/_cache/weekly_plan.parquet")["signal_date"]).unique())
sub = full[full.week.isin(sig)]
suby = sub.groupby(sub.week.dt.year)['signal_count'].mean().round(3)
print(pd.DataFrame({"全网格均值": fully, "仅信号周均值(交付口径)": suby}).head(12).to_string())
