"""shared.data_check — 数据校验（只读）：k线 / 对数收益率 / 波动率 的一致性核对。

三类校验，覆盖日 / 周 / 月三个频度：
  1. check_time_alignment  时间对齐：每个品种的 k线、log_return、volatility 的
     count / 起止时间是否自洽（diff 丢首行、volatility warmup、是否更新到最新）。
  2. check_log_return / check_volatility  计算抽查：调用原始计算函数
     (calc_log_return / calc_volatility, persist=False 不写库) 重算，
     与库里同行比对，验证库内值可复现。
  3. check_resample  重采样抽查：从 1d_k_data 按 W-FRI / ME 规则重构 week/mon OHLCV，
     与库里 week/mon_k_data 逐字段比对。

全部只读，不写任何库（计算函数一律 persist=False）。run_data_audit() 汇总出
一份 HTML 报告到 results/。

用法:
    from shared.data_check import run_data_audit
    run_data_audit()                       # 默认全量对齐 + 分类抽查
    run_data_audit(periods=("mon",))       # 只查月度
"""

import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from shared.sector import CATEGORY_MAP
from trend_following.check_trend_valid import (
    RETURNS_DB, calc_log_return, calc_volatility,
)

# ---- 路径（与 data_fetcher / data_viz 解耦，本地定义）----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
K_DATA_DB = PROJECT_ROOT / "data_cache" / "k_data.db"
RESULTS_DIR = PROJECT_ROOT / "results"

# period → 表名
_K_TABLE = {"1d": "1d_k_data", "week": "week_k_data", "mon": "mon_k_data"}
_R_TABLE = {"1d": "1d_return", "week": "week_return", "mon": "mon_return"}

# 重采样规则（须与 data_fetcher._build_tushare_resampled 完全一致）
_RESAMPLE_FREQ = {"week": "W-FRI", "mon": "ME"}
_AGG = {"open": "first", "close": "last", "high": "max", "low": "min",
        "vol": "sum", "oi": "last", "adj_factor": "last"}
_OHLC_FIELDS = ["open", "close", "high", "low", "vol", "oi", "adj_factor"]

# 各频度存库时用的 com（必须与 calc_volatility 计算时一致，否则 calc 抽查会误报不一致）
# 论文 com=60 指 60 交易日；周/月按 bar 长度反比缩放，保持相近时间窗。
_VOL_COM = {"1d": 60, "week": 15, "mon": 3}

# 容差：浮点重算应几乎逐位一致；重采样聚合也来自同一份日线，应几乎相等
_LR_TOL = 1e-8
_VOL_TOL = 1e-8
_RESAMPLE_TOL = 1e-6


# ================================ 辅助 ================================

def _probe_dates(date_values, n=3, quantiles=(0.15, 0.5, 0.85)):
    """从一串日期里按分位取 n 个「早/中/晚」探针日期（YYYY-MM-DD 字符串，去重）。"""
    s = pd.to_datetime(pd.Series(date_values)).dropna().sort_values().reset_index(drop=True)
    if s.empty:
        return []
    qs = list(quantiles)[:n]
    idx = [min(len(s) - 1, max(0, int(round(q * (len(s) - 1))))) for q in qs]
    seen, out = set(), []
    for i in idx:
        d = s.iloc[i].strftime("%Y-%m-%d")
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _kline_counts(period):
    """{symbol: (count, min_date, max_date)}，来自 k_data.<freq> 表。"""
    if not K_DATA_DB.exists():
        return {}
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        rows = conn.execute(
            f'SELECT symbol, COUNT(*), MIN(date), MAX(date) FROM "{_K_TABLE[period]}" '
            f"GROUP BY symbol"
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: (int(r[1]), r[2], r[3]) for r in rows}


def _symbols_with_history(period="1d"):
    """返回 DataFrame[symbol, category, k_count]：在库品种及其日线 k 线数（用于排序抽样）。"""
    kc = _kline_counts(period)
    rows = [{"symbol": s, "category": cat, "k_count": kc.get(s, (0,))[0]}
            for cat, syms in CATEGORY_MAP.items() for s in syms if s in kc]
    return pd.DataFrame(rows).sort_values(["category", "k_count"], ascending=[True, False])


