"""建期货**后复权**日线表 `future_daily_post` —— 供 cs-trend-train 期货模式画 K 线/交易用。

## 为什么要这张表
本地有两份期货数据，各有长短：
  · `future_daily`（本仓库 duckdb 视图）：**未复权**（`_meta.json: adjust=none`），字段全
    （OHLCV + amount + settlement + limit_up/down + dominant_id + exchange）
    ⇒ 主力连续**换月有假跳空**（实测螺纹换月日中位 2.06%、最大 ±10.7%；铁矿最大 20 个日涨跌幅里
      11 个是换月）—— 对"靠 high/low 撞止损线"的画线训练工具是**致命**的。
  · `data_cache/pd_k_data.db` → `[1d_k_data]`：**已后复权**（换月日 |涨跌| 中位 0.00%、最大 20 里占 0/20），
    但只有 OHLCV + oi + `adj_factor`。

本表 = 两者按 (品种短码, date) 内连接 ⇒ **既复权又字段全**。
**不动** 原 `future_daily`。

## 已验证的复权口径（写进脚本以免以后忘）
  `后复权价 = 未复权价 × adj_factor`（逐值最大相对差 2.6e-15，OHLC 四列同比例）；
  因子在换月日**比例平移**新合约价格到旧合约水平（该日收益记 0）。

产物：`future_daily_post/year=YYYY/part.parquet` + duckdb 视图 `future_daily_post`（**绝对路径**）
      —— 顺带把脆弱的 `future_daily` 视图也重建成绝对路径（它原来是相对路径，只在仓库根当 cwd 时才查得到）
用法：python build_future_daily_post.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent          # data_cache/pandadata_warehouse
REPO = ROOT.parents[1]
KDB = REPO / "data_cache" / "pd_k_data.db"
DB = ROOT / "warehouse.duckdb"
OUTDIR = ROOT / "future_daily_post"

COLS = ["symbol", "code", "date", "open", "high", "low", "close", "volume", "amount",
        "open_interest", "settlement", "pre_settlement", "limit_up", "limit_down",
        "dominant_id", "exchange", "adj_factor"]


def load_k() -> pd.DataFrame:
    """`[1d_k_data]`：**后复权** OHLCV（短码 symbol + adj_factor）。"""
    con = sqlite3.connect(str(KDB))
    k = pd.read_sql('SELECT symbol, date, open, high, low, close, vol, oi, adj_factor '
                    'FROM [1d_k_data]', con)
    con.close()
    k["code"] = k["symbol"].str.upper()
    k["date"] = pd.to_datetime(k["date"], format="%Y%m%d")
    return k.rename(columns={"vol": "volume", "oi": "open_interest"})


def load_fd() -> pd.DataFrame:
    """原 `future_daily`（未复权，但字段全）—— 直读 parquet（视图是相对路径，不可靠）。"""
    fd = (ROOT / "future_daily").resolve().as_posix()
    con = duckdb.connect()
    d = con.execute(f"""SELECT symbol, date, amount, settlement, pre_settlement,
                               limit_up, limit_down, dominant_id, exchange, underlying_symbol
                        FROM read_parquet('{fd}/**/*.parquet')""").df()
    con.close()
    d["date"] = pd.to_datetime(d["date"], format="%Y%m%d")
    d["code"] = d["underlying_symbol"].str.upper()      # 与 [1d_k_data] 的短码对齐（RB/I/JM…）
    return d


def main() -> int:
    k, d = load_k(), load_fd()
    print(f"[1d_k_data] 复权 {len(k):,} 行 / {k.code.nunique()} 品种 |  "
          f"future_daily 富字段 {len(d):,} 行")
    m = k.merge(d, on=["code", "date"], how="inner", suffixes=("", "_fd"))
    print(f"内连接 → {len(m):,} 行（应 = 172,395）")

    # ★ symbol 统一成**主连代码**（RB_DOMINANT.SHF）—— `[1d_k_data]` 那边是短码 `rb`，
    #   merge 后 `symbol` 会取到短码；这里用 future_daily 的 symbol 覆盖，短码保留在 `code`
    m["symbol"] = m["symbol_fd"]
    m["underlying_symbol"] = m["underlying_symbol"].fillna(m["code"])
    # ★ 价格列必须**同一坐标系**：OHLC 已是复权价，而 settlement/pre_settlement/limit_up/down
    #   来自未复权表 ⇒ 按同一 adj_factor 缩放，否则表内自相矛盾（实测 RB 复权 close 4466 vs
    #   未复权 limit_up 3260）。量/额（volume/amount/open_interest）是流量，**不缩放**。
    for c in ["settlement", "pre_settlement", "limit_up", "limit_down"]:
        m[c] = m[c] * m["adj_factor"]
    m = m[COLS].sort_values(["code", "date"]).reset_index(drop=True)
    m["year"] = m["date"].dt.year

    if OUTDIR.exists():
        import shutil
        shutil.rmtree(OUTDIR)
    for y, g in m.groupby("year"):
        p = OUTDIR / f"year={int(y)}"
        p.mkdir(parents=True, exist_ok=True)
        g.drop(columns=["year"]).to_parquet(p / "part.parquet", index=False, compression="zstd")
    print(f"→ {OUTDIR.name}/ （{m['year'].nunique()} 个年分区）")

    con = duckdb.connect(str(DB))
    for name, d_ in [("future_daily_post", OUTDIR), ("future_daily", ROOT / "future_daily")]:
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet("
                    f"'{d_.resolve().as_posix()}/**/*.parquet', hive_partitioning=true)")
    n, ns = con.execute("SELECT count(*), count(DISTINCT code) FROM future_daily_post").fetchone()
    con.close()
    print(f"视图 future_daily_post：{n:,} 行 / {ns} 品种")

    # ★ 校验：换月日的涨跌幅应落回非换月同量级
    print("\n=== 校验：换月日 |涨跌| vs 非换月 ===")
    for code in ["RB", "I", "M"]:
        g = m[m.code == code].reset_index(drop=True).copy()
        g["chg"] = g["close"].pct_change().abs()
        g["sw"] = g["dominant_id"] != g["dominant_id"].shift(1)
        sw = g["sw"]
        top = g["chg"].dropna().nlargest(20).index
        print(f"  {code:<3} 换月 {int(sw.sum()) - 1:>3} 次 | 换月日中位 {g.loc[sw,'chg'].median()*100:5.2f}% "
              f"非换月 {g.loc[~sw,'chg'].median()*100:5.2f}% | 最大20涨跌里换月占 "
              f"{int(g.loc[top,'sw'].sum()):>2}/20  ← 目标 0/20")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
