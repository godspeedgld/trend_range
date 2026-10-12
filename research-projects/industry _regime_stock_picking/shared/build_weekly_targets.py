"""共享预计算 —— 每周目标持仓表 + 引擎输入行情（多迭代共用）。

把策略决策（变盘指数 regime → 选 3 行业 → 行业内四因子复合排名选 2 只 → 缓冲 → 权重）
**预计算**成查表文件，供 `strategy.py` 的 5 接口 O(1) 查询。这是本工程既定模式
（analysis_001 同款：策略逻辑预计算、strategy.py 只查表）。

★ 缓冲依赖"当前持仓"，故本脚本**逐周模拟一遍理想持仓序列**（无成本、无停牌影响）来确定
  每周目标。引擎实际执行时若因停牌未能买入，目标表不随之调整 —— 属已知小偏差。

产物（`shared/_cache/`）：
  weekly_plan.parquet      所有信号日的 regime / top3 / exposure（含空仓周）
  weekly_targets.parquet   满仓周的目标持仓 (signal_date, symbol, weight, ...)
  engine_market.parquet    引擎输入行情 (date, symbol, open, high, low, close, name)

用法：MODE=regime|baseline  python build_weekly_targets.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                      # trend_range
CACHE = HERE / "_cache"
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"

MODE = os.environ.get("MODE", "regime")     # regime（迭代一）| baseline（云端原版·恒反转）
# ★ 2026-09-28 扩展（向后兼容）：UNIVERSE=index（默认，三指数成分）| full（全市场）
#   与 build_stock_panel.py 的 UNIVERSE 配套——读/写文件名都带后缀，互不覆盖。
UNIVERSE = os.environ.get("UNIVERSE", "index")
SUFFIX = "" if UNIVERSE == "index" else f"_{UNIVERSE}"
N_IND, N_PER_IND, BUF_MULT = 3, 2, 3
FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]

BT_START, BT_END = "2016-12-01", "2026-08-21"   # 引擎行情范围（略早于首个信号日）


def pick_industries(ind_day: pd.DataFrame, t_prime: float) -> tuple[list[str], str]:
    if t_prime < 0:
        return ind_day.nlargest(N_IND, "mom_240")["ind_name"].tolist(), "momentum"
    return ind_day.nsmallest(N_IND, "mom_60")["ind_name"].tolist(), "reversal"


def score_stocks(sub: pd.DataFrame, dirs: dict) -> pd.Series:
    return pd.concat([sub[f].mul(dirs[f]).rank(pct=True) for f in FACTORS],
                     axis=1).mean(axis=1)


def build_targets(cand: pd.DataFrame, inds: list[str], dirs: dict,
                  held: set) -> dict[str, list[str]]:
    """每行业挑 2 只；老仓在行业内前 N_PER_IND×BUF_MULT=6 名内则保留（降换手）。"""
    buf = N_PER_IND * BUF_MULT
    out = {}
    for ind in inds:
        sub = cand[cand["ind_name"] == ind].copy()
        if sub.empty:
            out[ind] = []
            continue
        sub["score"] = score_stocks(sub, dirs)
        # ★ 2026-10-12：并列破除加 instrument 二级键。云端注释明确：复合分约 1/3 存在并列，
        #   不显式定序则名次由上游行序决定 → 同一份数据重跑结果漂移（云端实测年化差 0.5pp）。
        ranked = sub.sort_values(["score", "symbol"], ascending=[False, True])["symbol"].tolist()
        targets = [s for s in ranked[:buf] if s in held]
        for s in ranked:
            if len(targets) >= N_PER_IND:
                break
            if s not in targets:
                targets.append(s)
        out[ind] = targets[:N_PER_IND]
    return out


def main():
    ind = pd.read_parquet(CACHE / "industry_index.parquet")
    reg = pd.read_parquet(CACHE / "regime.parquet")
    import os as _os2
    _panel_sfx = "_indpre" if _os2.environ.get("IND", "component") == "prefactors" else ""
    _price_sfx = "_rawpx" if _os2.environ.get("PRICE", "hfq") == "raw" else ""
    panel = pd.read_parquet(CACHE / f"signal_panel{SUFFIX}{_panel_sfx}.parquet")

    regi = reg.set_index("date")
    indi = {d: g for d, g in ind.groupby("date")}
    panel_by_day = {d: g for d, g in panel.groupby("date")}

    plan_rows, tgt_rows = [], []
    positions: dict[str, str] = {}          # symbol -> ind_name（理想持仓）
    prev_top3 = None

    for t in sorted(panel["date"].unique()):
        if t not in regi.index:
            continue
        tp = regi.at[t, "T_prime"]
        if pd.isna(tp):
            continue
        day = indi.get(t)
        cand = panel_by_day.get(t)
        if day is None or cand is None:
            continue
        top3, regime = pick_industries(day, float(tp))
        exposure = 1.0 if (prev_top3 is not None and set(top3) == set(prev_top3)) else 0.0
        if MODE == "baseline":
            dirs = {f: -1 for f in FACTORS}
        else:
            dirs = {f: (1 if regime == "momentum" else -1) for f in FACTORS}

        exec_date = cand["exec_date"].iloc[0]
        plan_rows.append({"signal_date": t, "exec_date": exec_date, "regime": regime,
                          "T_prime": float(tp), "top3": ",".join(top3), "exposure": exposure})

        # ★ 2026-10-12 对齐云端 build_holdings：
        #   ① 空仓周**也要发出行**（exposure=0 → weight=0）。否则策略侧 expand_to_daily
        #      只在满仓信号日之间铺权重 → 空仓周被"跨桥"，实际从不清仓；
        #   ② held（缓冲记忆）**跨空仓周延续** —— 云端 held 只在行业轮出时 pop，
        #      不因 exposure=0 清空。
        targets = build_targets(cand, top3, dirs, set(positions))
        new_pos = {}
        for ind_name, syms in targets.items():
            if not syms:
                continue
            sub = cand[cand["symbol"].isin(syms)].set_index("symbol")
            inv = 1.0 / sub["vol_20"].clip(lower=1e-6)
            w = inv / inv.sum()
            for s in syms:
                new_pos[s] = ind_name
                tgt_rows.append({"signal_date": t, "exec_date": exec_date,
                                 "symbol": s, "ind_name": ind_name, "regime": regime,
                                 "weight": float(exposure * w[s] / N_IND)})
        positions = new_pos
        prev_top3 = top3

    plan = pd.DataFrame(plan_rows)
    tgts = pd.DataFrame(tgt_rows)
    plan.to_parquet(CACHE / "weekly_plan.parquet", index=False)
    tgts.to_parquet(CACHE / f"weekly_targets_{MODE}{SUFFIX}{_panel_sfx}{_price_sfx}.parquet", index=False)
    print(f"[{MODE}] weekly_plan: {len(plan)} 信号日（满仓 {int(plan['exposure'].sum())}）")
    print(f"[{MODE}] weekly_targets: {len(tgts):,} 行 / {tgts['symbol'].nunique()} 只")
    wsum = tgts.groupby("signal_date")["weight"].sum()
    print(f"  每满仓周权重合计: 均值 {wsum.mean():.4f}  最小 {wsum.min():.4f} "
          f"最大 {wsum.max():.4f}（应≈1.0）")

    # ── 引擎输入行情（回测期 · 全部候选股）──
    # ★ 2026-10-12：行情与 MODE 无关（只取决于 panel + PRICE 开关），原 `if MODE=="regime"`
    #   让 baseline 模式建不出行情文件 → 改为两种模式都建
    if MODE in ("regime", "baseline"):
        import duckdb
        syms = sorted(panel["symbol"].unique())
        con = duckdb.connect(str(WAREHOUSE), read_only=True)
        inlist = ",".join(repr(s) for s in syms)
        # ★ PRICE 开关（2026-10-12）：云端 bigtrader 用**原始价**成交
        #   （实证：云端 5,548 笔成交价 = 后复权价÷adjust_factor，99.7% 逐笔吻合）
        #   本地原用后复权价 → PRICE=raw 还原真实价格交易
        import os as _os
        _raw = _os.environ.get("PRICE", "hfq") == "raw"
        _px = ("open / adjust_factor AS open, high / adjust_factor AS high, "
               "low / adjust_factor AS low, close / adjust_factor AS close"
               if _raw else "open, high, low, close")
        mk = con.execute(f"""
            SELECT date, instrument AS symbol, {_px}, name
            FROM stock_bar1d
            WHERE instrument IN ({inlist}) AND date >= '{BT_START}' AND date <= '{BT_END}'
        """).fetchdf()
        con.close()
        mk["date"] = pd.to_datetime(mk["date"])
        mk = mk.sort_values(["symbol", "date"]).reset_index(drop=True)
        mk.to_parquet(CACHE / f"engine_market{SUFFIX}{_panel_sfx}{_price_sfx}.parquet", index=False)
        print(f"[market] {len(mk):,} 行 / {mk['symbol'].nunique()} 只 / "
              f"{mk['date'].min().date()} ~ {mk['date'].max().date()}")


if __name__ == "__main__":
    main()
