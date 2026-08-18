#!/usr/bin/env python
"""Step 5 质量控制 — 检查工程产物完整性。

必需产物：
  01_initial/regime_label.md + regime_label_view.html + reference_idea.md
  02_iteration/iter_XXX/（至少 1 次：main_idea.md + regime_backtest/ 三件）
  04_delivery/final_report.md
  manifest.json

可选：03_cross_validation/（交叉验证，建议有）
"""
import sys, os, io, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    proj = Path(project_dir)
    print("=" * 70); print("质量控制 — 产物完整性检查"); print("=" * 70)

    # Step 1 初始化产物
    for rel, label in [
        ("01_initial/regime_label.md", "标注数据"),
        ("01_initial/regime_label_view.html", "标注可视化"),
        ("01_initial/reference_idea.md", "思路库"),
    ]:
        p = proj / rel
        if not p.exists() or p.stat().st_size == 0:
            errors.append(f"[FAIL] {label} 缺失或为空: {rel}")
        else:
            print(f"[PASS] {label}: {rel} ({p.stat().st_size} bytes)")

    # 思路库是否补充完成（检查待补充占位）
    idea = proj / "01_initial" / "reference_idea.md"
    if idea.exists():
        text = idea.read_text(encoding="utf-8")
        if "<待补充>" in text:
            warnings.append("[WARN] 思路库仍有 <待补充> 占位（agent 须完成 4 方面总结）")

    # Step 2 迭代产物
    iter_root = proj / "02_iteration"
    iter_dirs = sorted([d for d in iter_root.iterdir() if d.is_dir()]) if iter_root.exists() else []
    if not iter_dirs:
        errors.append("[FAIL] 无任何迭代目录（02_iteration/iter_XXX）")
    else:
        print(f"[PASS] 迭代次数: {len(iter_dirs)} ({', '.join(d.name for d in iter_dirs)})")
        for d in iter_dirs:
            for rel, label in [
                ("main_idea.md", f"{d.name} 迭代思路"),
                ("regime_backtest/regime_change.md", f"{d.name} 算法改动"),
                ("regime_backtest/regime_segments.md", f"{d.name} 划分结果"),
                ("regime_backtest/regime_view.html", f"{d.name} 可视化"),
                ("evaluate.json", f"{d.name} 区分度评估"),
            ]:
                p = d / rel
                if not p.exists() or p.stat().st_size == 0:
                    errors.append(f"[FAIL] {label} 缺失: {d.name}/{rel}")
                else:
                    print(f"[PASS] {label}: {d.name}/{rel}")

    # Step 3 交叉验证（建议）
    cv = proj / "03_cross_validation"
    if cv.exists() and any(cv.iterdir()):
        for rel in ["regime_segments.md", "regime_view.html"]:
            p = cv / rel
            if p.exists() and p.stat().st_size > 0:
                print(f"[PASS] 交叉验证 {rel}")
            else:
                warnings.append(f"[WARN] 交叉验证缺 {rel}")
    else:
        warnings.append("[WARN] 无交叉验证产物（03_cross_validation 为空）")

    # Step 4 最终报告
    fr = proj / "04_delivery" / "final_report.md"
    if not fr.exists() or fr.stat().st_size == 0:
        errors.append("[FAIL] 最终报告缺失: 04_delivery/final_report.md")
    else:
        print(f"[PASS] 最终报告: ({fr.stat().st_size} bytes)")

    # manifest
    mp = proj / "manifest.json"
    if not mp.exists():
        errors.append("[FAIL] manifest.json 缺失")
    else:
        m = json.loads(mp.read_text(encoding="utf-8-sig"))
        if m.get("label_source") is None:
            errors.append("[FAIL] manifest 缺 label_source（先跑 zigzag_label.py）")
        if not m.get("iterations"):
            warnings.append("[WARN] manifest 无迭代记录")
        else:
            print(f"[PASS] manifest 迭代记录: {len(m['iterations'])} 条")

    _summary(errors, warnings)
    return 1 if errors else 0


def _summary(errors, warnings):
    print("\n" + "=" * 70); print("错误: %d, 警告: %d" % (len(errors), len(warnings)))
    for e in errors: print(e)
    for w in warnings: print(w)
    print("【结果】未通过" if errors else "【结果】通过")


def main():
    if len(sys.argv) < 2:
        print("Usage: python quality_gate_check.py {project_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(check(sys.argv[1]))


if __name__ == "__main__":
    main()
