#!/usr/bin/env python3
"""
Step 4 门禁 — 回测特征提取检查（backtest_features.md + reference_implementation.py）

Usage: python check_strategy.py {report_id_dir}
检查：backtest_features.md 含 regime/开仓/止盈止损/开平仓逻辑/风控 + 文字+代码；reference_implementation.py 有函数+方向+参数。
Exit: 0 通过 / 1 有错误
"""
import sys, os, re, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    feat = Path(project_dir) / "03_backtest_strategy" / "backtest_features.md"
    impl = Path(project_dir) / "03_backtest_strategy" / "reference_implementation.py"
    print("=" * 70); print("Step 4 门禁 — 回测特征提取"); print("=" * 70)

    if not feat.exists():
        errors.append("[FAIL] 03_backtest_strategy/backtest_features.md 不存在")
    else:
        size = feat.stat().st_size
        if size < 800:
            errors.append(f"[FAIL] backtest_features.md 过短 ({size} bytes)")
        else:
            print(f"[PASS] backtest_features.md 存在 ({size} bytes)")
        doc = feat.read_text(encoding="utf-8")
        checks = [
            ("regime 判断", [r"regime", r"市场状态", r"门控", r"默认.*无"]),
            ("开仓信号", [r"开仓", r"入场", r"entry", r"信号", r"双均线", r"默认.*双均线"]),
            ("止盈止损", [r"止盈", r"止损", r"ATR", r"吊灯", r"默认.*ATR"]),
            ("开平仓逻辑", [r"开仓", r"平仓", r"反手", r"空仓", r"多仓", r"反向信号"]),
            ("风控/仓位", [r"仓位", r"风控", r"满仓", r"vol.?target", r"保证金", r"成本"]),
            ("文字+代码", [r"代码", r"def\s", r"```", r"可执行", r"build_strategy"]),
        ]
        for name, kws in checks:
            if any(re.search(k, doc, re.IGNORECASE) for k in kws):
                print(f"[PASS] 包含: {name}")
            else:
                errors.append(f"[FAIL] 缺少: {name} (关键词 {kws})")

    if not impl.exists():
        errors.append("[FAIL] 03_backtest_strategy/reference_implementation.py 不存在")
    else:
        code = impl.read_text(encoding="utf-8")
        if len(code) < 300:
            errors.append(f"[FAIL] reference_implementation.py 过短 ({len(code)} bytes)")
        else:
            print(f"[PASS] reference_implementation.py 存在 ({len(code)} bytes)")
        fns = re.findall(r'def\s+\w+\s*\(', code)
        if not fns:
            errors.append("[FAIL] reference_implementation.py 无函数定义")
        else:
            print(f"[PASS] 函数定义 {len(fns)} 个")
        if not re.search(r'direction|long|short|entry|signal', code, re.IGNORECASE):
            warnings.append("[WARN] reference_implementation.py 未找到方向/信号逻辑")
        if not re.search(r'THRESHOLD|PARAMS|params|window|period|k\s*=', code):
            warnings.append("[WARN] reference_implementation.py 未发现参数定义")

    print("\n" + "=" * 70)
    print("错误: %d, 警告: %d" % (len(errors), len(warnings)))
    for e in errors: print(e)
    for w in warnings: print(w)
    print("【结果】未通过 — 回测特征不合格" if errors else "【结果】通过 — 回测特征合格")
    return 1 if errors else 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_strategy.py {report_id_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(check(sys.argv[1]))


if __name__ == "__main__":
    main()
