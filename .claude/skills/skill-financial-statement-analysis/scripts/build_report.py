"""build_report.py — 从解析面板生成六维度财务分析报告（单文件 HTML，本地 plotly）

用法：
  python build_report.py --panel <parse 输出目录> --out report.html [--profile bank]

六维度（详见 references/framework.md）：
  1 成长性    2 盈利质量    3 偿债与资本    4 效率与资产质量
  5 勾稽与信号（fraud-index 三桶纪律）    6 指标全景

口径约定：
  income/cashflow = YTD 累计 → 同比用同财年同期，单季值用年内差分
  balance/ability = 时点/当期比率，直接使用
  银行 profile：OCF/净利背离信号弱化（银行经营现金流由存贷款变动主导，天然剧烈）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── 取数 ──────────────────────────────────────────────────────────────
def get(df: pd.DataFrame, *cands):
    """精确匹配 → 包含匹配，返回一行 Series（无命中返回 None）"""
    for c in cands:
        if c in df.index:
            return df.loc[c]
    for c in cands:
        hit = [i for i in df.index if c in i]
        if hit:
            return df.loc[hit[0]]
    return None


def pick(panels: dict, table: str, *cands):
    return get(panels[table], *cands) if table in panels else None


# ── 序列变换 ──────────────────────────────────────────────────────────
def yoy_ytd(s: pd.Series) -> pd.Series:
    """YTD 口径同比：'2026-06' 对 '2025-06'"""
    out = pd.Series(np.nan, index=s.index)
    for p in s.index:
        y, m = p.split("-")
        prev = f"{int(y)-1}-{m}"
        if prev in s.index and s.get(prev) and s.get(prev) != 0:
            out[p] = s[p] / s[prev] - 1
    return out


def to_single_quarter(s: pd.Series) -> pd.Series:
    """YTD 累计 → 单季：Q1 直取，Q2/Q3/Q4 = 当期累计 − 上一累计"""
    out = pd.Series(np.nan, index=s.index)
    prev_m = {"06": "03", "09": "06", "12": "09"}
    for p in s.index:
        y, m = p.split("-")
        if m == "03":
            out[p] = s[p]
        else:
            q = f"{y}-{prev_m[m]}"
            if q in s.index and s.get(q) is not None and not pd.isna(s.get(q)):
                out[p] = s[p] - s[q]
    return out


def fmt(v, d=2, pct=False):
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return "—"
    if pct:
        return f"{v*100:+.1f}%" if abs(v) < 10 else f"{v:+.0f}%"
    return f"{v:,.{d}f}"


def latest_valid(s: pd.Series, n=1):
    """倒数第 n 个非 NaN 值 → (value, period)。注意与 items() 的 (period, value) 相反"""
    ok = [(v, p) for p, v in s.items() if v is not None and not pd.isna(v)]
    return ok[-n] if len(ok) >= n else (None, None)


# ── 信号扫描（维度5）─────────────────────────────────────────────────
def scan_jumps(sq: pd.DataFrame, min_abs=1.0, thr=0.6, top=6):
    """单季序列环比突增：|Δ|>thr 且前后两期 |值|>min_abs。返回 [(指标, 期, 前值, 现值, 变化%)]"""
    hits = []
    for name in sq.index:
        s = sq.loc[name]
        for i in range(1, len(s)):
            a, b = s.iloc[i-1], s.iloc[i]
            if pd.isna(a) or pd.isna(b) or abs(a) < min_abs or abs(b) < min_abs:
                continue
            if abs(b - a) / abs(a) > thr:
                hits.append((name, s.index[i], a, b, (b - a) / abs(a)))
    hits.sort(key=lambda x: -abs(x[4]))
    return hits[:top]


# ── plotly 装配 ───────────────────────────────────────────────────────
DARK = dict(paper_bgcolor="#16181d", plot_bgcolor="#1b1e24", font=dict(color="#d8dce3", size=11),
            margin=dict(l=52, r=20, t=36, b=30))
GRID = dict(gridcolor="#26292f", zeroline=False)
C_MAIN, C_ACC, C_POS, C_NEG, C_WARN = "#4a90d9", "#e8c35a", "#ef232a", "#14b143", "#e8862e"


def fig_lines(div_id, traces, title, y_title="", shapes=None, y2=None, height=300):
    """traces=[(x, y, name, color, dash, width)]；y2=[...] 同结构挂右轴"""
    import plotly.io as pio
    cfg = dict(displayModeBar=False, responsive=True)
    tl = []
    for x, y, name, color, dash, w in traces:
        tl.append(dict(type="scatter", mode="lines", x=x, y=y, name=name,
                       line=dict(color=color, width=w, dash=dash)))
    if y2:
        for x, y, name, color, dash, w in y2:
            tl.append(dict(type="scatter", mode="lines", x=x, y=y, name=name, yaxis="y2",
                           line=dict(color=color, width=w, dash=dash)))
    layout = dict(**DARK, height=height, title=dict(text=title, font=dict(size=13)),
                  xaxis=dict(**GRID, type="category", tickangle=-45,
                             tickvals=list(traces[0][0])[::4] if traces[0][0] is not None else None),
                  yaxis=dict(**GRID, title=y_title), showlegend=len(tl) > 1,
                  legend=dict(orientation="h", y=1.15, x=0),
                  shapes=shapes or [])
    if y2:
        layout["yaxis2"] = dict(overlaying="y", side="right", **GRID, title="")
    fig = dict(data=tl, layout=layout)
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config=cfg, div_id=div_id)


def fig_bars(div_id, x, y, colors, title, y_title="", height=300):
    import plotly.io as pio
    fig = dict(data=[dict(type="bar", x=x, y=y, marker=dict(color=colors),
                          customdata=[[f"{v:+.1f}%"] for v in y],
                          hovertemplate="%{x}<br>%{y:.2f}<extra></extra>")],
               layout=dict(**DARK, height=height, title=dict(text=title, font=dict(size=13)),
                           xaxis=dict(**GRID, type="category", tickangle=-45,
                                      tickvals=list(x)[::4]),
                           yaxis=dict(**GRID, title=y_title), showlegend=False))
    return pio.to_html(fig, include_plotlyjs=False, full_html=False,
                       config=dict(displayModeBar=False, responsive=True), div_id=div_id)


def hline(y, color=C_WARN):
    return dict(type="line", y0=y, y1=y, x0=0, x1=1, xref="paper", yref="y",
                line=dict(color=color, width=1, dash="dot"))


# ── 主流程 ────────────────────────────────────────────────────────────
def build(panel_dir: Path, out_html: Path, profile: str):
    panels, meta = {}, json.loads((panel_dir / "meta.json").read_text(encoding="utf-8"))
    for t in ["income", "balance", "cashflow", "ability"]:
        p = panel_dir / f"panel_{t}.parquet"
        if p.exists():
            panels[t] = pd.read_parquet(p)
    inc, cf, ab = panels.get("income"), panels.get("cashflow"), panels.get("ability")
    bal = panels.get("balance")
    periods = inc.columns.tolist()
    company = meta.get("company", "?")
    code = meta.get("code", "?")
    last_p = periods[-1]

    # ★ 单位与报告频次按**源表实际口径**显示，不写死。东财 A 股大盘股常见「亿元/季报」，
    #   但港股与中小公司不同——五一视界(06651.HK) 实测「百万/半年报」，
    #   若写死"亿元"会把 1.7 亿营收写成 169.98 亿（差 100 倍），属宁缺毋错铁律的反面。
    UNIT = meta.get("unit") or "—"
    months = sorted({p.split("-")[1] for p in periods})
    FREQ_NOTE = {"06,12": "半年报", "03,06,09,12": "季报"}.get(",".join(months), "报告期")
    PNAME = {"bank": "银行", "software": "软件", "general": "通用"}.get(profile, "通用")

    # ── 维度1 成长性 ──
    rev = pick(panels, "income", "一、营业收入", "营业总收入", "营业收入")
    np_ = pick(panels, "income", "五、净利润", "净利润")
    np_parent = pick(panels, "income", "归属于母公司普通股股东的净利润")
    rev_yoy, np_yoy = yoy_ytd(rev), yoy_ytd(np_parent if np_parent is not None else np_)
    rev_q = to_single_quarter(rev)
    r0, r0p = latest_valid(rev), None
    ry, ryp = latest_valid(rev_yoy)
    ny, nyp = latest_valid(np_yoy)
    rev_q_now, _ = latest_valid(rev_q)

    # ── 维度2 盈利质量 ──
    roe = pick(panels, "ability", "归属于母公司普通股股东的加权ROE", "净资产收益率(ROE)")
    npm = pick(panels, "ability", "净利润率")
    if npm is None:
        npm = pick(panels, "income", "净利润率")
    gm = pick(panels, "ability", "毛利率(GM)", "销售毛利率", "毛利率")
    if gm is None:
        # 港股「财务指标表」不含毛利率（只有 ROE/每股/周转/负债率），它在**利润表**里，
        # 且值已是百分数（如 64.95 = 64.95%），下游不得再 ×100。
        gm = pick(panels, "income", "毛利率(GM)", "销售毛利率", "毛利率")
    ocf = pick(panels, "cashflow", "经营活动产生的现金流量净额")
    np_series = np_parent if np_parent is not None else np_
    ocf_np = ocf / np_series.replace(0, np.nan)          # 同为 YTD 口径
    on, onp = latest_valid(ocf_np)

    # ── 维度3 偿债与资本 ──
    cap1 = pick(panels, "ability", "核心一级资本充足率")          # bank
    capa = pick(panels, "ability", "资本充足率")                    # bank
    lev = pick(panels, "ability", "杠杆倍数")
    ta = pick(panels, "balance", "一、资产合计", "资产总计")
    tl = pick(panels, "balance", "负债合计", "负债总计", "总负债")
    # 资产负债率：综合表优先，缺则负债/资产自算（时点口径）
    dar = pick(panels, "ability", "资产负债率")
    if dar is None and tl is not None and ta is not None:
        dar = tl / ta.replace(0, np.nan)

    # ── 维度4 效率与资产质量 ──
    nim = pick(panels, "ability", "净息差")                          # bank
    cir = pick(panels, "income", "收入成本比", "成本收入比")         # bank
    npl = pick(panels, "ability", "不良率")                          # bank
    cov = pick(panels, "ability", "不良贷款拨备覆盖率")              # bank
    inv_turn = pick(panels, "ability", "存货周转率")                 # general
    ast_turn = pick(panels, "ability", "资产周转率")                 # general
    # ★ 东财「资产周转率」是**百分数形式**：营收 ÷ 平均资产 × 100。
    #   实测五一视界 2023-12 = 256.302/((504.342+374.688)/2)×100 = 58.31 ✓
    #                 2026-06 = 123.672/((1321.714+1303.45)/2)×100 = 9.42 ✓
    #   → 与常规"倍数"口径差 100 倍（9.42 实为 0.094 次），统一 ÷100 还原，避免误读。
    if ast_turn is not None:
        ast_turn = ast_turn / 100
    roic = pick(panels, "ability", "资本回报率(ROIC)", "资本回报率")  # general
    contract_liab = pick(panels, "balance", "合同负债", "预收款项")   # 地产：销售前瞻
    # ── software：费用结构与现金（软件/科技公司重点，非银通用）──
    rd_exp = pick(panels, "income", "研发费用")
    sf_exp = pick(panels, "income", "销售费用")
    mf_exp = pick(panels, "income", "管理费用")
    cash_ = pick(panels, "balance", "货币资金")
    cl_ = pick(panels, "balance", "流动负债合计")
    rd_ratio = (rd_exp / rev.replace(0, np.nan)
                if rd_exp is not None and rev is not None else None)
    exp_ratio = (((rd_exp + sf_exp + mf_exp) / rev.replace(0, np.nan))
                 if all(x is not None for x in (rd_exp, sf_exp, mf_exp)) and rev is not None
                 else None)
    cash_cl = (cash_ / cl_.replace(0, np.nan)
               if cash_ is not None and cl_ is not None else None)

    # ── 维度5 勾稽与信号 ──
    inc_q = inc.select_dtypes("float").apply(to_single_quarter, axis=1)
    jumps = scan_jumps(inc_q)
    signals_weak = [f"{n}：{p} 单季 {a:.0f}→{b:.0f}（{c:+.0%}）" for n, p, a, b, c in jumps]

    # ── HTML ──
    CSS = """
    *{box-sizing:border-box;margin:0;padding:0}
    body{font:14px/1.7 system-ui,'Microsoft YaHei',sans-serif;background:#16181d;color:#d8dce3;padding:24px 32px 60px;max-width:1080px;margin:0 auto}
    h1{font-size:20px;margin-bottom:2px} .sub{color:#7a8494;font-size:12px;margin-bottom:20px}
    h2{font-size:16px;color:#e8c35a;margin:28px 0 8px;border-left:3px solid #e8c35a;padding-left:10px}
    p.an{color:#b8c0cc;margin:6px 0} p.an b{color:#d8dce3} .pos{color:#ef232a}.neg{color:#14b143}.warn{color:#e8862e}
    .grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
    table{border-collapse:collapse;font-size:12px;margin:8px 0;width:100%}
    th,td{padding:5px 9px;border-bottom:1px solid #23262e;text-align:right;white-space:nowrap}
    th{color:#9aa3b2;font-weight:500} td.l,th.l{text-align:left}
    .bucket{background:#1b1e24;border:1px solid #2a2e38;border-radius:6px;padding:10px 14px;margin:8px 0;font-size:12.5px}
    .bucket b{color:#e8c35a} .bucket ul{margin:4px 0 0 18px} .bucket li{margin:2px 0}
    .tag{display:inline-block;padding:0 7px;border-radius:3px;font-size:11px;margin-right:6px}
    .t-red{background:#3a2020;color:#ef7a7a}.t-yel{background:#3a3320;color:#e8c35a}.t-gray{background:#2a2e38;color:#9aa3b2}
    """

    def para(t):
        return f"<p class='an'>{t}</p>"

    H = [f"<!DOCTYPE html><html lang=zh><head><meta charset='utf-8'><title>{company} 财务分析</title>",
         # ★ plotly 库必须放在 <head>：图的内联 newPlot 脚本在正文流中先于文档末尾执行，
         #   库放最后会 Plotly is not defined 全图空白。且 src 用**相对文件名**——
         #   绝对盘符路径('C:/...')会被浏览器当无效 scheme 解析，双击打开同样全空
         "<script src='plotly.min.js'></script>",
         f"<style>{CSS}</style></head><body>",
         f"<h1>{company}（{code}）财务分析报告</h1>",
         f"<div class='sub'>数据：东方财富四表导出 · {periods[0]} ~ {last_p} 共 {len(periods)} 期（{FREQ_NOTE}）· "
         f"profile = {profile} · 单位：{UNIT}（比率/每股除外，按源表口径原样显示） · 生成于 build_report.py</div>"]

    # ─ 1 成长性 ─
    H.append("<h2>一、成长性</h2>")
    H.append(para(
        f"<b>{ryp}</b> 营业收入 <b>{fmt(rev[ryp])}</b> {UNIT}（YTD），同比 "
        f"<b class='{'pos' if (ry or 0)>0 else 'neg'}'>{fmt(ry, pct=True)}</b>；"
        f"归母净利润同比 <b class='{'pos' if (ny or 0)>0 else 'neg'}'>{fmt(ny, pct=True)}</b>。"
        + (f"最近单季营收 <b>{fmt(rev_q_now)}</b> {UNIT}。" if rev_q_now is not None else "")
        + "收入与利润增速的裂口反映费用/减值端的弹性。"))
    x = rev_yoy.dropna().index.tolist()
    H.append("<div class='grid2'>")
    H.append(fig_lines("g1", [(x, rev_yoy.dropna().tolist(), "营收YoY", C_MAIN, None, 2),
                              (x, np_yoy.dropna().tolist(), "归母净利YoY", C_ACC, None, 2)],
                       "营收 / 归母净利润 同比（YTD 口径）", y_title="同比", height=300))
    rq = rev_q.dropna()
    H.append(fig_bars("g2", rq.index.tolist(), rq.tolist(),
                      [C_POS if v >= 0 else C_NEG for v in rq.tolist()],
                      f"营业收入 单季值（YTD 差分，{UNIT}）", y_title=UNIT, height=300))
    H.append("</div>")

    # ─ 2 盈利质量 ─
    H.append("<h2>二、盈利质量</h2>")
    roe_now, roe_p = latest_valid(roe) if roe is not None else (None, None)
    # 上年同期（同位比较，YTD 口径下 2026-06 对 2025-06）——不是"上一期"
    roe_prev = None
    if roe is not None and roe_p:
        y, m = roe_p.split("-")
        pk = f"{int(y)-1}-{m}"
        if pk in roe.index and roe.get(pk) is not None and not pd.isna(roe.get(pk)):
            roe_prev = roe[pk]
    H.append(para(
        f"加权 ROE 最新 <b>{fmt(roe_now)}%</b>（{roe_p}）"
        + (f"，上年同期 {fmt(roe_prev)}%（同位比较，YTD 未年化）" if roe_prev else "")
        + f"；净利率 <b>{fmt(npm[last_p]) if npm is not None else '—'}%</b>"
        + (f"，毛利率 <b>{fmt(latest_valid(gm)[0])}%</b>（{latest_valid(gm)[1]}）。" if gm is not None else "。")
        + f"经营现金流净额 / 净利润 最新为 <b class='{'warn' if on is not None and abs(on) > 2 else ''}'>{fmt(on)}</b>"
        + (f"（{onp}）——银行该比值天然剧烈（经营现金流由存贷款变动主导），仅作跟踪不作警示。"
           if profile == "bank" else
           f"（{onp}）——亏损期净利为负，该比值符号易误导，重点看经营现金流净额的**绝对规模与趋势**"
           "（现金消耗速度），而非比值本身。"
           if profile == "software" else
           f"（{onp}）——房企经营现金流受拿地/销售节奏主导波动大，与净利持续背离需查拿地支出。")))
    H.append("<div class='grid2'>")
    if roe is not None:
        rr = roe.dropna()
        H.append(fig_lines("g3", [(rr.index.tolist(), rr.tolist(), "加权ROE(%)", C_MAIN, None, 2)],
                           "加权 ROE（%）", height=300))
    if ocf is not None and np_series is not None:
        oc, nps = ocf.dropna(), np_series.dropna()
        H.append(fig_lines("g4", [(oc.index.tolist(), oc.tolist(), "经营现金流净额", C_MAIN, None, 2),
                                  (nps.index.tolist(), nps.tolist(), "净利润", C_ACC, None, 2)],
                           f"经营现金流 vs 净利润（{UNIT}，YTD）", height=300))
    H.append("</div>")

    # ─ 3 偿债与资本 ─
    H.append(f"<h2>三、偿债与资本（{PNAME}口径）</h2>")
    if profile == "bank":
        c1n, c1p = latest_valid(cap1) if cap1 is not None else (None, None)
        H.append(para(
            f"核心一级资本充足率 <b>{fmt(c1n)}%</b>（{c1p}，监管参考线 7.5% 含储备）；"
            f"资本充足率 <b>{fmt(latest_valid(capa)[0] if capa is not None else None)}%</b>（参考线 10.5%）；"
            f"杠杆倍数 <b>{fmt(latest_valid(lev)[0] if lev is not None else None, 1)}</b>；"
            f"总资产 <b>{fmt(ta[last_p] if ta is not None else None, 0)}</b> {UNIT}。"
            "充足率趋势下行 = 资产扩张快于资本补充（内生或外源融资压力）。"))
    elif profile == "software":
        dn, dp = latest_valid(dar) if dar is not None else (None, None)
        disp = (dn * 100) if (dn is not None and abs(dn) < 1) else dn
        cs, csp = latest_valid(cash_) if cash_ is not None else (None, None)
        ccr, ccrp = latest_valid(cash_cl) if cash_cl is not None else (None, None)
        H.append(para(
            f"资产负债率 <b>{fmt(disp)}%</b>（{dp}）——软件公司轻资产、有息负债通常低，"
            "该比率主要反映预收/应付与历史融资结构；<b>&gt;100% 即资不抵债</b>，"
            "通常出现在上市前可转债/优先股累积期，靠 IPO 或大额融资解除。"
            f"货币资金 <b>{fmt(cs)}</b>（{csp}）"
            + (f"，货币资金 / 流动负债 <b>{fmt(ccr)}</b>（{ccrp}）"
               "——低于 1 意味着账面现金覆盖不了短期负债，需靠融资或经营现金流补" if ccr is not None else "")
            + "。亏损公司的真正命门是「钱能烧多久」：把经营现金流净额的**绝对规模**"
            "与货币资金余额对照，而不是看比率。"))
    else:
        dn, dp = latest_valid(dar) if dar is not None else (None, None)
        cl_now, cl_p = (latest_valid(contract_liab) if contract_liab is not None else (None, None))
        disp = (dn * 100) if (dn is not None and abs(dn) < 1) else dn   # 统一百分数
        H.append(para(
            f"资产负债率 <b>{fmt(disp)}%</b>（{dp}）——房企 75~80% 属常态（预收/合同负债计入负债），"
            "趋势骤升且伴随合同负债收缩才是真风险信号；"
            f"总资产 <b>{fmt(ta[last_p] if ta is not None else None, 0)}</b> {UNIT}"
            + (f"，合同负债 <b>{fmt(cl_now, 0)}</b> {UNIT}（{cl_p}，已售未结 = 未来收入蓄水池）" if cl_now is not None else "")
            + "。"))
    H.append("<div class='grid2'>")
    if profile == "bank":
        for sr, nm, ref, cid in [(cap1, "核心一级(%)", 7.5, "g5"), (capa, "资本充足率(%)", 10.5, "g6")]:
            if sr is not None:
                ss = sr.dropna()
                H.append(fig_lines(cid, [(ss.index.tolist(), ss.tolist(), nm, C_MAIN, None, 2)],
                                   f"{nm}（虚线 = 监管参考线）", height=300, shapes=[hline(ref)]))
    else:
        if dar is not None:
            dd = dar.dropna()
            dd = dd * 100 if abs(dd.max()) < 1 else dd
            H.append(fig_lines("g5", [(dd.index.tolist(), dd.tolist(), "资产负债率(%)", C_MAIN, None, 2)],
                               "资产负债率（%，虚线=80 参考）", height=300, shapes=[hline(80)]))
        if contract_liab is not None:
            cc = contract_liab.dropna()
            H.append(fig_lines("g6", [(cc.index.tolist(), cc.tolist(), f"合同负债({UNIT})", C_ACC, None, 2)],
                               f"合同负债（已售未结，{UNIT}）", height=300))
    H.append("</div>")

    # ─ 4 效率与资产质量 ─
    H.append(f"<h2>四、效率与资产质量（{PNAME}口径）</h2>")
    if profile == "bank":
        nimn, nimp = latest_valid(nim) if nim is not None else (None, None)
        cirn, _ = latest_valid(cir) if cir is not None else (None, None)
        npln, _ = latest_valid(npl) if npl is not None else (None, None)
        covn, _ = latest_valid(cov) if cov is not None else (None, None)
        H.append(para(
            f"净息差 NIM <b>{fmt(nimn)}%</b>（{nimp}）——银行盈利的核心引擎；"
            f"收入成本比 <b>{fmt(cirn)}%</b>；不良率 <b>{fmt(npln)}%</b>，"
            f"拨备覆盖率 <b>{fmt(covn, 0)}%</b>（150% 为监管参考）。"
            "NIM 下行 + 不良上行同时出现 = 典型周期底部组合；拨备覆盖率高 = 利润调节缓冲厚。"))
    elif profile == "software":
        gmn, gmp = latest_valid(gm) if gm is not None else (None, None)
        rdn, rdp = latest_valid(rd_ratio) if rd_ratio is not None else (None, None)
        exn, exq = latest_valid(exp_ratio) if exp_ratio is not None else (None, None)
        atn, _ = latest_valid(ast_turn) if ast_turn is not None else (None, None)

        def _pct(v):
            # rd_ratio / exp_ratio 都是本报告自算的「费用 ÷ 收入」，恒为**小数比率** → 直接 ×100。
            # 不能用“<1 才 ×100”的启发式：三费率 1.094（=109.4%）会被误判成 1.09%。
            return None if v is None else v * 100

        H.append(para(
            f"毛利率 <b>{fmt(gmn)}%</b>（{gmp}）——软件/科技公司的核心盈利结构指标，"
            "反映产品化程度与人力成本占比。<b>趋势比单点重要</b>：骤降通常意味着业务结构变化"
            "（高毛利软件/订阅占比下降，硬件、集成或人力外包占比上升），"
            "而非单纯的成本波动。"
            + (f"研发费用率 <b>{fmt(_pct(rdn))}%</b>（{rdp}）——亏损期该比率高不必然是坏事"
               "（投入换产品壁垒），但必须与收入增速对照：**收入不涨而费用刚性 = 烧钱无产出**。"
               if rdn is not None else "")
            + (f"三费（研发+销售+管理）合计占收入 <b>{fmt(_pct(exn))}%</b>（{exq}）。"
               if exn is not None else "")
            + f"资产周转率 <b>{fmt(atn)}</b>（轻资产公司该值偏低属正常）。"))
    else:
        gmn, gmp = latest_valid(gm) if gm is not None else (None, None)
        itn, _ = latest_valid(inv_turn) if inv_turn is not None else (None, None)
        atn, _ = latest_valid(ast_turn) if ast_turn is not None else (None, None)
        rcn, _ = latest_valid(roic) if roic is not None else (None, None)
        H.append(para(
            f"毛利率 <b>{fmt(gmn)}%</b>（{gmp}）——房企该指标受结转节奏（低毛利地提前结转）影响大，"
            f"趋势比单点重要；存货周转率 <b>{fmt(itn)}</b>，资产周转率 <b>{fmt(atn)}</b>，"
            f"ROIC <b>{fmt(rcn)}%</b>。"
            "房企存货周转天然慢（开发周期 2-3 年），骤降 = 竣工结转停滞或去化放缓。"))
    H.append("<div class='grid2'>")
    if profile == "bank":
        if nim is not None:
            nn = nim.dropna()
            H.append(fig_lines("g7", [(nn.index.tolist(), nn.tolist(), "净息差NIM(%)", C_MAIN, None, 2)],
                               "净息差 NIM（%）", height=300))
        if cir is not None:
            cc = cir.dropna()
            H.append(fig_lines("g8", [(cc.index.tolist(), cc.tolist(), "收入成本比(%)", C_ACC, None, 2)],
                               "收入成本比（%）", height=300))
        if npl is not None:
            n_ = npl.dropna()
            H.append(fig_lines("g9", [(n_.index.tolist(), n_.tolist(), "不良率(%)", C_NEG, None, 2)],
                               "不良率（%）", height=300))
        if cov is not None:
            c_ = cov.dropna()
            H.append(fig_lines("g10", [(c_.index.tolist(), c_.tolist(), "拨备覆盖率(%)", C_POS, None, 2)],
                               "拨备覆盖率（%）", height=300, shapes=[hline(150)]))
    else:
        if gm is not None:
            gg = gm.dropna()
            H.append(fig_lines("g7", [(gg.index.tolist(), gg.tolist(), "毛利率(%)", C_MAIN, None, 2)],
                               "毛利率（%）", height=300))
        if inv_turn is not None:
            ii = inv_turn.dropna()
            H.append(fig_lines("g8", [(ii.index.tolist(), ii.tolist(), "存货周转率", C_ACC, None, 2)],
                               "存货周转率", height=300))
        if roic is not None:
            rr = roic.dropna()
            H.append(fig_lines("g9", [(rr.index.tolist(), rr.tolist(), "ROIC(%)", C_WARN, None, 2)],
                               "ROIC（%）", height=300, shapes=[hline(0)]))
    H.append("</div>")

    # ─ 5 勾稽与信号（fraud-index 三桶）──
    H.append("<h2>五、勾稽与信号（三桶纪律）</h2>")
    confirmed, weak, missing = [], [], []
    # 勾稽1：四表期数一致性
    lens = {t: len(df.columns) for t, df in panels.items()}
    if len(set(lens.values())) == 1:
        confirmed.append(f"四表期间完全对齐（{list(lens.values())[0]} 期），跨表比率可逐期计算")
    else:
        weak.append(f"四表期数不一致 {lens}，跨表指标存在缺口")
    # 勾稽2：净利与 OCF 方向背离（银行弱化：连续 4 期反号才记）
    if ocf is not None and np_series is not None:
        both = pd.concat([ocf, np_series], axis=1).dropna()
        opp = (both.iloc[:, 0] * both.iloc[:, 1] < 0)
        if opp.iloc[-4:].all() and len(opp) >= 4:
            weak.append(f"经营现金流与净利润连续 {int(opp.iloc[-4:].sum())} 期反号（银行口径：或由贷款投放节奏主导，需结合资产负债表核对）")
    weak += [f"科目单季突增：{s}" for s in signals_weak]
    # 缺失清单按 profile 取该口径**真正需要**的指标：银行专属项（净息差/不良率/拨备）
    # 对非银不构成"缺口"。候选名用 | 分隔多写法——A 股叫「加权ROE」，港股叫「…的ROE」。
    _NEED = {
        "bank": [("净息差", "ability", "净息差"), ("不良率", "ability", "不良率"),
                 ("拨备覆盖率", "ability", "不良贷款拨备覆盖率|拨备覆盖率")],
        "general": [("加权ROE", "ability", "净资产收益率(ROE)|加权ROE"),
                    ("毛利率", "ability|income", "毛利率(GM)|销售毛利率")],
        "software": [("加权ROE", "ability", "净资产收益率(ROE)|加权ROE"),
                     ("毛利率", "ability|income", "毛利率(GM)|销售毛利率"),
                     ("研发费用", "income", "研发费用"),
                     ("货币资金", "balance", "货币资金")],
    }
    for nm, tbls, keys in _NEED.get(profile, _NEED["general"]):
        if all(pick(panels, t, *keys.split("|")) is None for t in tbls.split("|")):
            missing.append(f"{nm}（{tbls} 表中未找到）")
    if profile == "bank":
        missing.append("公募持仓/同行横截面（本数据源不含，需外部数据）")
    H.append("<div class='bucket'><span class='tag t-red'>明确异常</span>结论需报告证据支撑"
             + ("<ul>" + "".join(f"<li>{x}</li>" for x in confirmed) + "</ul>" if confirmed else "：<ul><li>未发现</li></ul>") + "</div>")
    H.append("<div class='bucket'><span class='tag t-yel'>弱信号</span>疑似但不构成结论"
             + ("<ul>" + "".join(f"<li>{x}</li>" for x in weak) + "</ul>" if weak else "：<ul><li>未发现</li></ul>") + "</div>")
    H.append("<div class='bucket'><span class='tag t-gray'>缺失数据</span>影响置信度的缺口"
             + ("<ul>" + "".join(f"<li>{x}</li>" for x in missing if x) + "</ul>"
                if any(missing) else "：<ul><li>未发现</li></ul>") + "</div>")

    # ─ 6 指标全景 ─
    H.append("<h2>六、指标全景（综合能力表核心项）</h2>")
    rows = []
    for label, s in [("加权ROE(%)", roe), ("总资产收益率ROA(%)", pick(panels, "ability", "总资产收益率(ROA)")),
                     ("毛利率(%)", gm), ("ROIC(%)", roic), ("存货周转率", inv_turn),
                     ("资产负债率(%)", dar), ("合同负债(亿)", contract_liab),
                     ("净息差(%)", nim), ("不良率(%)", npl), ("拨备覆盖率(%)", cov),
                     ("核心一级资本充足率(%)", cap1), ("杠杆倍数", lev),
                     ("客户存款(亿)", pick(panels, "ability", "客户存款")),
                     ("贷款总额(亿)", pick(panels, "ability", "贷款和垫款总额")),
                     ("员工人数", pick(panels, "ability", "员工人数"))]:
        if s is None:
            continue
        v_now, p_now = latest_valid(s)
        v_prev, _ = latest_valid(s, 2)
        v_first = next((x for x in s.tolist() if x is not None and not pd.isna(x)), None)
        rows.append(f"<tr><td class='l'>{label}</td><td>{fmt(v_first)}</td>"
                    f"<td>{fmt(v_prev)}</td><td><b>{fmt(v_now)}</b></td>"
                    f"<td>{fmt((v_now or 0)-(v_prev or 0), 2)}</td><td>{p_now}</td></tr>")
    H.append("<table><tr><th class='l'>指标</th><th>历史首值</th><th>上期</th><th>最新</th><th>变动</th><th>最新期</th></tr>"
             + "".join(rows) + "</table>")
    H.append(para("口径提醒：比率类为当期披露值；金额类 YTD 差分后才得单季。本报告全部数字直接来自四表面板，未做外部补充。"))

    H.append("</body></html>")
    out_html.write_text("\n".join(H), encoding="utf-8")
    # ★ 拷一份 plotly 到报告同目录（报告 + plotly.min.js 两个文件一起移动/分享）
    src_js = Path(__file__).resolve().parent.parent / "assets" / "plotly.min.js"
    dst_js = out_html.parent / "plotly.min.js"
    if src_js.exists() and not dst_js.exists():
        import shutil
        shutil.copy(src_js, dst_js)
    print(f"OK -> {out_html}（{out_html.stat().st_size/1024:.0f} KB，旁边带 plotly.min.js）")
    print(f"[核对] 营收 {ryp} = {fmt(rev[ryp])}（应与东财原表一致）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", required=True, help="parse_eastmoney_xls.py 的输出目录")
    ap.add_argument("--out", default=None,
                    help="报告路径；缺省 = <当前工程>/financial-statement-analysis/<公司>_财务分析报告.html")
    ap.add_argument("--profile", default="bank", choices=["bank", "general", "software"])
    a = ap.parse_args()
    # ★ 输出默认落在"当前工程"下的 financial-statement-analysis/（按仓库惯例：产物目录集中、gitignore）
    out = Path(a.out) if a.out else None
    if out is None:
        meta = json.loads((Path(a.panel) / "meta.json").read_text(encoding="utf-8"))
        out = Path("financial-statement-analysis") / f"{meta.get('company','公司')}_财务分析报告.html"
    build(Path(a.panel), out, a.profile)
