"""比较【云端 vs 本地】的因子值 —— 定位「哪个因子算得不对」。

用法：
  1. 云端跑 `cloud_code_with_industry_log.py/.ipynb` → 得 `panel_2026.parquet`
  2. 本地跑 `local_factor_export.py` → 得 `local_panel_2026.parquet`
  3. 两个文件都在本目录时，跑本脚本

前提（已证实）：**每个调仓日选中的 3 个行业，本地与云端完全一致**（494/494 周）。
所以两边比的是同一批「调仓日 × 行业」，差异只能来自因子值或候选股集合。

比较三段：
  段1 身份   调仓日 / 候选股集合 / 逐日只数        → 池口径差异
  段2 因子   turn_ratio / px_ma20 / mom_20 /
             liq_amount / vol_stock 逐值比          → **直接回答哪个因子算得不对**
  段3 排名   行业内复合分 top2 是否一致            → 连到「为什么选出来的股不同」

判定：`|Δ| <= atol + rtol*|本地值|`（atol=1e-12, rtol=1e-9）。
  纯绝对阈值会被 liq_amount（量级 1e9）的 float64 舍入误判；
  纯相对阈值会被 px_ma20 过零点（值 ~1e-12）误判。

产物：`factor_diag_report.txt`（中文报告）· `factor_diff.csv`（逐列汇总）
      `factor_value_diff.csv`（逐值长表）
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
sys.path.insert(0, str(PROJ))
from shared.build_panel import CODE2NAME      # noqa: E402  （801 码 → 行业名）

KEY = ["date", "instrument"]
FACTORS = ["turn_ratio", "px_ma20", "mom_20", "liq_amount"]
ALL = FACTORS + ["vol_stock"]
ATOL, RTOL = 1e-12, 1e-9

_LINES: list[str] = []


def say(s: str = "") -> None:
    print(s)
    _LINES.append(s)


def load(stem: str, label: str) -> pd.DataFrame | None:
    for suf in (".parquet", ".csv.gz", ".csv"):
        f = HERE / f"{stem}{suf}"
        if f.exists():
            df = pd.read_parquet(f) if suf == ".parquet" else pd.read_csv(f)
            df["date"] = pd.to_datetime(df["date"])
            df = df.rename(columns={"instrument": "instrument", "symbol": "instrument"})
            if "ind_code" in df.columns:
                df["ind_code"] = df["ind_code"].astype(str).str.replace(r"\.SWI$", "",
                                                                       regex=True)
            print(f"{label}: {len(df):,} 行 × {df.shape[1]} 列 / {df.date.nunique()} 个信号日 / "
                  f"{df.instrument.nunique():,} 只  （{f.name}）")
            return df
    print(f"[缺] 未找到 {stem}.parquet —— {'请先在云端跑' if label.startswith('云端') else '请先跑 local_factor_export.py'}")
    return None


def diff_stats(a: pd.Series, b: pd.Series) -> dict | None:
    """a=云端, b=本地。"""
    both = a.notna() & b.notna()
    if not both.any():
        return None
    x, y = a[both].astype(float), b[both].astype(float)
    d = (x - y).abs()
    tol = ATOL + RTOL * y.abs()
    return {"n": int(both.sum()),
            "one_sided": int((a.notna() ^ b.notna()).sum()),
            "ok": float((d <= tol).mean()),
            "med_abs": float(d.median()),
            "med_rel": float((d / y.abs().clip(lower=1e-12)).median()),
            "max_rel": float((d / y.abs().clip(lower=1e-12)).max())}


def main():
    say("=" * 96)
    say("因子对账：【云端 cn_stock_prefactors + DAI 宏】 vs 【本地 BigQuant 仓库 + Python 自算】")
    say("=" * 96)
    say(f"判定：|Δ| <= {ATOL:g} + {RTOL:g}×|本地值|")
    cl = load("panel_2026", "云端")
    lo = load("local_panel_2026", "本地")
    if cl is None or lo is None:
        (HERE / "factor_diag_report.txt").write_text("\n".join(_LINES), encoding="utf-8")
        raise SystemExit("缺文件，无法对账。")

    # ==================== 段1 身份 ====================
    say("\n" + "=" * 96 + "\n段1 身份：调仓日 / 候选股集合\n" + "=" * 96)
    dc, dl = set(cl["date"].unique()), set(lo["date"].unique())
    say(f"  调仓日：云端 {len(dc)}  本地 {len(dl)}  交集 {len(dc & dl)}")
    if dc - dl:
        say(f"    仅云端 {sorted(str(d)[:10] for d in dc - dl)[:8]}")
    if dl - dc:
        say(f"    仅本地 {sorted(str(d)[:10] for d in dl - dc)[:8]}")
    sc, sl = set(cl["instrument"]), set(lo["instrument"])
    say(f"  股票：云端 {len(sc):,}  本地 {len(sl):,}  交集 {len(sc & sl):,}  "
        f"仅云端 {len(sc - sl):,}  仅本地 {len(sl - sc):,}")

    say(f"\n  逐日候选股数（云端 vs 本地）：")
    a = cl.groupby("date").size().rename("云端")
    b = lo.groupby("date").size().rename("本地")
    cmp = pd.concat([a, b], axis=1).dropna()
    cmp["差"] = cmp["本地"] - cmp["云端"]
    say(f"    中位：云端 {cmp['云端'].median():.0f} 只/日  本地 {cmp['本地'].median():.0f} 只/日  "
        f"差中位 {cmp['差'].median():+.0f}")
    say(f"    逐日差范围 {cmp['差'].min():+.0f} ~ {cmp['差'].max():+.0f}")

    # 按行业看（更能定位是哪个行业的池不同）
    say(f"\n  按行业汇总候选股数（差 = 本地 − 云端）：")
    ia = cl.groupby("ind_code").size().rename("云端")
    ib = lo.groupby("ind_code").size().rename("本地")
    ii = pd.concat([ia, ib], axis=1).fillna(0).astype(int)
    ii["差"] = ii["本地"] - ii["云端"]
    ii["行业"] = [CODE2NAME.get(c, c) for c in ii.index]
    ii = ii.sort_values("差", key=lambda s: s.abs(), ascending=False)
    say(ii[["行业", "云端", "本地", "差"]].to_string())

    # ==================== 段2 因子逐值 ====================
    m = cl.merge(lo, on=KEY, how="inner", suffixes=("_c", "_l"))
    say("\n" + "=" * 96)
    say(f"段2 因子逐值（可比行 = 两边共有的 调仓日×股票：{len(m):,} 行）")
    say("=" * 96)
    say(f"\n  {'因子':<14}{'可比行':>9}{'单边NaN':>8}{'容差内%':>10}{'中位|Δ|':>12}"
        f"{'中位相对差':>12}{'最大相对差':>12}  判定")
    rows = []
    for f in ALL:
        cc, ll = f"{f}_c", f"{f}_l"
        if cc not in m.columns or ll not in m.columns:
            say(f"  {f:<14}（列缺失：云端 {cc} / 本地 {ll}）")
            continue
        st = diff_stats(m[cc], m[ll])
        if st is None:
            say(f"  {f:<14} 无可比行")
            continue
        verdict = ("**算得对**" if st["ok"] > 0.999
                   else ("部分不同" if st["ok"] > 0.5 else "**算得不对**"))
        say(f"  {f:<14}{st['n']:>9,}{st['one_sided']:>8,}{st['ok']:>10.2%}"
            f"{st['med_abs']:>12.3g}{st['med_rel']:>12.3g}{st['max_rel']:>12.3g}  {verdict}")
        rows.append({"因子": f, **st, "判定": verdict})
        m[[*KEY, cc, ll]].rename(columns={cc: f"{f}_cloud", ll: f"{f}_local"}).to_csv(
            HERE / "factor_value_diff.csv", mode="a",
            header=not (HERE / "factor_value_diff.csv").exists(),
            index=False, encoding="utf-8-sig")

    # ==================== 段3 行业内排名 ====================
    say("\n" + "=" * 96)
    say("段3 行业内复合分 top2 是否一致（两边各用自己的因子值排）")
    say("=" * 96)

    def top2(df: pd.DataFrame, suff: str) -> set:
        d = df[[*KEY, "ind"]].copy()
        for f in FACTORS:
            d[f] = df[f"{f}_{suff}"].values
        d = d.dropna(subset=FACTORS)
        d["_s"] = pd.concat(
            [d.groupby(["date", "ind"])[f].transform(lambda s: s.mul(-1).rank(pct=True))
             for f in FACTORS], axis=1).mean(axis=1)
        d = d.dropna(subset=["_s"]).sort_values(["date", "ind", "_s", "instrument"],
                                               ascending=[True, True, False, True])
        t = d.groupby(["date", "ind"]).head(2)
        return set(zip(t["date"], t["ind"], t["instrument"]))

    # merge 后两侧同名列都被加了后缀：ind_code_c / ind_code_l
    if "ind_code_c" in m.columns and "ind_code_l" in m.columns:
        same_ind = (m["ind_code_c"].astype(str) == m["ind_code_l"].astype(str))
        say(f"  个股行业归属一致率（云端 sw_level_index_code vs 本地 component 表）: "
            f"{same_ind.mean():.2%}")
        if not same_ind.all():
            bad = m.loc[~same_ind, ["date", "instrument", "ind_code_c", "ind_code_l"]]
            say(f"    不一致 {len(bad):,} 行，样例：")
            say(bad.head(6).to_string(index=False))
        m = m[same_ind].copy()
    m["ind"] = m["ind_code_c"].astype(str)
    if all(f"{f}_c" in m.columns and f"{f}_l" in m.columns for f in FACTORS):
        sa, sb = top2(m, "c"), top2(m, "l")
        inter = len(sa & sb)
        say(f"  云端因子选中 {len(sa):,} 个 (调仓日,行业,股) / 本地选中 {len(sb):,} 个 / "
            f"重合 {inter:,}")
        say(f"  一致率（交集/并集）: {inter / max(1, len(sa | sb)):.1%}")
        only_c = sorted(sa - sb)[:8]
        if only_c:
            say(f"  仅云端选中样例: {[(str(d)[:10], i, s) for d, i, s in only_c]}")

    # ==================== 收尾 ====================
    pd.DataFrame(rows).to_csv(HERE / "factor_diff.csv", index=False, encoding="utf-8-sig")
    say(f"\n→ {HERE / 'factor_diff.csv'}（逐列汇总）")
    say(f"→ {HERE / 'factor_value_diff.csv'}（逐值长表）")
    (HERE / "factor_diag_report.txt").write_text("\n".join(_LINES), encoding="utf-8")
    say(f"→ {HERE / 'factor_diag_report.txt'}")


if __name__ == "__main__":
    main()
