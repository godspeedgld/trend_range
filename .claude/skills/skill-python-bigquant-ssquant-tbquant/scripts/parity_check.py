#!/usr/bin/env python
"""移植对账（六层比对 + 交易对账）—— 移植产物的标准验收工具。

用法（云端先跑模板最后一个"诊断导出"cell，下载 cloud_export/ 后）：
  python parity_check.py \
    --cloud-export outputs/bigquant/cloud_export \
    --panel <本地面板.parquet> \        # L1/L2（symbol 列）
    --events <本地事件.parquet> \       # L3（symbol/date/degree/line；缺省跳过）
    --warehouse <duckdb> \              # L4/L5/L6（index_bar1d + index_component）
    --index-code 000300.SH \
    --cloud-trades outputs/bigquant/csv.csv \      # L7（可选）
    --local-trades <trades_paired.csv>             # L7（可选）

七层（任何一层 FAIL 都直接解释交易分歧）：
  L1 原始数据：probe OHLC vs 本地面板 → 复权/数据源差异
  L2 指标：probe ATR14(Wilder)/ma20/sd20 vs 本地重算 → 兜底重算传导验证
  L3 事件表：signals.csv vs 本地事件缓存 → line/degree/键差异
  L4 年线闸门 + 暖期边界
  L5 指数日线
  L6 成分月末快照
  L7 交易对账：交集开仓的平仓同步率/收益差 + 分叉方向（单边倒=执行层 bug）

验收标准（strategy_006 实证基线）：
  L1-L6 偏差浮点级（<1e-9）；L7 平仓同步率 ≥95% 且同步笔收益差 ≈ 佣金口径（<1pp）；
  分叉笔方向不应单边倒（全早卖/全晚卖 = 撮合或指标口径 bug，非随机分歧）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def head(t):
    print(f"\n═══ {t} ═══")


def rel_diff(a, b):
    return (a - b).abs() / b.abs()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cloud-export", required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--events", default=None)
    ap.add_argument("--warehouse", default=None)
    ap.add_argument("--index-code", default="000300.SH")
    ap.add_argument("--index-table", default="index_bar1d")
    ap.add_argument("--component-table", default="index_component")
    ap.add_argument("--cloud-trades", default=None, help="云端成交明细 csv（普通成交/除权除息列）")
    ap.add_argument("--local-trades", default=None, help="本地 trades_paired.csv")
    ap.add_argument("--start", default="2015-01-01", help="闸门比对同窗起点")
    args = ap.parse_args()

    CE = Path(args.cloud_export)
    if not CE.exists():
        print(f"❌ 未找到 {CE}——先在 aistudio 跑诊断导出 cell 并下载 cloud_export/")
        return 1

    # ═══ L1 原始数据 ═══
    head("L1 原始数据：probe OHLC vs 本地面板")
    probe = pd.read_csv(CE / "panel_probe.csv", encoding="utf-8-sig")
    probe["date"] = pd.to_datetime(probe["date"])
    panel = pd.read_parquet(args.panel)
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel.dropna(subset=["close"])
    m = probe.merge(panel, left_on=["instrument", "date"],
                    right_on=["symbol", "date"], how="left", suffixes=("_c", "_l"))
    matched = m["close_l"].notna()
    r = rel_diff(m.loc[matched, "close_c"].astype(float), m.loc[matched, "close_l"].astype(float))
    sym_c, sym_l = set(probe["instrument"]), set(panel["symbol"].unique())
    ok1 = matched.mean() > 0.95 and (r < 1e-9).mean() > 0.999
    print(f"probe {len(probe)} 行：键匹配 {matched.mean()*100:.2f}%；"
          f"close 相对偏差 >1e-9 占比 {(r >= 1e-9).mean()*100:.3f}%（最大 {r.max():.1e}）")
    print(f"标的集合: 云端 {len(sym_c)} / 本地 {len(sym_l)} / 仅云端 {len(sym_c - sym_l)} / 仅本地 {len(sym_l - sym_c)}")
    if not ok1 and (r >= 1e-9).any():
        w = m.loc[matched][r >= 1e-9]
        print(w[["instrument", "date", "close_c", "close_l"]].head(5).to_string(index=False))
    print("L1:", "PASS" if ok1 else "⚠ 检查上方样例（复权口径/数据源差异）")

    # ═══ L2 指标 ═══
    head("L2 指标：ATR14(Wilder) / ma20 / sd20 vs 本地重算")
    loc = []
    for sym, g in panel.groupby("symbol"):
        g = g.dropna(subset=["high", "low", "close"]).copy()
        if len(g) < 15:
            continue
        h, l, c = g["high"].to_numpy(float), g["low"].to_numpy(float), g["close"].to_numpy(float)
        pc = np.concatenate([[np.nan], c[:-1]])
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        tr[0] = h[0] - l[0]
        g["atr14_l"] = pd.Series(tr).ewm(alpha=1/14, adjust=False, min_periods=14).mean().to_numpy()
        g["ma20_l"] = g["close"].rolling(20).mean()
        g["sd20_l"] = g["close"].rolling(20).std()
        loc.append(g[["symbol", "date", "atr14_l", "ma20_l", "sd20_l"]])
    loc = pd.concat(loc)
    j = probe.merge(loc, left_on=["instrument", "date"], right_on=["symbol", "date"], how="inner")
    for cc, ll, name in [("atr14", "atr14_l", "ATR14"), ("ma20", "ma20_l", "MA20"), ("sd20", "sd20_l", "SD20")]:
        ok = j[ll].notna() & j[cc].notna()
        rr = rel_diff(j.loc[ok, cc].astype(float), j.loc[ok, ll])
        # ATR 允许停牌 NaN 处理差异造成的极少离群；看 P99
        print(f"{name}: 可比 {ok.sum()} 行 / 中位 {rr.median():.1e} / P99 {rr.quantile(.99):.1e} / 最大 {rr.max():.1e}")

    # ═══ L3 事件表 ═══
    if args.events:
        head("L3 事件表：signals.csv vs 本地事件缓存（同日 degree 最大 + ≤max_degree）")
        sig = pd.read_csv(CE / "signals.csv", encoding="utf-8-sig")
        sig["date"] = pd.to_datetime(sig["date"])
        ev = pd.read_parquet(args.events)
        ev["date"] = pd.to_datetime(ev["date"])
        ev = (ev.sort_values("degree", ascending=False)
                .drop_duplicates(["symbol", "date"], keep="first"))
        maxdeg = int(sig["degree"].max()) if len(sig) else 5
        ev = ev[ev["degree"] <= maxdeg]
        j3 = sig.merge(ev, left_on=["instrument", "date"], right_on=["symbol", "date"],
                       how="outer", suffixes=("_c", "_l"), indicator=True)
        both, only_c = j3[j3["_merge"] == "both"], j3[j3["_merge"] == "left_only"]
        only_l = j3[j3["_merge"] == "right_only"]
        # 回测期内的键差异才是问题：本地事件若被截到回测起点，仅云端多出的暖期事件不算 FAIL
        print(f"事件: 云端 {len(sig)} / 本地 {len(ev)} / 交集 {len(both)} / 仅云端 {len(only_c)} / 仅本地 {len(only_l)}")
        if len(both):
            deg_ok = (both["degree_c"] == both["degree_l"]).mean() * 100
            lr = rel_diff(both["line_c"].astype(float), both["line_l"].astype(float))
            print(f"交集: degree 一致 {deg_ok:.2f}% / line 偏差中位 {lr.median():.1e} / P99 {lr.quantile(.99):.1e}")
        if len(only_l):
            print("⚠ 回测期内本地有而云端无的事件（需人工看样例）:")
            print(only_l[["symbol", "date", "degree_l", "line_l"]].head(5).to_string(index=False))
        elif len(both) and deg_ok > 99.9 and lr.quantile(.99) < 1e-9:
            print("L3: PASS")
    else:
        print("\n（--events 未提供，跳过 L3）")

    # ═══ L4/L5/L6（需 warehouse）═══
    if args.warehouse:
        import duckdb
        con = duckdb.connect(args.warehouse, read_only=True)
        idx = con.execute(f"SELECT date, close FROM {args.index_table} "
                          f"WHERE instrument='{args.index_code}' ORDER BY date").fetchdf()
        comp = con.execute(f"SELECT date, member_code FROM {args.component_table} "
                           f"WHERE instrument='{args.index_code}'").fetchdf()
        con.close()
        idx["date"] = pd.to_datetime(idx["date"])
        comp["date"] = pd.to_datetime(comp["date"])

        head("L4 年线闸门 + 暖期")
        lines = (CE / "runtime.txt").read_text(encoding="utf-8").splitlines()
        neb = [x.split("=")[1] for x in lines if x.startswith("no_entry_before")][0]
        bull_c = {pd.Timestamp(x.split("=")[1]) for x in lines if x.startswith("bull=")}
        s = idx.set_index("date")["close"]
        s = s[s.index >= pd.Timestamp(args.start)]
        ma200 = s.rolling(200).mean()
        notfull = ma200.isna()          # SQL 窗口不足 200 行=已有行均值（爬坡），同口径模拟
        ma200[notfull] = s.expanding().mean()[notfull]
        bull_l = set(s.index[(s > ma200).fillna(False)])
        print(f"no_entry_before = {neb}")
        print(f"bull 天数（{args.start}+ 同窗）: 云端 {len(bull_c)} / 本地 {len(bull_l)} / 对称差 {len(bull_c ^ bull_l)}")
        if bull_c ^ bull_l:
            d = sorted(bull_c ^ bull_l)
            in_bt = [x for x in d if x >= pd.Timestamp(args.start)]
            print(f"差异日 {len(d)} 天，样例: {[x.date().isoformat() for x in d[:8]]}")
            print("（若差异集中在 SQL 爬坡期[窗满前]属口径噪声，回测期外可忽略）")

        head("L5 指数日线")
        ic = pd.read_csv(CE / "index.csv", encoding="utf-8-sig")
        ic["date"] = pd.to_datetime(ic["date"])
        j5 = ic.merge(idx, on="date", suffixes=("_c", "_l"))
        r5 = rel_diff(j5["close_c"], j5["close_l"])
        print(f"指数: 云端 {len(ic)} / 匹配 {len(j5)} / close 偏差中位 {r5.median():.1e} / 最大 {r5.max():.1e}")

        head("L6 成分月末快照")
        cc = pd.read_csv(CE / "component_monthly.csv", encoding="utf-8-sig")
        cc["date"] = pd.to_datetime(cc["date"])
        cd = {d: set(g["member_code"]) for d, g in comp.groupby("date")}
        n_same = n_diff = 0
        diffs = []
        for d, g in cc.groupby("date"):
            earlier = [x for x in cd if x <= d]
            if not earlier:
                continue
            cs, lm = set(g["member_code"]), cd[max(earlier)]
            if cs == lm:
                n_same += 1
            else:
                n_diff += 1
                diffs.append((d.date(), len(cs - lm), len(lm - cs)))
        print(f"月末快照: 一致 {n_same} / 不一致 {n_diff}")
        if diffs:
            print("不一致月（日期, 仅云端, 仅本地）:", diffs[:8])
    else:
        print("\n（--warehouse 未提供，跳过 L4/L5/L6）")

    # ═══ L7 交易对账 ═══
    if args.cloud_trades and args.local_trades:
        head("L7 交易对账：交集开仓 → 平仓同步率 + 收益差 + 分叉方向")
        cl = pd.read_csv(args.cloud_trades, encoding="utf-8-sig")
        cl = cl[cl["成交类型"] == "普通成交"].copy()
        cl["date"] = pd.to_datetime(cl["日期"])
        sells = cl[cl["买/卖"] == "卖出"]
        buys = cl[cl["买/卖"] == "买入"][["date", "证券代码"]].rename(
            columns={"date": "entry"}).sort_values("entry")
        pairs = []
        for _, s_ in sells.iterrows():
            b = buys[(buys["证券代码"] == s_["证券代码"]) & (buys["entry"] <= s_["date"])].tail(1)
            if len(b):
                ret = float(str(s_["平仓盈亏"]).split("/")[1].strip("%")) if "/" in str(s_["平仓盈亏"]) else np.nan
                pairs.append({"sym": s_["证券代码"], "entry": b["entry"].iloc[0],
                              "exit": s_["date"], "cret": ret})
        cp = pd.DataFrame(pairs)
        lo = pd.read_csv(args.local_trades, encoding="utf-8-sig")
        lo["entry_date"] = pd.to_datetime(lo["entry_date"])
        lo["exit_date"] = pd.to_datetime(lo["exit_date"])
        mm = cp.merge(lo, left_on=["sym", "entry"], right_on=["symbol", "entry_date"], how="inner")
        mm["gap"] = (mm["exit"] - mm["exit_date"]).abs().dt.days
        sync = mm[mm["gap"] <= 3]
        far = mm[mm["gap"] > 3]
        rate = len(sync) / len(mm) * 100 if len(mm) else 0
        print(f"云端平仓 {len(cp)} / 本地 {len(lo)} / 交集开仓 {len(mm)}")
        print(f"平仓同步率(±3天): {len(sync)}/{len(mm)} = {rate:.1f}%   {'✅ ≥95%' if rate >= 95 else '❌ <95% → 执行/指标层有 bug'}")
        if len(sync):
            d7 = sync["cret"] - sync["return_pct"]
            print(f"同步笔收益差(云端-本地): 均值 {d7.mean():+.2f}pp / 中位 {d7.median():+.2f}pp"
                  f"   {'✅ ≈佣金口径(<1pp)' if abs(d7.median()) < 1 else '❌ >1pp'}")
        if len(far):
            early = (far["exit"] < far["exit_date"]).sum()
            one_sided = len(far) >= 5 and (early == 0 or early == len(far))
            tag = (f"   ❌ 单边倒({'全晚卖→指标口径偏松/兜底未传导到 pivot' if early == 0 else '全早卖→指标口径偏紧'})"
                   if one_sided else "（双向或样本少，随机分歧）")
            print(f"分叉 {len(far)} 笔：云端早卖 {early} / 晚卖 {len(far) - early}{tag}")
            print(f"分叉收益: 云端 {far['cret'].mean():+.2f}% vs 本地 {far['return_pct'].mean():+.2f}%")
            print(far.nsmallest(5, "cret")[["sym", "entry", "exit", "exit_date", "cret", "return_pct"]].to_string(index=False))
        print(f"开仓端: 云端独有 {len(cp) - len(mm)} / 本地独有 {len(lo) - len(mm)}")
    elif args.cloud_trades or args.local_trades:
        print("\n（L7 需同时提供 --cloud-trades 与 --local-trades，跳过）")

    print("\n═══ 完 ═══ 分层定位：L1/L2 差 → 原始数据；L3 差 → 事件表；L4/L5/L6 差 → 闸门/指数/成分；"
          "全 PASS 而交易分歧 → 撮合/资金执行层（真实现金/涨跌停/停牌）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
