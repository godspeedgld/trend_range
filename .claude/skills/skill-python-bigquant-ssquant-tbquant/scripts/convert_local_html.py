"""本地 BigQuant wiki HTML → markdown 转换器（skill 参考文档构建用）。

输入：bigquant_references/ 下浏览器保存的 wiki 页面 HTML（含 _files 资源目录，忽略）
输出：references/bigquant/ 下对应 md 文件

用法：
  python convert_local_html.py            # 转换全部映射
  python convert_local_html.py bq_trader  # 只转单个

映射（本地文件名含中文/空格，按模式匹配）：
  bq_trader.md       ← Bigtrader交易引擎API*.html
  bq_dai.md          ← 数据平台_DAI*.html
  bq_dai_fun.md      ← DAI SQL 函数列表*.html
  bq_dai_sql_fqa.md  ← DAI SQL FAQ*.html

转换规则：标题层级保留 / 代码块 fence / 表格转 markdown 表 / 列表保留 / 去导航与脚本样式。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REFS = SKILL / "references" / "bigquant"
SRC = SKILL.parents[2] / "bigquant_references"      # c:/Quant/trend_range/bigquant_references

MAPPING = {
    "bq_trader": ("Bigtrader交易引擎API", "https://bigquant.com/wiki/doc/nxDOuIdhm2"),
    "bq_dai": ("数据平台_DAI", "https://bigquant.com/wiki/doc/PLSbc1SbZX"),
    "bq_dai_fun": ("DAI SQL 函数列表", "https://bigquant.com/wiki/doc/Rceb2JQBdS"),
    "bq_dai_sql_fqa": ("DAI SQL FAQ", "https://bigquant.com/wiki/doc/C7MciptBTM"),
}


def _inline_md(el) -> str:
    """行内元素 → markdown（加粗/斜体/代码）。"""
    if isinstance(el, NavigableString):
        return str(el)
    if not isinstance(el, Tag):
        return ""
    name = el.name.lower()
    if name in ("script", "style"):
        return ""
    if name == "br":
        return "\n"
    inner = "".join(_inline_md(c) for c in el.children)
    if name in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else inner
    if name in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else inner
    if name in ("code", "tt"):
        return f"`{inner}`" if inner.strip() else inner
    if name == "a" and el.get("href"):
        href = el["href"]
        if not href.startswith(("http", "#", "mailto")):
            href = "https://bigquant.com" + href
        return f"[{inner.strip()}]({href})" if inner.strip() else ""
    return inner


def _table_md(tbl: Tag) -> str:
    """<table> → markdown 表格（含表头分隔行）。"""
    rows = []
    for tr in tbl.find_all("tr"):
        cells = []
        for cell in tr.find_all(["th", "td"]):
            txt = " ".join(_inline_md(c) for c in cell.children).strip()
            txt = re.sub(r"\s+", " ", txt).replace("|", "\\|")
            cells.append(txt)
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join(["---"] * ncol) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _block_md(el: Tag) -> list[str]:
    """块级元素 → markdown 段落列表。"""
    name = el.name.lower()
    if name in ("script", "style", "nav", "button", "iframe", "form"):
        return []
    if name == "table":
        t = _table_md(el)
        return [t, ""] if t else []
    if name == "pre":
        code = el.get_text().strip("\n")
        return [f"```\n{code}\n```", ""]
    if name.startswith("h") and len(name) == 2 and name[1].isdigit():
        lvl = min(int(name[1]) + 1, 6)      # wiki h1=h2 平铺，整体降一级从 ## 起
        txt = _inline_md(el).strip() or el.get_text().strip()
        txt = re.sub(r"\s+", " ", txt).strip("__").strip()
        return [f"{'#' * lvl} {txt}", ""]
    if name in ("ul", "ol"):
        items = []
        for k, li in enumerate(el.find_all("li", recursive=False), 1):
            txt = re.sub(r"\s+", " ", _inline_md(li)).strip()
            if txt:
                items.append(f"{k}. {txt}" if name == "ol" else f"- {txt}")
        return (["\n".join(items), ""] if items else [])
    if name == "blockquote":
        txt = el.get_text().strip()
        return ["> " + txt.replace("\n", "\n> "), ""] if txt else []
    if name == "hr":
        return ["---", ""]
    if name == "p":
        txt = _inline_md(el).strip()
        txt = re.sub(r"\n{2,}", "\n", txt)
        return [txt, ""] if txt else []
    # 兜底：容器（div 等）递归
    out = []
    for c in el.children:
        if isinstance(c, NavigableString):
            t = str(c).strip()
            if t:
                out += [t, ""]
        elif isinstance(c, Tag):
            out += _block_md(c)
    return out


def _postprocess(md: str) -> str:
    """切侧边栏/页脚 + 清理标题伪影（styled-components 页面无语义标签所致）。"""
    lines = md.split("\n")
    # ① 侧边栏：最后一个"导入文档"行之前全删（wiki 侧栏目录的固定尾部标记）
    last_nav = max((i for i, l in enumerate(lines) if l.strip() == "导入文档"), default=-1)
    if last_nav >= 0:
        lines = lines[last_nav + 1:]
    # ② 页脚：评论框/版权等尾部垃圾
    for i, l in enumerate(lines):
        if any(k in l for k in ("还没有评论", "抢个沙发", "© ", "Copyright")):
            lines = lines[:i]
            break
    md = "\n".join(lines)
    # ③ 标题伪影：wiki 用 **加粗** 当标题 → "#### #**xxx**" / "## **xxx**"
    md = re.sub(r"^(#{2,6})\s*#+\*\*(.+?)\*\*\s*$", r"\1 \2", md, flags=re.M)
    md = re.sub(r"^(#{2,6})\s*\*\*(.+?)\*\*\s*$", r"\1 \2", md, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def convert(html_path: Path, out_md: Path, title: str, url: str):
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript"]):
        tag.decompose()
    # styled-components 页面：无语义容器，直接遍历 body（class 启发式会误中小 wrapper）
    body = soup.body or soup
    blocks = []
    for c in body.children:
        if isinstance(c, Tag):
            blocks += _block_md(c)
    md = _postprocess("\n".join(blocks))
    header = (f"# {title}\n\n"
              f"> 来源：{url}（本地 HTML 快照转换；远程为最新版本，如需更新访问链接）\n\n")
    out_md.write_text(header + md, encoding="utf-8")
    n_lines = md.count("\n")
    n_tables = len(re.findall(r"^\|[-\s|]+\|$", md, flags=re.M))
    n_code = md.count("```") // 2
    print(f"[ok] {out_md.name}: {len(md)} chars, {n_lines} 行, 表格 {n_tables}, 代码块 {n_code}")


# ═══ 手工补注（口径警示等，不来自 HTML 源）═══
# 转换会覆盖 references/*.md → 转换后自动重应用下列补注。
# 补注内容与 SKILL.md 移植 checklist 第 1 条同源，改动时两处同步。
PATCHES: dict[str, list[tuple[str, str]]] = {
    "bq_dai_fun.md": [
        ("| m_ta_atr | 时间序列上该窗口内的真实波动幅度均值 |",
         "| m_ta_atr | 时间序列上该窗口内的真实波动幅度均值（= `m_avg(TR)` 即 **SMA 口径，非 Wilder RMA**"
         "——与 pandas `ewm(alpha=1/n)` 在 TR 突变期差 3~16%，吊灯止损/波动率目标类策略需 Python 兜底重算对齐，"
         "见 SKILL.md 移植 checklist） |"),
        ("| m_ta_ema | 时间序列上 arg 在该窗口内的指数均值 |",
         "| m_ta_ema | 时间序列上 arg 在该窗口内的指数均值（⚠ alpha 是 2/(n+1)[pandas span] "
         "还是 1/n[Wilder] 未证实，两种相差明显） |"),
        ("| m_ta_rsi | 时间序列上 arg 在该窗口内的相对强弱指数 |",
         "| m_ta_rsi | 时间序列上 arg 在该窗口内的相对强弱指数（⚠ 经典定义用 Wilder RMA 平滑，"
         "BigQuant 口径未证实） |"),
        ("| m_ta_adxr | 时间序列上该窗口内的平均趋向指数评估 |",
         "| m_ta_adxr | 时间序列上该窗口内的平均趋向指数评估（⚠ 口径未证实——经典定义为 Wilder 系，"
         "用于策略判定前先小样本对照本地重算，见 SKILL.md 移植 checklist 第 1 条） |"),
        ("| m_ta_trix | 时间序列上 arg 在该窗口内的三重指数平滑平均线 |",
         "| m_ta_trix | 时间序列上 arg 在该窗口内的三重指数平滑平均线（⚠ 口径未证实——经典定义为 "
         "Wilder/EMA 系，BigQuant 实现可能为 SMA/其他平滑；用于策略判定前先小样本对照本地重算，"
         "见 SKILL.md 移植 checklist 第 1 条） |"),
    ],
    "bq_dai.md": [
        ("| timeperiod周期的均幅指标 | ta_atr(high, low, close, timeperiod) |",
         "| timeperiod周期的均幅指标（=SMA 口径，**非 Wilder RMA**——实证 TR 突变期差 3~16%，"
         "吊灯/波动率类策略须 pandas Wilder 兜底） | ta_atr(high, low, close, timeperiod) |"),
    ],
}


def reapply_patches():
    """转换后重应用手工补注（幂等：已含补注则跳过）。"""
    for fname, pairs in PATCHES.items():
        p = REFS / fname
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        n = 0
        for old, new in pairs:
            if old in t:            # 未打补注的原始行 → 替换
                t = t.replace(old, new)
                n += 1
        if n:
            p.write_text(t, encoding="utf-8")
        print(f"[patch] {fname}: 重应用 {n} 条补注（共定义 {len(pairs)} 条）")


def main():
    keys = sys.argv[1:] or list(MAPPING)
    REFS.mkdir(parents=True, exist_ok=True)
    for key in keys:
        stem, url = MAPPING[key]
        cands = sorted(SRC.glob(f"{stem}*.html"))
        if not cands:
            print(f"[skip] {key}: 找不到 {stem}*.html")
            continue
        convert(cands[0], REFS / f"{key}.md", stem, url)
    reapply_patches()


if __name__ == "__main__":
    main()