def _pick_per_category(n, in_set):
    """每板块从 in_set 里取历史最长的 n 个品种（CATEGORY_MAP 顺序）；返回 [symbol]。"""
    df = _symbols_with_history("1d")
    df = df[df["symbol"].isin(in_set)]
    picked = []
    for cat in CATEGORY_MAP:                       # 保持板块稳定顺序
        sub = df[df["category"] == cat].head(n)
        picked.extend(sub["symbol"].tolist())
    return picked


# ================================ 校验函数 ================================

def check_time_alignment(period, symbols=None):
    """时间对齐：全品种的 k线 / log_return / volatility 范围与计数是否自洽。

    Returns:
        DataFrame[symbol, category, k_count, k_min, k_max, lr_count, lr_min, lr_max,
                  vol_count, vol_min, vol_max, status, note]
        status ∈ {'ok','warn','fail'}。
    """
    kc = _kline_counts(period)
    if not RETURNS_DB.exists():
        return pd.DataFrame()
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        rows = conn.execute(
            f'SELECT symbol, '
            f'  SUM(CASE WHEN log_return IS NOT NULL THEN 1 ELSE 0 END),'
            f'  SUM(CASE WHEN volatility IS NOT NULL THEN 1 ELSE 0 END),'
            f'  MIN(CASE WHEN log_return IS NOT NULL THEN datetime END),'
            f'  MAX(CASE WHEN log_return IS NOT NULL THEN datetime END),'
            f'  MIN(CASE WHEN volatility IS NOT NULL THEN datetime END),'
            f'  MAX(CASE WHEN volatility IS NOT NULL THEN datetime END) '
            f'FROM "{_R_TABLE[period]}" GROUP BY symbol'
        ).fetchall()
    finally:
        conn.close()
    rmap = {r[0]: r[1:] for r in rows}

    syms = symbols if symbols is not None else sorted(set(kc) | set(rmap))
    out = []
    for s in syms:
        k = kc.get(s)
        r = rmap.get(s)
        k_n, k_min, k_max = (k if k else (0, None, None))
        if r:
            lr_n, vol_n, lr_min, lr_max, vol_min, vol_max = (int(r[0] or 0), int(r[1] or 0),
                                                             r[2], r[3], r[4], r[5])
        else:
            lr_n = vol_n = 0
            lr_min = lr_max = vol_min = vol_max = None

        note, status = [], "ok"
        d = lambda x: (x or "")[:10]                       # 日期取前 10 位比较
        # log_return 应更新到 k 线最新，且 count ≈ k 线 - 1（diff 丢首行）
        if k_n and lr_n:
            if d(lr_max) != d(k_max):
                note.append(f"log_return 未到最新K线({d(lr_max)}≠{d(k_max)})")
                status = "warn"
            miss = (k_n - 1) - lr_n
            if miss > max(1, 0.01 * k_n):
                note.append(f"log_return 比 K线-1 少 {miss}")
                status = "warn"
        elif k_n and not lr_n:
            note.append("有K线无log_return"); status = "fail"
        # volatility：覆盖比例过短 / 未更新到最新
        if lr_n and vol_n:
            if d(vol_max) != d(lr_max):
                note.append(f"volatility 未到最新({d(vol_max)}≠{d(lr_max)})")
                status = "warn"
            if vol_n / lr_n < 0.5:
                note.append(f"volatility 仅覆盖 {vol_n}/{lr_n} ({vol_n/lr_n*100:.0f}%)")
                status = "warn"
        elif lr_n and not vol_n:
            note.append("有log_return无volatility"); status = "fail"

        out.append({
            "symbol": s, "category": (k and next((c for c, sy in CATEGORY_MAP.items() if s in sy), "")) or "",
            "k_count": k_n, "k_min": d(k_min), "k_max": d(k_max),
            "lr_count": lr_n, "lr_min": d(lr_min), "lr_max": d(lr_max),
            "vol_count": vol_n, "vol_min": d(vol_min), "vol_max": d(vol_max),
            "status": status, "note": "；".join(note) if note else "—",
        })
    return pd.DataFrame(out)


