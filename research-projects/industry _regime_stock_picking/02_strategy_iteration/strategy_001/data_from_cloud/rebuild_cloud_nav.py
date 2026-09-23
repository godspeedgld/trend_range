"""用云端成交明细重建云端净值曲线（对账用）。

云端只给了逐笔成交（csv.csv，5548 行），没给净值序列。本脚本用本地 warehouse 的
**真实价**（`stock_bar1d.open|close ÷ adjust_factor`，已用成交价逐笔验证吻合）重建
每日持仓市值 → 净值曲线，供与本地 baseline 对账。

口径：
  · 初始现金 500,000（code.txt 的 CAPITAL_BASE，非 context.txt 说的 1000 万）
  · 买入 cash -= 成交金额 + 交易费用；卖出 cash += 成交金额 − 交易费用
  · 「除权除息」记录 qty=0、amount=现金分红 → 同样计入现金（fee = 红利税）
  · 日终市值 = cash + Σ 持仓股数 × 当日真实收盘价
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]                      # trend_range
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
INIT_CASH = 500_000.0


def load_prices(symbols: list[str]) -> pd.DataFrame:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    inlist = ",".join(repr(s) for s in symbols)
    df = con.execute(f"""
        SELECT date, instrument AS symbol, open, close, adjust_factor
        FROM stock_bar1d WHERE instrument IN ({inlist})
    """).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["real_open"] = df["open"] / df["adjust_factor"]
    df["real_close"] = df["close"] / df["adjust_factor"]
    return df


def main():
    tr = pd.read_csv(HERE / "csv.csv", encoding="utf-8-sig")
    tr.columns = ["date", "time", "symbol", "name", "side", "qty", "price",
                  "amount", "pnl", "fee", "type"]
    tr["date"] = pd.to_datetime(tr["date"])
    symbols = sorted(tr["symbol"].unique())
    print(f"云端成交 {len(tr):,} 笔 / {len(symbols)} 只 / "
          f"{tr['date'].min().date()} ~ {tr['date'].max().date()}")

    px = load_prices(symbols)
    print(f"价格 {len(px):,} 行")

    # ── 校验：成交价 vs open/af ──
    chk = tr[tr["type"] == "普通成交"].merge(
        px[["date", "symbol", "real_open"]], on=["date", "symbol"], how="left")
    chk = chk[chk["real_open"].notna()]
    err = (chk["price"] / chk["real_open"] - 1).abs()
    print(f"成交价 vs 开盘真实价：{len(chk):,} 笔可比，"
          f"中位偏差 {err.median():.4%}，>1% 的 {int((err > 0.01).sum())} 笔")

    close_px = px.pivot_table(index="date", columns="symbol",
                              values="real_close").sort_index().ffill()
    all_days = close_px.index

    # ── 逐日重建 ──
    d0, d1 = tr["date"].min(), tr["date"].max()
    days = all_days[(all_days >= d0) & (all_days <= d1)]
    trades_by_day = {d: g for d, g in tr.groupby("date")}

    cash = INIT_CASH
    pos: dict[str, float] = {}
    rows = []
    for d in days:
        for r in trades_by_day.get(d, pd.DataFrame()).itertuples():
            if r.side == "买入":
                cash -= r.amount + r.fee
                pos[r.symbol] = pos.get(r.symbol, 0.0) + r.qty
            else:
                cash += r.amount - r.fee
                if r.qty > 0:
                    pos[r.symbol] = pos.get(r.symbol, 0.0) - r.qty
        mv = 0.0
        for s, q in pos.items():
            if q == 0:
                continue
            p = close_px.at[d, s] if s in close_px.columns else np.nan
            if pd.notna(p):
                mv += q * p
        rows.append({"date": d, "cash": cash, "mv": mv, "nav": cash + mv,
                     "n_pos": sum(1 for q in pos.values() if q != 0)})

    nav = pd.DataFrame(rows)
    nav["ret"] = nav["nav"].pct_change().fillna(nav["nav"].iloc[0] / INIT_CASH - 1)
    nav["dd"] = nav["nav"] / nav["nav"].cummax() - 1

    n = len(nav)
    total = nav["nav"].iloc[-1] / INIT_CASH - 1
    ann = (1 + total) ** (252 / n) - 1
    vol = nav["ret"].std() * np.sqrt(252)
    out = HERE / "cloud_nav_rebuilt.csv"
    nav.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"\n=== 重建的云端净值（{days[0].date()} ~ {days[-1].date()}，{n} 交易日）===")
    print(f"  期末净值 {nav['nav'].iloc[-1]:,.0f}  累计 {total:+.1%}")
    print(f"  年化 {ann:+.2%}  波动 {vol:.2%}  Sharpe {ann/vol:.3f}  "
          f"最大回撤 {nav['dd'].min():.1%}")
    print(f"  期末持仓 {int(nav['n_pos'].iloc[-1])} 只")
    print(f"  （云端报告：累计 +801.23% / 夏普 1.04 / 回撤 −23.87%）")
    print(f"\n→ {out}")

    # 分年收益
    yr = nav.set_index("date")["nav"].groupby(lambda d: d.year)
    yr = ((yr.last() / yr.first()) - 1).mul(100).round(2)
    print("\n分年收益(%):")
    print(yr.to_string())


if __name__ == "__main__":
    main()
