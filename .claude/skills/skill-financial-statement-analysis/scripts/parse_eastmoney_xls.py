"""parse_eastmoney_xls.py — 把东方财富导出的四表 .xls 解析成统一面板

输入布局（实测 2026-09，东财"财务报表"导出）：
  第 1 行 = [单位说明, '', '公司名(代码)  表名']
  第 2 行 = ['日期', '2026年6月', '2026年3月', ...]   ← 46 期，**最新在前**
  第 3 行起 = 指标行：[指标名(带\\xa0尾巴), 值, 值, ...]
  值形态：数字字符串 / '--' / '62.72%' / 带千分位逗号

四张表类型（按标题自动识别）：
  利润报表 / 资产负债表 / 现金流量报表 / 公司综合能力报表

输出（--out 目录）：
  panel_<type>.parquet   行=指标名，列=报告期（升序，最旧在前）
  meta.json              公司名/代码/期数/各表指标清单

口径（重要，下游 build_report 依赖）：
  利润表 / 现金流量表 = **累计值**（'2026年6月' = 上半年 YTD）→ 单季化需差分
  资产负债表 / 综合能力表 = 时点值或当期比率，不做差分

用法：
  python parse_eastmoney_xls.py --dir "C:\\...\\平安银行" --out <dir>
  python parse_eastmoney_xls.py --files a.xls b.xls c.xls d.xls --out <dir>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

# 标题 → 面板类型（标题第二格形如 '平安银行(000001)  利润报表'）
TABLE_TYPES = [
    ("利润报表", "income"), ("利润表", "income"),
    ("资产负债表", "balance"),
    ("现金流量报表", "cashflow"), ("现金流量表", "cashflow"),
    ("公司综合能力报表", "ability"), ("综合能力", "ability"),
    # 港股版东财导出把同一张表叫「财务指标表」（首批非 A 股数据实测：
    # 五一视界 06651.HK，内容与 A 股「公司综合能力表」一致：每股指标/ROE/周转/负债率）
    ("财务指标表", "ability"),
]
PERIOD_RE = re.compile(r"^(\d{4})年(\d{1,2})月?$")


def clean_value(v):
    """'--'/'—' → NaN；'62.72%' → 62.72；'1,234.5' → 1234.5；数字直通"""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", "").replace(",", "").strip()
    if s in {"--", "—", "-", ""}:
        return None
    if s.endswith("%"):
        s = s[:-1]
    try:
        return float(s)
    except ValueError:
        return None


def parse_one(path: Path) -> dict:
    wb = xlrd.open_workbook(str(path))
    ws = wb.sheet_by_index(0)
    title = str(ws.cell_value(0, 2) or ws.cell_value(0, 0) or path.stem)
    # 公司名(代码)
    m = re.search(r"([\u4e00-\u9fa5A-Za-z*·\-]+)\((\d{6})\)", title)
    company = m.group(1) if m else title.split()[0] if title.split() else path.stem
    code = m.group(2) if m else None
    ttype = next((t for kw, t in TABLE_TYPES if kw in title), None)
    if ttype is None:  # 标题识别不了就用文件名
        ttype = next((t for kw, t in TABLE_TYPES if kw in path.name), "unknown")

    # 日期行 → period 标签（升序重排）
    raw_periods = [(c, str(ws.cell_value(1, c)).strip()) for c in range(1, ws.ncols)]
    dated = []
    for c, p in raw_periods:
        pm = PERIOD_RE.match(p)
        if pm:
            dated.append((c, f"{pm.group(1)}-{int(pm.group(2)):02d}", int(pm.group(1)), int(pm.group(2))))
    dated.sort(key=lambda x: x[1])                      # 最旧在前
    cols = [d[0] for d in dated]
    periods = [d[1] for d in dated]

    rows, names = [], []
    for r in range(2, ws.nrows):
        name = str(ws.cell_value(r, 0)).replace("\xa0", "").strip()
        if not name:
            continue
        vals = [clean_value(ws.cell_value(r, c)) for c in cols]
        rows.append(vals); names.append(name)
    df = pd.DataFrame(rows, index=names, columns=periods)
    df = df[~df.index.duplicated(keep="first")]

    # ★ 单位 / 币种：源表末尾两行是「单位=百万」「币种=人民币」这类**文本**值，
    #   会被 clean_value 洗成 None（它只保留数字）→ 单独抓原始值。
    #   宁缺毋错：报告若写死"亿元"，对五一小公司会差 100 倍（实测五一视界单位=百万）。
    unit = currency = None
    for r in range(2, ws.nrows):
        nm = str(ws.cell_value(r, 0)).replace("\xa0", "").strip()
        if nm in ("单位", "币种"):
            vs = [str(ws.cell_value(r, c)).strip() for c in cols]
            v = next((x for x in vs if x and x not in {"--", "—", "-"}), None)
            if nm == "单位":
                unit = v
            else:
                currency = v
    return {"type": ttype, "company": company, "code": code,
            "title": title, "df": df, "periods": periods,
            "unit": unit, "currency": currency}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=str, help="含四表 .xls 的目录")
    ap.add_argument("--files", nargs="*", type=str, help="或直接给文件列表")
    ap.add_argument("--out", type=str, default=None,
                help="面板输出目录；缺省 = <当前工程>/financial-statement-analysis/panel")
    a = ap.parse_args()
    files = sorted(Path(a.dir).glob("*.xls")) if a.dir else [Path(f) for f in a.files]
    if not files:
        return print("没有找到 .xls 文件")
    parsed = [parse_one(f) for f in files]
    # ★ 多公司并存：默认面板目录按公司名隔离（panel_保利发展/ panel_万科/ …）
    out = (Path(a.out) if a.out
           else Path("financial-statement-analysis") / f"panel_{parsed[0]['company']}")
    out.mkdir(parents=True, exist_ok=True)

    meta = {"tables": {}, "company": None, "code": None}
    for f, d in zip(files, parsed):
        d["df"].to_parquet(out / f"panel_{d['type']}.parquet")
        meta["tables"][d["type"]] = {"file": f.name, "rows": len(d["df"]),
                                     "periods": len(d["periods"]),
                                     "first": d["periods"][0], "last": d["periods"][-1],
                                     "fields": list(d["df"].index)}
        meta["tables"][d["type"]]["unit"] = d.get("unit")
        meta["tables"][d["type"]]["currency"] = d.get("currency")
        meta["company"] = meta["company"] or d["company"]
        meta["code"] = meta["code"] or d["code"]
        meta["unit"] = meta.get("unit") or d.get("unit")
        meta["currency"] = meta.get("currency") or d.get("currency")
        print(f"  {d['type']:<9} {len(d['df']):>3} 指标 x {len(d['periods'])} 期  "
              f"{d['periods'][0]} ~ {d['periods'][-1]}  <- {f.name}")
    meta["n_periods"] = max(t["periods"] for t in meta["tables"].values())
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    print(f"公司: {meta['company']} ({meta['code']})；面板与 meta.json 已写出 -> {out}")

    # ★ 抽查断言：打印关键科目首末期，供与原表肉眼比对（吸取"错数字"教训）
    chk = [("income", "一、营业收入"), ("income", "五、净利润"),
           ("balance", "一、资产合计")]
    print("\n[抽查] 首期 / 末期（应与东财原表一致）：")
    for t, k in chk:
        p = out / f"panel_{t}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        hit = [i for i in df.index if k.replace("一、", "").replace("五、", "") in i]
        if hit:
            r = df.loc[hit[0]]
            print(f"  [{t}] {hit[0]}: {df.columns[0]}={r.iloc[0]}  {df.columns[-1]}={r.iloc[-1]}")


if __name__ == "__main__":
    sys.exit(main())