def check_log_return(period, symbol, dates=None, n_probe=3):
    """对数收益率计算抽查：calc_log_return(persist=False) 重算 vs 库内值。

    dates 为 None 时自动从该品种库内 log_return 序列按分位取早/中/晚探针。
    Returns: list[dict]，每探针一行（含 stored / recomputed / abs_diff / pass）。
    """
    table = _R_TABLE[period]
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        rows = conn.execute(
            f'SELECT datetime, log_return FROM "{table}" WHERE symbol=? AND log_return IS NOT NULL',
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return [{"symbol": symbol, "period": period, "date": "—", "stored": None,
                 "recomputed": None, "abs_diff": None, "pass": "无数据"}]
    smap = {pd.to_datetime(d).strftime("%Y-%m-%d"): float(v) for d, v in rows}
    if dates is None:
        dates = _probe_dates([d for d, _ in rows], n_probe)

    rec = calc_log_return(symbol, period=period, source="local", persist=False)
    rmap = {}
    if isinstance(rec, pd.DataFrame) and not rec.empty:
        rec = rec.copy()
        rec["_d"] = pd.to_datetime(rec["datetime"]).dt.strftime("%Y-%m-%d")
        rmap = dict(zip(rec["_d"], rec["log_return"].astype(float)))

    out = []
    for d in dates:
        sv, rv = smap.get(d), rmap.get(d)
        if sv is None or rv is None:
            out.append({"symbol": symbol, "period": period, "date": d, "stored": sv,
                        "recomputed": rv, "abs_diff": None, "pass": "缺失"})
            continue
        diff = abs(sv - rv)
        out.append({"symbol": symbol, "period": period, "date": d, "stored": sv,
                    "recomputed": rv, "abs_diff": diff,
                    "pass": "通过" if diff < _LR_TOL else "不一致"})
    return out


def check_volatility(period, symbol, dates=None, n_probe=3, com=None):
    """波动率计算抽查：calc_volatility(persist=False) 重算 vs 库内值。

    com 默认取 _VOL_COM[period]（须与存库时一致）；dates 为 None 时自动从该品种
    库内 volatility 非空序列取探针（只抽有值的地方）。
    Returns: list[dict]。
    """
    table = _R_TABLE[period]
    if com is None:
        com = _VOL_COM.get(period, 60)
    conn = sqlite3.connect(str(RETURNS_DB))
    try:
        rows = conn.execute(
            f'SELECT datetime, volatility FROM "{table}" WHERE symbol=? AND volatility IS NOT NULL',
            (symbol,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return [{"symbol": symbol, "period": period, "date": "—", "stored": None,
                 "recomputed": None, "abs_diff": None, "pass": "库里无volatility"}]
    smap = {pd.to_datetime(d).strftime("%Y-%m-%d"): float(v) for d, v in rows}
    if dates is None:
        dates = _probe_dates([d for d, _ in rows], n_probe)

    rec = calc_volatility(symbol, period=period, com=com, persist=False)
    rmap = {}
    if isinstance(rec, pd.DataFrame) and not rec.empty:
        rec = rec.copy()
        rec["_d"] = pd.to_datetime(rec["datetime"]).dt.strftime("%Y-%m-%d")
        rmap = dict(zip(rec["_d"], rec["volatility"].astype(float)))

    out = []
    for d in dates:
        sv, rv = smap.get(d), rmap.get(d)
        if sv is None or rv is None:
            out.append({"symbol": symbol, "period": period, "date": d, "stored": sv,
                        "recomputed": rv, "abs_diff": None, "pass": "缺失"})
            continue
        diff = abs(sv - rv)
        out.append({"symbol": symbol, "period": period, "date": d, "stored": sv,
                    "recomputed": rv, "abs_diff": diff,
                    "pass": "通过" if diff < _VOL_TOL else "不一致"})
    return out


def check_resample(symbol, period, dates=None, n_probe=3):
    """重采样抽查（仅 week/mon）：从 1d_k_data 按 W-FRI/ME 重构 OHLCV，逐字段对比库内。

    dates 为 None 时自动从库内 week/mon_k_data 取探针。
    Returns: list[dict]，每 (探针日期, 字段) 一行。
    """
    if period not in _RESAMPLE_FREQ:
        raise ValueError(f"check_resample 仅支持 week/mon，收到 {period!r}")
    freq = _RESAMPLE_FREQ[period]
    conn = sqlite3.connect(str(K_DATA_DB))
    try:
        daily = pd.read_sql(
            f'SELECT date,open,close,high,low,vol,oi,adj_factor FROM "1d_k_data" '
            f"WHERE symbol=? ORDER BY date", conn, params=(symbol,))
        tgt = pd.read_sql(
            f'SELECT date,open,close,high,low,vol,oi,adj_factor FROM "{_K_TABLE[period]}" '
            f"WHERE symbol=?", conn, params=(symbol,))
    finally:
        conn.close()
    if daily.empty:
        return [{"symbol": symbol, "period": period, "date": "—", "field": "—",
                 "stored": None, "reconstructed": None, "abs_diff": None, "pass": "无日线"}]
    daily["date"] = pd.to_datetime(daily["date"])
    recon = (daily.set_index("date").resample(freq).agg(_AGG)
             .dropna(subset=["open"]).reset_index())
    recon["date"] = recon["date"].dt.strftime("%Y-%m-%d")
    recon = recon.set_index("date")
    tgt = tgt.set_index("date") if not tgt.empty else tgt

    if dates is None:
        dates = _probe_dates(tgt.index.tolist() if not tgt.empty else [], n_probe)

    out = []
    for d in dates:
        if d not in recon.index or (tgt.empty or d not in tgt.index):
            out.append({"symbol": symbol, "period": period, "date": d, "field": "(整行)",
                        "stored": None, "reconstructed": None, "abs_diff": None,
                        "pass": "缺失"})
            continue
        for field in _OHLC_FIELDS:
            rv = recon.loc[d, field]
            sv = tgt.loc[d, field]
            rv = None if pd.isna(rv) else float(rv)
            sv = None if pd.isna(sv) else float(sv)
            if rv is None or sv is None:
                out.append({"symbol": symbol, "period": period, "date": d, "field": field,
                            "stored": sv, "reconstructed": rv, "abs_diff": None, "pass": "缺失"})
                continue
            diff = abs(sv - rv)
            out.append({"symbol": symbol, "period": period, "date": d, "field": field,
                        "stored": sv, "reconstructed": rv, "abs_diff": diff,
                        "pass": "通过" if diff < _RESAMPLE_TOL else "不一致"})
    return out


# ================================ HTML 报告 ================================

_BG = {"ok": "#e6ffe6", "通过": "#e6ffe6", "warn": "#fff7e6",
       "fail": "#ffe6e6", "不一致": "#ffe6e6", "缺失": "#fff0b3",
       "无数据": "#eeeeee", "库里无volatility": "#eeeeee", "无日线": "#eeeeee"}


def _table_html(table_id, headers, rows, status_col=None):
    """渲染一个可点击排序的 HTML 表。status_col: 每行状态字符串，决定底色（None 不上色）。"""
    thead = "".join(f'<th onclick="sortTable(\'{table_id}\',{i})" title="点击排序">{h}</th>'
                    for i, h in enumerate(headers))
    body = ""
    for ri, row in enumerate(rows):
        bg = _BG.get(status_col[ri], "") if status_col else ""
        style = f' style="background:{bg}"' if bg else ""
        tds = "".join(f'<td data-val="{str(c)}">{c}</td>' for c in row)
        body += f'<tr{style}>{tds}</tr>\n'
    return f'''<table id="{table_id}">
<thead><tr>{thead}</tr></thead>
<tbody>{body}</tbody>
</table>'''


_SORT_JS = """
let _last = {};
function sortTable(id, col) {
  const tbl = document.getElementById(id);
  const rows = Array.from(tbl.tBodies[0].rows);
  const key = id + ':' + col;
  const asc = (_last[key] === undefined) ? true : !_last[key];
  _last[key] = asc;
  rows.sort((a, b) => {
    const x = a.cells[col].getAttribute("data-val");
    const y = b.cells[col].getAttribute("data-val");
    const xn = parseFloat(x), yn = parseFloat(y);
    let cmp = (!isNaN(xn) && !isNaN(yn)) ? (xn - yn) : String(x).localeCompare(String(y), "zh");
    return asc ? cmp : -cmp;
  });
  rows.forEach(r => tbl.tBodies[0].appendChild(r));
}
"""


def _fmt(v, decimals=6):
    if v is None or (isinstance(v, float) and (np.isnan(v))):
        return ""
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        return f"{v:.{decimals}f}"
    return str(v)


def run_data_audit(periods=("1d", "week", "mon"), n_calc=2, n_resample=1,
                   do_alignment=True, do_calc=True, do_resample=True,
                   out_name="data_audit_report.html", run_time=None):
    """汇总校验，生成 HTML 报告。

    Args:
        periods:        参与校验的频度（默认日/周/月）。
        n_calc:         每板块计算抽查的品种数（取历史最长者）。
        n_resample:     每板块重采样抽查的品种数。
        do_alignment:   是否做 ① k线/log_return/volatility 时间对齐（全品种）。
        do_calc:        是否做 ②③ log_return/volatility 计算抽查（重算 vs 库内）。
        do_resample:    是否做 ④ 日线→周/月 重采样抽查。
        out_name:       输出 HTML 文件名（写到 results/）。
        run_time:       报告显示的运行时间字符串；None 则标 '—'（模块内不取系统时间）。

    Returns:
        生成的 HTML 文件路径（Path）。
    """
    periods = tuple(periods)
    sections = []
    summary = {"align_ok": 0, "align_warn": 0, "align_fail": 0,
               "lr_pass": 0, "lr_fail": 0,
               "vol_pass": 0, "vol_fail": 0,
               "res_pass": 0, "res_fail": 0}

    # ---- ① 时间对齐（全品种）----
    for p in periods:
        if not do_alignment:
            break
        df = check_time_alignment(p)
        if df.empty:
            continue
        counts = df["status"].value_counts()
        summary["align_ok"] += int(counts.get("ok", 0))
        summary["align_warn"] += int(counts.get("warn", 0))
        summary["align_fail"] += int(counts.get("fail", 0))
        headers = ["symbol", "板块", "K线数", "K线起", "K线止",
                   "lr数", "lr起", "lr止", "vol数", "vol起", "vol止", "状态", "备注"]
        rows = [[r["symbol"], r["category"], r["k_count"], r["k_min"], r["k_max"],
                 r["lr_count"], r["lr_min"], r["lr_max"], r["vol_count"], r["vol_min"],
                 r["vol_max"], r["status"], r["note"]] for _, r in df.iterrows()]
        sections.append(f"<h3>① 时间对齐 — {p}（{len(df)} 品种："
                        f"✓{counts.get('ok',0)} / ⚠{counts.get('warn',0)} / ✗{counts.get('fail',0)}）</h3>")
        sections.append(_table_html(f"align_{p}", headers, rows,
                                    status_col=df["status"].tolist()))

    # 抽样品种（基于日线在库）；各开关关闭时跳过相应抽样
    in_db = set(_kline_counts("1d").keys())
    calc_symbols = _pick_per_category(n_calc, in_db) if do_calc else []
    resample_symbols = _pick_per_category(n_resample, in_db) if do_resample else []

    # ---- ② 对数收益率计算抽查 ----
    lr_rows, lr_status = [], []
    for p in periods:
        for s in calc_symbols:
            for item in check_log_return(p, s):
                lr_rows.append([item["period"], item["symbol"], item["date"],
                                _fmt(item["stored"], 8), _fmt(item["recomputed"], 8),
                                _fmt(item["abs_diff"], 2) if item["abs_diff"] is not None
                                else ("" if item["abs_diff"] is None else _fmt(item["abs_diff"], 2)),
                                item["pass"]])
                lr_status.append(item["pass"])
                if item["pass"] == "通过":
                    summary["lr_pass"] += 1
                elif item["pass"] == "不一致":
                    summary["lr_fail"] += 1
    if lr_rows:
        sections.append(f"<h3>② 对数收益率计算抽查（{len(calc_symbols)} 品种 × "
                        f"{len(periods)} 频度，重算 vs 库内，tol=1e-8）</h3>")
        sections.append(_table_html("lr", ["频度", "symbol", "日期", "库内", "重算", "abs差", "结果"],
                                    lr_rows, lr_status))

    # ---- ③ 波动率计算抽查 ----
    vol_rows, vol_status = [], []
    for p in periods:
        for s in calc_symbols:
            for item in check_volatility(p, s):
                vol_rows.append([item["period"], item["symbol"], item["date"],
                                 _fmt(item["stored"], 8), _fmt(item["recomputed"], 8),
                                 _fmt(item["abs_diff"], 2) if item["abs_diff"] is not None else "",
                                 item["pass"]])
                vol_status.append(item["pass"])
                if item["pass"] == "通过":
                    summary["vol_pass"] += 1
                elif item["pass"] == "不一致":
                    summary["vol_fail"] += 1
    if vol_rows:
        sections.append(f"<h3>③ 波动率计算抽查（{len(calc_symbols)} 品种 × "
                        f"{len(periods)} 频度，重算 vs 库内，tol=1e-8）</h3>")
        sections.append(_table_html("vol", ["频度", "symbol", "日期", "库内", "重算", "abs差", "结果"],
                                    vol_rows, vol_status))

    # ---- ④ 重采样抽查（仅 week/mon）----
    res_rows, res_status = [], []
    for p in periods:
        if p not in _RESAMPLE_FREQ:
            continue
        for s in resample_symbols:
            for item in check_resample(s, p):
                res_rows.append([item["period"], item["symbol"], item["date"], item["field"],
                                 _fmt(item["stored"], 2), _fmt(item["reconstructed"], 2),
                                 _fmt(item["abs_diff"], 2) if item["abs_diff"] is not None else "",
                                 item["pass"]])
                res_status.append(item["pass"])
                if item["pass"] == "通过":
                    summary["res_pass"] += 1
                elif item["pass"] == "不一致":
                    summary["res_fail"] += 1
    if res_rows:
        sections.append(f"<h3>④ 重采样抽查（{len(resample_symbols)} 品种，日线→周/月，tol=1e-6）</h3>")
        sections.append(_table_html("res",
                                    ["频度", "symbol", "日期", "字段", "库内", "重构", "abs差", "结果"],
                                    res_rows, res_status))

    # ---- 汇总 ----
    ov = [
        ["K线库", str(K_DATA_DB)], ["收益率库", str(RETURNS_DB)],
        ["频度", " / ".join(periods)],
        ["计算抽查品种/板块", f"{len(calc_symbols)} / {len(CATEGORY_MAP)}（每板块 {n_calc}）"],
        ["重采样抽查品种/板块", f"{len(resample_symbols)} / {len(CATEGORY_MAP)}（每板块 {n_resample}）"],
        ["① 时间对齐", f"✓ {summary['align_ok']}  ⚠ {summary['align_warn']}  ✗ {summary['align_fail']}"],
        ["② 对数收益率抽查", f"✓ {summary['lr_pass']}  ✗ {summary['lr_fail']}（缺的不计）"],
        ["③ 波动率抽查", f"✓ {summary['vol_pass']}  ✗ {summary['vol_fail']}（缺的不计）"],
        ["④ 重采样抽查", f"✓ {summary['res_pass']}  ✗ {summary['res_fail']}（缺的不计）"],
        ["运行时间", run_time or "—"],
    ]

    html = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>数据校验报告</title>
<style>
  body {{ font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 20px; color: #222; }}
  h2 {{ color: #333; }} h3 {{ color: #1a5276; margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; margin-bottom: 8px; }}
  th, td {{ border: 1px solid #ccc; padding: 4px 7px; text-align: center; white-space: nowrap; }}
  th {{ background: #afeeee; cursor: pointer; user-select: none; position: sticky; top: 0; }}
  th:hover {{ background: #8deeee; }}
  tr:nth-child(even) {{ background: #f7fafa; }}
  .ov td {{ text-align: left; }} .ov td:first-child {{ width: 200px; font-weight: bold; }}
  .hint {{ color: #888; font-size: 12px; }}
</style></head>
<body>
<h2>数据校验报告</h2>
<p class="hint">全部只读，不写库（计算函数一律 persist=False）。点击表头排序。底色：绿=通过，黄=缺失/告警，红=不一致/失败。</p>
<h3>概览</h3>
<table class="ov"><tbody>
{''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in ov)}
</tbody></table>
{''.join(sections)}
<script>{_SORT_JS}</script>
</body></html>"""

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / out_name
    out.write_text(html, encoding="utf-8")
    print(f"[data_check] 已输出: {out}")
    print(f"[data_check] 汇总: 对齐 ✓{summary['align_ok']}/⚠{summary['align_warn']}/✗{summary['align_fail']} | "
          f"收益率 ✓{summary['lr_pass']}/✗{summary['lr_fail']} | "
          f"波动率 ✓{summary['vol_pass']}/✗{summary['vol_fail']} | "
          f"重采样 ✓{summary['res_pass']}/✗{summary['res_fail']}")
    return out


if __name__ == "__main__":
    run_data_audit()
