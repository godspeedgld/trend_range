#!/usr/bin/env python3
"""
Step 3 门禁 — 量化方法提取检查（main_approach.md）

Usage: python check_approach.py {report_id_dir}
检查：taxonomy 大类、每方法 5 部分（思路/原理/公式/优缺点）、衍生方法、参考资料、未来探索。
Exit: 0 通过 / 1 有错误
"""
import sys, os, re, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    doc_path = Path(project_dir) / "02_approach" / "main_approach.md"
    print("=" * 70); print("Step 3 门禁 — 量化方法提取（main_approach.md）"); print("=" * 70)
    if not doc_path.exists():
        errors.append("[FAIL] 02_approach/main_approach.md 不存在（这是本技能的头条产出）")
        _summary(errors, warnings); return 1
    size = doc_path.stat().st_size
    if size < 1500:
        errors.append(f"[FAIL] main_approach.md 过短 ({size} bytes)，方法提取不充分")
    else:
        print(f"[PASS] main_approach.md 存在 ({size} bytes)")
    doc = doc_path.read_text(encoding="utf-8")
    checks = [
        ("regime 判断类", [r"regime", r"市场状态", r"趋势.*震荡", r"TSI", r"Hurst"]),
        ("指标分析类", [r"均线", r"动量", r"MACD", r"Kalman", r"指标", r"滤波"]),
        ("多指标融合", [r"融合", r"共振", r"打分", r"自适应", r"Kaufman"]),
        ("止盈止损类", [r"止盈", r"止损", r"ATR", r"吊灯", r"退出"]),
        ("风险控制类", [r"风控", r"仓位", r"vol.?target", r"目标波动", r"熔断"]),
        ("文中思路总结", [r"思路", r"叙述", r"原文", r"文中"]),
        ("方法原理分析", [r"原理", r"经济.*含义", r"统计学", r"为什么"]),
        ("公式提取", [r"公式", r"=", r"\\[", r"\\(", r"formula"]),
        ("优缺点", [r"优点", r"缺点", r"延迟", r"抗噪", r"敏感", r"不足"]),
        ("衍生方法", [r"衍生", r"替代", r"未采用", r"马尔科夫", r"提及"]),
        ("参考资料", [r"参考", r"文献", r"引用", r"论文", r"et al", r"\\d{4}"]),
        ("未来探索", [r"未来", r"展望", r"下一步", r"探索", r"改进"]),
    ]
    for name, kws in checks:
        if any(re.search(k, doc, re.IGNORECASE) for k in kws):
            print(f"[PASS] 包含: {name}")
        else:
            errors.append(f"[FAIL] 缺少: {name} (关键词 {kws})")
    _summary(errors, warnings); return 1 if errors else 0


def _summary(errors, warnings):
    print("\n" + "=" * 70); print("错误: %d, 警告: %d" % (len(errors), len(warnings)))
    for e in errors: print(e)
    print("【结果】未通过 — 方法提取不合格" if errors else "【结果】通过 — 方法提取合格")


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_approach.py {report_id_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(check(sys.argv[1]))


if __name__ == "__main__":
    main()
