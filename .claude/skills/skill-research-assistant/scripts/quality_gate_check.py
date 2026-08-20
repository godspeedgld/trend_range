#!/usr/bin/env python
"""质量控制 — 检查工程产物完整性。

数据分析（analysis_XXX）：records.md + analysis.py + result_view.html
策略迭代（strategy_XXX）：main_idea.md + backtest_strategy/ + final_report.md
最终：04_delivery/final_report.md + manifest.json
"""
import sys, os, io, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    proj = Path(project_dir)
    print("=" * 70); print("质量控制 — 产物完整性"); print("=" * 70)

    # 数据分析
    da = proj / "01_data_analysis"
    analysis_dirs = sorted([d for d in da.iterdir() if d.is_dir()]) if da.exists() else []
    if not analysis_dirs:
        warnings.append("[WARN] 无数据分析（01_data_analysis 为空）")
    else:
        print(f"[PASS] 数据分析 {len(analysis_dirs)} 个: {', '.join(d.name for d in analysis_dirs)}")
        for d in analysis_dirs:
            for rel, label in [("records.md", "分析记录"), ("analysis.py", "分析代码"),
                               ("result_view.html", "可视化")]:
                p = d / rel
                if not p.exists() or p.stat().st_size == 0:
                    errors.append(f"[FAIL] {label} 缺失: {d.name}/{rel}")
                else:
                    print(f"[PASS] {label}: {d.name}/{rel}")

    # 策略迭代
    si = proj / "02_strategy_iteration"
    strat_dirs = sorted([d for d in si.iterdir() if d.is_dir()]) if si.exists() else []
    if not strat_dirs:
        warnings.append("[WARN] 无策略迭代（02_strategy_iteration 为空）")
    else:
        print(f"[PASS] 策略迭代 {len(strat_dirs)} 个: {', '.join(d.name for d in strat_dirs)}")
        for d in strat_dirs:
            for rel, label in [("main_idea.md", "策略思路"), ("final_report.md", "策略报告"),
                               ("backtest_strategy/backtest_report.html", "回测报告"),
                               ("backtest_strategy/config.json", "回测配置")]:
                p = d / rel
                if not p.exists() or p.stat().st_size == 0:
                    errors.append(f"[FAIL] {label} 缺失: {d.name}/{rel}")
                else:
                    print(f"[PASS] {label}: {d.name}/{rel}")

    # 最终报告 + manifest
    fr = proj / "04_delivery" / "final_report.md"
    if not fr.exists() or fr.stat().st_size == 0:
        warnings.append("[WARN] 最终报告缺失（04_delivery/final_report.md，非必须）")
    else:
        print(f"[PASS] 最终报告: ({fr.stat().st_size} bytes)")

    mp = proj / "manifest.json"
    if not mp.exists():
        errors.append("[FAIL] manifest.json 缺失")
    else:
        m = json.loads(mp.read_text(encoding="utf-8-sig"))
        dc = m.get("data_check", {})
        if dc.get("status") == "missing":
            errors.append(f"[FAIL] 数据检查未通过，缺失: {dc.get('missing')}")
        else:
            print("[PASS] manifest 数据检查状态:", dc.get("status"))

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
