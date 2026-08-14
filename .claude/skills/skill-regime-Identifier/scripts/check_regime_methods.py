#!/usr/bin/env python3
"""Step 4 门禁 — Regime 方法提取检查"""
import sys, os, re, io, ast
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def check(project_dir):
    errors, warnings = [], []
    regime_dir = Path(project_dir) / "03_regime_analysis"
    print("=" * 70); print("Step 4 门禁 — Regime 方法提取"); print("=" * 70)

    # 检查 regime_methods.md
    md_path = regime_dir / "regime_methods.md"
    if not md_path.exists():
        errors.append("[FAIL] regime_methods.md 不存在")
    else:
        size = md_path.stat().st_size
        doc = md_path.read_text(encoding="utf-8")
        print(f"[PASS] regime_methods.md 存在 ({size} bytes)")
        for name, kws in [
            ("方法/划分逻辑", [r"方法", r"划分", r"趋势", r"震荡", r"阈值"]),
            ("公式", [r"公式", r"=", r"\\[", r"formula"]),
            ("参数", [r"参数", r"窗口", r"阈值", r"period", r"thresh"]),
        ]:
            if any(re.search(k, doc, re.IGNORECASE) for k in kws):
                print(f"[PASS] 包含: {name}")
            else:
                errors.append(f"[FAIL] regime_methods.md 缺少: {name}")

    # 检查 regime_impl.py
    impl_path = regime_dir / "regime_impl.py"
    if not impl_path.exists():
        errors.append("[FAIL] regime_impl.py 不存在")
    else:
        src = impl_path.read_text(encoding="utf-8")
        print(f"[PASS] regime_impl.py 存在 ({impl_path.stat().st_size} bytes)")
        if "classify_regime" not in src:
            errors.append("[FAIL] regime_impl.py 缺少 classify_regime 函数")
        else:
            print("[PASS] classify_regime 函数定义存在")
        # 检查 PARAMS
        if "PARAMS" in src:
            print("[PASS] PARAMS 字典存在")
        else:
            warnings.append("[WARN] 未找到 PARAMS 字典")

    # 检查 data_params.json
    dp_path = regime_dir / "data_params.json"
    if not dp_path.exists():
        warnings.append("[WARN] data_params.json 不存在（建议生成）")
    else:
        print(f"[PASS] data_params.json 存在")

    _summary(errors, warnings); return 1 if errors else 0


def _summary(errors, warnings):
    print("\n" + "=" * 70); print("错误: %d, 警告: %d" % (len(errors), len(warnings)))
    for e in errors: print(e)
    for w in warnings: print(w)
    print("【结果】未通过" if errors else "【结果】通过")


def main():
    if len(sys.argv) < 2:
        print("Usage: python check_regime_methods.py {report_id_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(check(sys.argv[1]))


if __name__ == "__main__":
    main()
