"""本地因子导出 —— **用本地 BigQuant 仓库的日频数据 + 现成的 Python 因子代码**。

不做任何 `dai` 查询、不重写因子公式。因子早已由
`shared/build_stock_panel.py`（= 「之前写过的回测代码」里的因子部分）算好并落在
`shared/_cache/signal_panel_full.parquet` 里 —— 就是拿本地 `stock_bar1d` 的
close / pre_close / turn / amount 在 pandas 里算出来的。

本脚本**只做筛选与另存**：取 2026 年、且落在当周选中行业内的行，
写成 `local_panel_2026.parquet`，与云端 `panel_2026.parquet` 同口径、逐值可比。

行业信号已证实 **494/494 周与云端完全一致**，所以「当周选中哪 3 个行业」直接取本地
`shared/_cache/weekly_plan.parquet` 的 top3 即可，不必再问云端。

用法：`python local_factor_export.py`   （不消耗任何配额）
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]                            # industry _regime_stock_picking
CACHE = PROJ / "shared/_cache"

sys.path.insert(0, str(PROJ))
from shared.build_panel import SW801 as NAME2CODE      # noqa: E402  （行业名 → 801 码）

# 与云端 cloud_code_with_industry_log.py 的 PANEL_START / PANEL_END 保持一致
PANEL_START, PANEL_END = "2026-01-01", "2026-08-14"


def main():
    panel = pd.read_parquet(CACHE / "signal_panel_full.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.rename(columns={"symbol": "instrument", "vol_20": "vol_stock"})
    print(f"本地面板（signal_panel_full，由 build_stock_panel.py 用 Python 算出）: "
          f"{len(panel):,} 行 / {panel.date.nunique()} 信号日 / {panel.instrument.nunique():,} 只")

    # ── 当周选中的行业（本地 weekly_plan 的 top3；已证实与云端逐周一致）──
    plan = pd.read_parquet(CACHE / "weekly_plan.parquet")
    plan["signal_date"] = pd.to_datetime(plan["signal_date"])
    plan = plan[(plan["signal_date"] >= pd.Timestamp(PANEL_START))
                & (plan["signal_date"] <= pd.Timestamp(PANEL_END))]
    entered = {(r.signal_date, ind) for _, r in plan.iterrows()
               for ind in str(r["top3"]).split(",")}
    print(f"调仓日 {len(plan)} 个（{plan.signal_date.min().date()} ~ "
          f"{plan.signal_date.max().date()}），共 {len(entered)} 个「调仓日×行业」组合")

    # ── 筛选：2026 年 + 当周选中行业内 ──
    win = panel[(panel["date"] >= pd.Timestamp(PANEL_START))
                & (panel["date"] <= pd.Timestamp(PANEL_END))]
    ent = win[[(d, i) in entered for d, i in zip(win["date"], win["ind_name"])]].copy()
    ent["ind_code"] = ent["ind_name"].map(NAME2CODE)

    cols = ["date", "instrument", "ind_code", "ind_name",
            "turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_stock"]
    ent = ent[cols].sort_values(["date", "ind_code", "instrument"]).reset_index(drop=True)
    print(f"\n进入行业面板: {len(ent):,} 行 / {ent.date.nunique()} 个信号日 / "
          f"{ent.instrument.nunique():,} 只 / 均值 {len(ent)/max(1, ent.date.nunique()):.0f} 只/日")
    print(f"  逐日只数: {ent.groupby('date').size().describe()[['min','50%','max']].to_dict()}")
    print(f"  四因子非空率: "
          + ", ".join(f"{c}={ent[c].notna().mean():.1%}"
                      for c in ["turn_ratio", "px_ma20", "mom_20", "liq_amount", "vol_stock"]))

    out = HERE / "local_panel_2026.parquet"
    ent.to_parquet(out, index=False)
    print(f"\n→ {out.name}  ({len(ent):,} 行 × {ent.shape[1]} 列, "
          f"{out.stat().st_size/1e6:.2f} MB)")
    print(f"  列: {list(ent.columns)}")
    print("\n下一步：把云端 panel_2026.parquet 下载到本目录，跑 python compare_factor_values.py")


if __name__ == "__main__":
    main()
