"""analysis_011 — A_v2 交易突破价的历史十分位分布：成功/失败案例在十个分位的分布。

问题：v3 突破买在个股过去 1 年价格区间的什么位置？高位突破 vs 低位突破的成功率
是否稳定（三时段对照防上帝视角）？

口径：
  - 交易底：strategy_006 ab_tests/A_v2（无闸门基线，673 笔）；信号日 = entry 前一交易日
  - 突破价 P = 信号日收盘 close_sig（突破发生价）
  - 十分位：P 在【该股信号日前 252 个交易日（含当日）收盘价窗口】中的百分位
    pct = (窗口内收盘 < P 的比例)，decile = int(pct×10)+1（1=最低档，10=最高档）
  - 历史窗口用 2015 全面板（保证 2017-04 首笔信号也有约 270 根历史，接近满窗）
  - 成功/失败：return_pct > 0 = 成功（简单口径，records 注明）
  - 三时段（按信号日）：S1 2015-2020（实际 2017-04 起）、S2 2021-2026、S3 全期
  - 输出：每段 成功/失败 在十档的数量+占比（占该类总数），另附每档成功率（跨类对照）

无未来：分位只用 ≤信号日 数据；return_pct 是该笔交易事后收益（分析对象本身）。
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Quant\trend_range")
PROJ = ROOT / "replication/research-projects/hs300-enh-2017-2021"
HERE = Path(__file__).resolve().parent
A_V2 = PROJ / "02_strategy_iteration/strategy_006/ab_tests/A_v2/backtest_logs/trades_paired.csv"
PANEL = PROJ / "_market_hs300_panel.parquet"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

WINDOW = 252          # 过去 1 年（含信号日）
SEGMENTS = {"S1_2015-2020": ("2015-01-01", "2020-12-31"),
            "S2_2021-2026": ("2021-01-01", "2026-12-31"),
            "S3_全期": ("2015-01-01", "2026-12-31")}


def main():
    # ── 交易 + 信号日 ──
    tr = pd.read_csv(A_V2, encoding="utf-8-sig")
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    cal = pd.DatetimeIndex(pd.to_datetime(
        con.execute("SELECT date FROM index_bar1d WHERE instrument='000300.SH' "
                    "ORDER BY date").fetchdf()["date"]))
    con.close()
    pos_cal = {d: i for i, d in enumerate(cal)}
    tr["sig_date"] = [cal[pos_cal[pd.Timestamp(e)] - 1]
                      if pd.Timestamp(e) in pos_cal and pos_cal[pd.Timestamp(e)] > 0
                      else pd.NaT for e in tr["entry_date"]]
    tr = tr.dropna(subset=["sig_date"]).copy()

    # ── 面板收盘（按 symbol 建索引）──
    p = pd.read_parquet(PANEL, columns=["date", "symbol", "close"])
    p["date"] = pd.to_datetime(p["date"])
    by_sym = {s: g.set_index("date")["close"].sort_index()
              for s, g in p.groupby("symbol")}

    # ── 每笔交易 → 十分位 ──
    dec, nwin = [], []
    for r in tr.itertuples():
        g = by_sym.get(r.symbol)
        if g is None:
            dec.append(np.nan); nwin.append(0); continue
        sd = pd.Timestamp(r.sig_date)
        if sd not in g.index:
            dec.append(np.nan); nwin.append(0); continue
        i = g.index.get_loc(sd)
        lo = max(0, i - WINDOW + 1)
        win = g.iloc[lo:i + 1]
        pct = float((win < g.iloc[i]).mean())          # 信号日收盘在窗口内的百分位
        dec.append(min(int(pct * 10) + 1, 10))
        nwin.append(len(win))
    tr["decile"] = dec
    tr["win_len"] = nwin
    tr["ok"] = tr["return_pct"] > 0
    tr = tr.dropna(subset=["decile"])
    tr["decile"] = tr["decile"].astype(int)
    full_win = (tr["win_len"] >= 200).mean()
    print(f"交易 {len(tr)} 笔 | 历史窗口≥200根占比 {full_win*100:.0f}% | "
          f"分位均中位 {tr['decile'].median():.0f} 档")

    # ── 三段 × 十档统计 ──
    out_rows = []
    for seg, (a, b) in SEGMENTS.items():
        sub = tr[(tr["sig_date"] >= a) & (tr["sig_date"] <= b)]
        ok_n, bad_n = int(sub["ok"].sum()), int((~sub["ok"]).sum())
        for d in range(1, 11):
            g = sub[sub["decile"] == d]
            g_ok, g_bad = int(g["ok"].sum()), int((~g["ok"]).sum())
            out_rows.append({
                "segment": seg, "decile": d,
                "n_ok": g_ok, "n_bad": g_bad, "n": len(g),
                "ok_share": g_ok / ok_n if ok_n else np.nan,      # 占该段成功总数
                "bad_share": g_bad / bad_n if bad_n else np.nan,  # 占该段失败总数
                "win_rate": g_ok / len(g) if len(g) else np.nan,  # 该档成功率
                "avg_ret": g["return_pct"].mean() if len(g) else np.nan,
            })
    stats = pd.DataFrame(out_rows)
    stats.to_csv(HERE / "decile_stats.csv", index=False, encoding="utf-8-sig")
    tr[["symbol", "entry_date", "sig_date", "return_pct", "ok", "decile", "win_len"]].to_csv(
        HERE / "trades_deciled.csv", index=False, encoding="utf-8-sig")

    for seg in SEGMENTS:
        s = stats[stats["segment"] == seg]
        print(f"\n═══ {seg} ═══")
        print(s[["decile", "n_ok", "n_bad", "ok_share", "bad_share", "win_rate",
                 "avg_ret"]].round(3).to_string(index=False))
    return tr, stats


if __name__ == "__main__":
    main()
