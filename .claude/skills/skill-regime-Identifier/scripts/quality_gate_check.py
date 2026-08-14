#!/usr/bin/env python3
"""Step 7 质量门禁 — 验证所有必需产物存在且非空"""
import sys, os, io, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    proj = Path(project_dir)
    print("=" * 70); print("Step 7 质量门禁 — 产物完整性检查"); print("=" * 70)

    # 必需产物（中文研报可跳过 translation）
    required = [
        ("02_approach/main_approach.md", "方法提取"),
        ("03_regime_analysis/regime_methods.md", "Regime 方法"),
        ("03_regime_analysis/regime_impl.py", "Regime 实现"),
        ("03_regime_analysis/data_params.json", "数据参数"),
        ("03_regime_analysis/regime_segments.md", "时间段划分表"),
        ("03_regime_analysis/regime_view.html", "Regime 可视化"),
        ("04_delivery/final_report.md", "最终报告"),
        ("manifest.json", "项目元数据"),
    ]

    for rel, label in required:
        p = proj / rel
        if not p.exists():
            errors.append(f"[FAIL] {label} 不存在: {rel}")
        elif p.stat().st_size == 0:
            errors.append(f"[FAIL] {label} 为空: {rel}")
        else:
            print(f"[PASS] {label}: {rel} ({p.stat().st_size} bytes)")

    # 可选产物
    optional = [
        ("01_translation/full_translation.md", "翻译（中文可跳过）"),
        ("03_regime_analysis/regime_stats.json", "Regime 统计"),
    ]
    for rel, label in optional:
        p = proj / rel
        if p.exists() and p.stat().st_size > 0:
            print(f"[PASS] {label}: {rel}")
        else:
            warnings.append(f"[WARN] {label} 不存在或为空: {rel}")

    # manifest 必需字段
    mp = proj / "manifest.json"
    if mp.exists():
        m = json.loads(mp.read_text(encoding="utf-8-sig"))
        for key in ["report_id", "title", "status"]:
            if key not in m:
                errors.append(f"[FAIL] manifest.json 缺少字段: {key}")

    _summary(errors, warnings); return 1 if errors else 0


def _summary(errors, warnings):
    print("\n" + "=" * 70); print("错误: %d, 警告: %d" % (len(errors), len(warnings)))
    for e in errors: print(e)
    for w in warnings: print(w)
    print("【结果】未通过" if errors else "【结果】通过 — 所有必需产物就绪")


def main():
    if len(sys.argv) < 2:
        print("Usage: python quality_gate_check.py {report_id_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(check(sys.argv[1]))


if __name__ == "__main__":
    main()
