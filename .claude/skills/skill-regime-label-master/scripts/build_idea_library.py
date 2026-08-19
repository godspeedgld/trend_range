#!/usr/bin/env python
"""扫描 REPLICATION_ROOT 复现目录，汇总思路库原始材料 → 01_initial/reference_idea.md。

脚本职责（确定性部分）：
  1. 遍历 {replication_root}/*/，检查 02_approach/main_approach.md、
     03_regime_analysis/regime_methods.md、04_delivery/final_report.md 是否齐全
  2. 齐全的目录提取文档关键内容，拼接为 reference_idea.md 的原始材料区

4 方面总结（核心思路/解决问题/理论优缺点/实证结果）由 agent 按
references/idea_library.md 规范在生成的文件上补充完善。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REQUIRED_DOCS = [
    "02_approach/main_approach.md",
    "03_regime_analysis/regime_methods.md",
    "04_delivery/final_report.md",
]


def _load_env_upward(start: Path, max_up: int = 8) -> None:
    p = start.resolve()
    for _ in range(max_up):
        env_file = p / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        if p.parent == p:
            break
        p = p.parent


def default_replication_root() -> Path:
    _load_env_upward(Path(__file__).parent)
    env = os.environ.get("REPLICATION_ROOT")
    return Path(env) if env else Path.cwd() / "replication"


def scan_projects(root: Path) -> list[dict]:
    """扫描文档齐全的复现项目。"""
    found = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")):
            continue
        if d.name == "regime-projects":  # 本技能工程目录，跳过
            continue
        missing = [doc for doc in REQUIRED_DOCS if not (d / doc).exists()]
        if not missing:
            found.append({"name": d.name, "dir": str(d)})
    return found


def extract_summary(project_dir: Path) -> str:
    """提取项目的核心文档片段（方法名/公式行/结论行）。"""
    parts = []
    for doc in REQUIRED_DOCS:
        p = project_dir / doc
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        # 提取标题行 + 方法/公式/结论相关行（保守截取，避免文件过大）
        lines = text.splitlines()
        key_lines = [ln for ln in lines
                     if ln.startswith("#") or "公式" in ln or "dist" in ln.lower()
                     or "思路" in ln or "准确率" in ln or "区分" in ln or "HMM" in ln
                     or "Zig" in ln or "效率" in ln or "强度" in ln or "夏普" in ln]
        parts.append(f"#### `{doc}`\n" + "\n".join(key_lines[:40]))
    return "\n\n".join(parts)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--replication-root", default=str(default_replication_root()))
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    root = Path(args.replication_root).resolve()
    if not root.exists():
        print(f"错误: replication root 不存在: {root}", file=sys.stderr)
        return 1

    projects = scan_projects(root)
    if not projects:
        print(f"警告: {root} 下无文档齐全的复现项目", file=sys.stderr)

    out_path = proj / "01_initial" / "reference_idea.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Regime 思路库（reference_idea.md）", "",
        "> 来源：REPLICATION_ROOT 下文档齐全的研报/论文复现项目",
        "> 提取规范：核心思路 / 解决问题 / 理论优缺点 / 实证结果（4 方面，见 references/idea_library.md）",
        "> **agent 须为每个项目补充 4 方面总结表**（脚本已汇总原始材料）", "",
        f"共收录 {len(projects)} 个项目：{', '.join(x['name'] for x in projects)}", "",
        "---", "",
    ]
    for item in projects:
        lines.append(f"## {item['name']}")
        lines.append("")
        lines.append("<!-- agent 补充：4 方面总结表 -->")
        lines.append("| 方面 | 内容 |")
        lines.append("|------|------|")
        lines.append("| 核心思路 | <待补充> |")
        lines.append("| 解决问题 | <待补充> |")
        lines.append("| 理论优缺点 | <待补充> |")
        lines.append("| 实证结果 | <待补充> |")
        lines.append("")
        lines.append("### 原始材料（脚本汇总）")
        lines.append("")
        lines.append(extract_summary(Path(item["dir"])))
        lines.append("")
        lines.append("---")
        lines.append("")

    # 思路分类总结表（agent 必填，迭代导航核心）
    lines += [
        "## 思路分类总结表（agent 必填）", "",
        "> 按方法方向归纳（格式见 references/idea_library.md）。首次迭代从此表选方向，后续迭代从此表找改进思路。", "",
        "| 方向 | 优点 | 缺点 | 实证经验 | 可能改进思路 |",
        "|------|------|------|---------|------------|",
        "| <方向1> | <待补充> | <待补充> | <待补充> | <待补充> |",
        "", "> **agent 补充完 4 方面总结后，必须完成此分类表**", "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")

    # 更新 manifest
    mp = proj / "manifest.json"
    if mp.exists():
        m = json.loads(mp.read_text(encoding="utf-8-sig"))
        m["idea_library"] = {"source_root": str(root), "projects": [x["name"] for x in projects]}
        mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "n_projects": len(projects),
                      "projects": [x["name"] for x in projects],
                      "output": str(out_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
