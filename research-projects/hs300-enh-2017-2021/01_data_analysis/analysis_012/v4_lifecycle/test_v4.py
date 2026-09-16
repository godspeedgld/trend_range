"""v4 生命周期测试：中芯国际 + 招商蛇口 → 带生死明细 + 可视化数据。

输出本目录：
  smic_v4_bands.csv / shekou_v4_bands.csv（带明细：线/生死/起止日/degree）
  smic_v4_events.csv / shekou_v4_events.csv（突破事件）
  对比 v3：同股跑 v3 的带结构，数出死亡带数差异。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SHARED = HERE.parents[2] / "shared"
sys.path.insert(0, str(SHARED))

from plateau_algo_v3 import run_band_breakout      # noqa: E402  冻结 v3
from plateau_algo_v4 import run_band_breakout_v4  # noqa: E402  v4 生命周期

import duckdb

WAREHOUSE = Path(r"C:\Quant\trend_range\data_cache/bigquant_warehouse/bigquant_warehouse.duckdb")
STOCKS = {"688981.SH": "smic", "001979.SZ": "shekou"}


def load_daily(inst: str) -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute("SELECT date, open, high, low, close FROM stock_bar1d "
                     f"WHERE instrument='{inst}' ORDER BY date").fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna().reset_index(drop=True)


def band_span_days(g, i0, i1):
    return (pd.Timestamp(g["date"].iloc[i1]) - pd.Timestamp(g["date"].iloc[i0])).days


def main():
    summary = {}
    for inst, tag in STOCKS.items():
        g = load_daily(inst)
        ev4, bands4, _ = run_band_breakout_v4(g)
        ev3, bands3, _ = run_band_breakout(g)

        b4 = pd.DataFrame([{**{k: v for k, v in b.items() if k not in ("dead_i",)},
                            "dead": b["dead"],
                            "dead_date": b["d_dead"], "d_last": b["d_last"]} for b in bands4])
        b4["span_days"] = [band_span_days(g, b["i0"], b["born_i"]) for b in bands4]
        b4.to_csv(HERE / f"{tag}_v4_bands.csv", index=False, encoding="utf-8-sig")
        e4 = pd.DataFrame(ev4)
        if len(e4):
            e4["date"] = pd.to_datetime(e4["date"])
            e4.to_csv(HERE / f"{tag}_v4_events.csv", index=False, encoding="utf-8-sig")

        n_dead = int(b4["dead"].sum())
        summary[inst] = {
            "bars": len(g), "range": f"{g['date'].min().date()}~{g['date'].max().date()}",
            "v3_bands": len(bands3), "v4_bands": len(bands4),
            "v4_dead": n_dead, "v4_alive": len(bands4) - n_dead,
            "v3_events": len(ev3), "v4_events": len(ev4),
            "dead_list": b4[b4["dead"]][["line", "d_born", "dead_date", "count"]].to_dict("records"),
        }
        print(f"\n═══ {inst}（{tag}）═══")
        for k, v in summary[inst].items():
            if k != "dead_list":
                print(f"  {k}: {v}")
        for d in summary[inst]["dead_list"]:
            print(f"  DEAD 带: line={d['line']:.2f} born={str(d['d_born'])[:10]} "
                  f"dead={str(d['dead_date'])[:10]} pts={d['count']}")
        # 事件差异
        e3 = pd.DataFrame(ev3)
        if len(e3) and len(e4):
            e3["date"] = pd.to_datetime(e3["date"])
            k3 = set(zip(e3["date"].dt.date, e3["line"].round(2)))
            k4 = set(zip(e4["date"].dt.date, e4["line"].round(2)))
            print(f"  事件: 仅v3 {len(k3 - k4)} / 仅v4 {len(k4 - k3)} / 共有 {len(k3 & k4)}")
        g.to_csv(HERE / f"{tag}_daily.csv", index=False)
    pd.DataFrame(summary).T.to_csv(HERE / "v4_test_summary.csv", encoding="utf-8-sig")


if __name__ == "__main__":
    main()
