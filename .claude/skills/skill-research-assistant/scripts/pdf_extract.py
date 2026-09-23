#!/usr/bin/env python
"""PDF 提取 —— 研报提取（仓库根 research_report/，公共文献库）的前置工具。

券商研报 PDF 分两类，处理方式完全不同，**先自动判定再走对应路径**：

| 模式 | 特征 | 做法 | 成本 |
|---|---|---|---|
| `text`   | 含可提取文本层（文字版 PDF） | 直接抽出纯文本 → `.txt` | 低（无 token 成本） |
| `render` | 图片型/扫描件（每页大量图片、可提取字符≈0） | 逐页渲染 PNG → 用 **Read 工具看图** | 高（每页一张图） |

⚠ 本机没装 poppler 的 `pdftoppm`，**Read 工具无法直接打开 PDF**；
图片型 PDF 必须先用本脚本渲染成 PNG，再用 Read 工具逐页读（多模态看图，不是 OCR——
好处是图表/公式/净值曲线都能看懂，OCR 反而易错）。

用法：
  python scripts/pdf_extract.py <pdf> [--outdir DIR] [--dpi 150] [--mode auto|text|render]
                                 [--pages 3-22] [--sample 8] [--threshold 200]

  text   → 写出 <outdir>/<stem>.txt
  render → 写出 <outdir>/<stem>_p03.png …（1-based 补零对齐；--pages 限定范围）

判定：抽样 min(sample, 总页数) 页，平均可提取字符 < threshold → 判为图片型。
省 token 提示：只需核心章节时用 `--pages` 限定，研报的免责声明页通常可跳过。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import pymupdf  # PyMuPDF ≥1.24 的新名字
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore


def parse_pages(spec: str | None, total: int) -> list[int]:
    """'3-22' / '5' / '1-3,7,9-10' → 0-based 页索引列表（去重保序）。"""
    if not spec:
        return list(range(total))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out += list(range(int(a) - 1, int(b)))
        else:
            out.append(int(part) - 1)
    return [i for i in dict.fromkeys(out) if 0 <= i < total]


def probe(doc, sample: int) -> tuple[float, int]:
    """抽样若干页，返回 (平均可提取字符数, 抽样页数)。"""
    n = min(sample, doc.page_count)
    idx = sorted(set(round(i * (doc.page_count - 1) / max(n - 1, 1)) for i in range(n)))
    total = sum(len((doc[i].get_text() or "").strip()) for i in idx)
    return total / max(len(idx), 1), len(idx)


def extract_text(doc, pages: list[int]) -> str:
    return "".join(f"\n\n===== page {i + 1} =====\n\n" + (doc[i].get_text() or "")
                   for i in pages)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--outdir", default=None, help="默认 <pdf 同目录>/_pdf_extract/<stem>/")
    ap.add_argument("--dpi", type=int, default=150, help="render 模式分辨率（150 实测中文可读）")
    ap.add_argument("--mode", choices=["auto", "text", "render"], default="auto")
    ap.add_argument("--pages", default=None, help="页范围，如 3-22 / 1-3,7,9-10；默认全部")
    ap.add_argument("--sample", type=int, default=8, help="auto 判定的抽样页数")
    ap.add_argument("--threshold", type=float, default=200.0,
                    help="抽样页平均字符数低于此值 → 判为图片型")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"✗ 文件不存在: {pdf}", file=sys.stderr)
        return 1
    out = Path(args.outdir) if args.outdir else pdf.parent / "_pdf_extract" / pdf.stem
    out.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf)
    pages = parse_pages(args.pages, doc.page_count)
    avg, ns = probe(doc, args.sample)
    mode = args.mode if args.mode != "auto" else ("text" if avg >= args.threshold else "render")
    print(f"PDF: {pdf.name} | 共 {doc.page_count} 页，本次取 {len(pages)} 页 | "
          f"抽样 {ns} 页平均可提取 {avg:.0f} 字符 → 判定 **{mode}**")

    if mode == "text":
        txt = out / f"{pdf.stem}.txt"
        txt.write_text(extract_text(doc, pages), encoding="utf-8")
        print(f"✓ 文本已写出: {txt}（{len(txt.read_text(encoding='utf-8')):,} 字符）"
              f"—— 直接用 Read 读这个 txt")
    else:
        w = len(str(doc.page_count))
        made = []
        for i in pages:
            p = out / f"{pdf.stem}_p{i + 1:0{w}d}.png"
            doc[i].get_pixmap(dpi=args.dpi).save(p)
            made.append(p)
        print(f"✓ 渲染 {len(made)} 页 PNG @ {args.dpi}dpi → {out}")
        print(f"  下一步：用 Read 工具逐页看，例如 {made[0].name} … {made[-1].name}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
