#!/usr/bin/env python3
"""
Step 3 门禁检查 — 时序 CTA 策略逻辑抽取（开仓 / 止损 / 止盈 三要素）

Usage:
    python check_strategy_logic.py {report_id_dir}

检查项：
    1. 02_strategy_logic/strategy_summary.md 存在且非空
    2. strategy_summary.md 包含：研究问题/结论、资产池、周期、开仓、止损、止盈、参数、假设
    3. 02_strategy_logic/reference_implementation.py 存在、非空、有函数定义
    4. 参考实现含方向(direction)与参数逻辑

Exit codes:
    0 — 通过
    1 — 存在错误
"""

import sys
import os
import re
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check_strategy_logic(project_dir):
    errors = []
    warnings = []

    doc_path = Path(project_dir) / "02_strategy_logic" / "strategy_summary.md"
    code_path = Path(project_dir) / "02_strategy_logic" / "reference_implementation.py"

    print("=" * 70)
    print("Step 3 门禁检查 — 策略逻辑抽取（开仓/止损/止盈）")
    print("=" * 70)

    # 1. strategy_summary.md
    if not doc_path.exists():
        errors.append("[FAIL] 02_strategy_logic/strategy_summary.md 不存在")
    else:
        size = doc_path.stat().st_size
        if size < 800:
            errors.append(f"[FAIL] 策略文档过短 ({size} bytes)")
        else:
            print(f"[PASS] 策略文档存在 ({size} bytes)")

        doc = doc_path.read_text(encoding="utf-8")
        checks = [
            ("原文思路/原理", [r"原文思路", r"设计目的", r"原理", r"立论", r"为什么"]),
            ("研究问题/结论", [r"研究问题", r"结论", r"Research", r"Conclusion", r"目标"]),
            ("资产池", [r"品种", r"资产", r"universe", r"标的", r"期货", r"ETF"]),
            ("周期/频率", [r"周期", r"频率", r"日频", r"周频", r"rebalance", r"窗口", r"bar"]),
            ("regime/市场状态", [r"市场状态", r"regime", r"趋势.*震荡", r"门控", r"TSI", r"Hurst"]),
            ("开仓规则", [r"开仓", r"入场", r"entry", r"买入", r"做空", r"金叉", r"突破", r"信号"]),
            ("止损规则", [r"止损", r"stop.?loss", r"ATR", r"移动止损", r"吊灯", r"固定百分"]),
            ("止盈/退出规则", [r"止盈", r"退出", r"平仓", r"exit", r"take.?profit", r"移动止盈", r"时间退出", r"证伪"]),
            ("仓位控制", [r"仓位", r"position", r"满仓", r"vol.?target", r"等手数", r"风险平价", r"Kelly"]),
            ("参数", [r"参数", r"param", r"窗口", r"倍数", r"阈值", r"k\s*=", r"窗口长度"]),
            ("参数优化", [r"参数优化", r"网格", r"贝叶斯", r"walk.?forward.*优化", r"optimization", r"搜索空间"]),
            ("假设/风控", [r"假设", r"assumption", r"成本", r"滑点", r"保证金", r"手续费", r"杠杆"]),
            ("参考文档", [r"参考文档", r"参考文献", r"引用", r"论文", r"Moskowitz", r"Levine", r"文献"]),
        ]
        for name, keywords in checks:
            if any(re.search(kw, doc, re.IGNORECASE) for kw in keywords):
                print(f"[PASS] 文档包含: {name}")
            else:
                errors.append(f"[FAIL] 文档缺少: {name} (关键词: {keywords})")

    # 2. reference_implementation.py
    print("\n--- reference_implementation.py 检查 ---")
    if not code_path.exists():
        errors.append(
            "[FAIL] 02_strategy_logic/reference_implementation.py 不存在。"
            "必须包含可审计的信号生成代码（读 OHLC → 开仓/止损/止盈 → direction）。"
        )
    else:
        size = code_path.stat().st_size
        if size < 400:
            errors.append(f"[FAIL] 参考实现过短 ({size} bytes)，疑似空文件")
        else:
            print(f"[PASS] 参考实现存在 ({size} bytes)")

        code = code_path.read_text(encoding="utf-8")
        func_count = len(re.findall(r'def\s+\w+\s*\(', code))
        if func_count < 1:
            errors.append("[FAIL] 参考实现无函数定义")
        else:
            print(f"[PASS] 参考实现包含 {func_count} 个函数定义")

        # 三要素函数（常见命名）
        elem_funcs = re.findall(
            r'def\s+(entry|signal|open_position|stop_loss|stop|take_profit|exit|update_signal|on_bar)\w*',
            code, re.IGNORECASE)
        if elem_funcs:
            print(f"[PASS] 发现策略要素函数: {sorted(set(elem_funcs))}")
        else:
            warnings.append("[WARN] 未发现标准命名的开仓/止损/止盈函数，确认函数名表意清晰")

        if "direction" in code or "long" in code.lower() or "short" in code.lower():
            print("[PASS] 参考实现包含多空方向逻辑")
        else:
            warnings.append("[WARN] 参考实现未找到方向(direction/long/short)逻辑")

        if re.search(r'THRESHOLD|PARAMS|params|window|WINDOW|multiplier', code):
            print("[PASS] 参考实现包含参数定义")
        else:
            warnings.append("[WARN] 参考实现中未发现参数定义")

    print_summary(errors, warnings)
    return 1 if errors else 0


def print_summary(errors, warnings):
    print("\n" + "=" * 70)
    print("检查汇总")
    print("=" * 70)
    for e in errors:
        print(e)
    for w in warnings:
        print(w)
    print(f"\n错误: {len(errors)}, 警告: {len(warnings)}")
    if errors:
        print("【结果】未通过 — 策略三要素抽取不符合要求。必须修复后重新检查。")
    elif warnings:
        print("【结果】有条件通过 — 建议修复警告项。")
    else:
        print("【结果】通过 — 策略逻辑抽取合格。")


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_strategy_logic.py {report_id_dir}")
        sys.exit(1)
    project_dir = sys.argv[1]
    if not os.path.exists(project_dir):
        print(f"错误: 目录不存在: {project_dir}")
        sys.exit(1)
    sys.exit(check_strategy_logic(project_dir))


if __name__ == "__main__":
    main()
