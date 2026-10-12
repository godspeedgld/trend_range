"""权重引擎模板 — 「目标权重表」生成器（喂 `local_weight_backtest.py --targets`）。

与 `portfolio_strategy.py`（**信号引擎**的 5 接口模板）的区别：
  · 信号引擎：引擎自己管组合记账，策略只给「入场/出场/优先序/权重」4~5 个回调，
    且**只在信号变化日交易**。
  · 权重引擎：策略直接产出**每个交易日的目标权重表**，引擎逐日把持仓
    `order_target_percent` 对齐到目标、并卖掉当天目标里没有的持仓 ——
    这正是 bigtrader `handle_data_weight_based` 的语义，**用来复现云端权重型策略**。

  两者产出的绩效**不可互换**（实测同一份 targets：权重引擎 +377.9% vs 信号引擎 −46.1%）。
  要复现云端权重型策略，**必须**用权重引擎 + 本模板；信号引擎那条路走不通。

引擎语义（详见 `scripts/local_weight_backtest.py`）：
  每个交易日 d：目标表里有 (d, instrument, weight) → 把该股拉到该权重；
  d 当天没出现在目标表里的持仓 → 清仓；`weight=0` 的行 = 显式空仓。
  ★ 空仓周**必须发 weight=0 行**（或让该日目标表为空串），否则引擎会跨桥不清仓。

本模板给出 4 个可替换点（下方均有可运行默认实现）：

  ① config_signal_dates(calendar)  何时重算目标（默认：每周最后一个交易日）
  ② pick(panel_at_t, ctx, params)  该信号日选哪些股 + 权重（★ 核心可替换点）
  ③ config_expand(targets, cal)    信号日目标 → 逐交易日（引擎逐日对齐所需）
  ④ 空仓表达：该信号日不放任何行 / 放 weight=0 行

产物：parquet，列 = `date, instrument, weight`（date 覆盖每个交易日）。

用法：
    python weight_strategy.py --panel <panel.parquet> --calendar <market.parquet> \\
        --out <targets_daily.parquet> [--factor mom_20 --top-n 6 --weight equal|inv_vol]
    python .claude/skills/skill-research-assistant/scripts/local_weight_backtest.py <project> \\
        --market-data <market.parquet> --targets <targets_daily.parquet> --output-dir <dir>
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

# ═══════════════════════════════════════════════════════════
# 接口①：信号日（何时重算目标）
# ═══════════════════════════════════════════════════════════

def config_signal_dates(calendar: pd.DatetimeIndex, freq: str = "W") -> pd.DatetimeIndex:
    """从交易日历取信号日。默认每周最后一个交易日。

    【可替换点】月频 = "M"；季度 = "Q"；固定间隔 = 自行取 cal[::k]。
    周频策略的**因子窗口也应在信号日序列上滚动**（口径一致，见 SKILL 的坑记录）。
    """
    s = pd.Series(calendar, index=calendar)
    return pd.DatetimeIndex(s.groupby(calendar.to_period(freq)).last().values)


# ═══════════════════════════════════════════════════════════
# 接口②：选股 + 权重（核心可替换点）
# ═══════════════════════════════════════════════════════════

def pick(panel_at_t: pd.DataFrame, ctx: dict, params: dict) -> pd.DataFrame:
    """单个信号日 t 选股并定权重，返回 DataFrame[instrument, weight]（可为空 = 空仓）。

    panel_at_t: 该信号日的候选面板（列含 instrument + 因子列 + 可选 vol_20）
    ctx:        上下文（如 {"prev_holdings": [...], "exposure": 1.0}）—— 缓冲/敞口用
    params:     因子列名、取前几只、权重方式等

    【可替换点】默认实现：按 `factor` 降序取前 `top_n` 只，权重 = 等权 or 波动率倒数。
    真实策略常在此处叠加：行业内选股 / 复合打分 / 持仓缓冲 / regime 切换方向 / 敞口。
    与云端对齐时，这两件事**容易踩坑**，务必复刻：
      · 复合分并列 → 用 instrument 做**显式二级排序键**（否则重跑漂移）
      · 老仓缓冲 → 保留顺序按「老仓进入先后」，容器要用**保序**的（list/dict），别用 set
    """
    df = panel_at_t.copy()
    f = params["factor"]
    df = df.dropna(subset=[f])
    if df.empty:
        return pd.DataFrame(columns=["instrument", "weight"])
    df = df.sort_values([f, "instrument"], ascending=[False, True]).head(params["top_n"])
    if params["weight"] == "inv_vol" and "vol_20" in df.columns:
        vol = df["vol_20"].fillna(df["vol_20"].median()).clip(lower=1e-4)
        w = (1.0 / vol) / (1.0 / vol).sum()
    else:
        w = pd.Series(1.0 / len(df), index=df.index)
    exposure = float(ctx.get("exposure", 1.0))
    return pd.DataFrame({"instrument": df["instrument"].values,
                         "weight": (w.values * exposure)})


# ═══════════════════════════════════════════════════════════
# 接口③：信号日目标 → 逐交易日
# ═══════════════════════════════════════════════════════════

def config_expand(targets: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """把「信号日目标」铺到每个交易日 —— 引擎逐日对齐所需（对标云端 expand_to_daily）。

    targets: DataFrame[date(信号日), instrument, weight]
    规则：信号日 d0 的目标 [d0, d1] 每日重复（d1 = 下一信号日，末期用 cal[-1]），
          边界日取**新**信号（keep="last"）。
    ★ 空仓：d0 无任何行 → 该区间自然无行 → 引擎逐日看到「目标里没有」→ 清仓。
    """
    tg = targets.copy()
    tg["date"] = pd.to_datetime(tg["date"])
    sig = sorted(tg["date"].unique())
    frames = []
    for k, d0 in enumerate(sig):
        d1 = sig[k + 1] if k + 1 < len(sig) else calendar[-1]
        w = tg.loc[tg["date"] == d0, ["instrument", "weight"]]
        for dt in calendar[(calendar >= d0) & (calendar <= d1)]:
            f = w.copy()
            f["date"] = dt
            frames.append(f)
    if not frames:
        return pd.DataFrame(columns=["date", "instrument", "weight"])
    out = pd.concat(frames, ignore_index=True).drop_duplicates(
        subset=["date", "instrument"], keep="last")
    return out[["date", "instrument", "weight"]].sort_values(["date", "instrument"]).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# 串联 + CLI
# ═══════════════════════════════════════════════════════════

def build_targets(panel: pd.DataFrame, calendar: pd.DatetimeIndex, **params) -> pd.DataFrame:
    p = {"factor": "mom_20", "top_n": 6, "weight": "equal", "freq": "W"}
    p.update(params)
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"])
    sig_dates = config_signal_dates(calendar, p["freq"])
    rows = []
    prev: list[str] = []
    for t in sig_dates:
        sub = panel[panel["date"] == t]
        if sub.empty:
            prev = []
            continue                                  # 该信号日无候选 → 空仓
        ctx = {"prev_holdings": prev, "exposure": 1.0}
        r = pick(sub.rename(columns={"symbol": "instrument"}), ctx, p)
        if r.empty:
            prev = []
            continue                                  # 无合格候选 → 空仓
        r.insert(0, "date", t)
        rows.append(r)
        prev = r["instrument"].tolist()
    sig_tgts = (pd.concat(rows, ignore_index=True) if rows
                else pd.DataFrame(columns=["date", "instrument", "weight"]))
    return config_expand(sig_tgts, calendar)


def main() -> int:
    ap = argparse.ArgumentParser(description="权重引擎模板：生成目标权重表")
    ap.add_argument("--panel", required=True, help="候选面板 parquet（列含 date,symbol,因子…）")
    ap.add_argument("--calendar", required=True, help="行情 parquet（取 date 列作为交易日历）")
    ap.add_argument("--out", required=True, help="产物 parquet（date,instrument,weight）")
    ap.add_argument("--factor", default="mom_20")
    ap.add_argument("--top-n", type=int, default=6)
    ap.add_argument("--weight", default="equal", choices=["equal", "inv_vol"])
    ap.add_argument("--freq", default="W", choices=["W", "M", "Q"])
    a = ap.parse_args()

    panel = pd.read_parquet(a.panel)
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(pd.read_parquet(a.calendar, columns=["date"])["date"]).unique()))
    out = build_targets(panel, cal, factor=a.factor, top_n=a.top_n, weight=a.weight, freq=a.freq)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(a.out, index=False)
    print(f"信号日 {config_signal_dates(cal, a.freq).size} 个 → 逐日 {len(out):,} 行 / {out['date'].nunique()} 交易日")
    print(f"  → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
