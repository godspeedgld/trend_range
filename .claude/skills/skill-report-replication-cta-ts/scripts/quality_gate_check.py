#!/usr/bin/env python3
"""
Quality Gate — 时序 CTA 研报复现交付前检查（cta-ts 4 目录）

Usage: python quality_gate_check.py {report_id_dir}
检查：目录结构 / 强制产出物 / manifest / signal_log 格式。
Exit: 0 通过(或仅警告) / 1 有错误
"""
import sys, os, json, io
from pathlib import Path
from datetime import datetime
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class Colors:
    R, G, Y, C = "\033[91m", "\033[92m", "\033[93m", "\033[96m"
    X = "\033[0m"


def header(t): print(f"\n{Colors.C}{'='*70}{Colors.X}\n{Colors.C}{t}{Colors.X}\n{Colors.C}{'='*70}{Colors.X}")


class Q:
    def __init__(self, d):
        self.d = Path(d).resolve(); self.errors = []; self.warns = []; self.passes = 0
    def err(self, m): self.errors.append(m); print(f"  {Colors.R}[FAIL]{Colors.X} {m}")
    def warn(self, m): self.warns.append(m); print(f"  {Colors.Y}[WARN]{Colors.X} {m}")
    def ok(self, m): self.passes += 1; print(f"  {Colors.G}[PASS]{Colors.X} {m}")

    def dirs(self):
        header("Check 1: 目录结构")
        for dd in ["01_translation", "02_approach", "03_backtest_strategy",
                   "03_backtest_strategy/backtest_logs", "04_delivery"]:
            (self.ok if (self.d / dd).is_dir() else self.err)(f"目录{'存在' if (self.d/dd).is_dir() else '缺失'}: {dd}/")

    def files(self):
        header("Check 2: 强制产出物")
        req = [
            "02_approach/main_approach.md",                       # headline
            "03_backtest_strategy/backtest_features.md",
            "03_backtest_strategy/reference_implementation.py",
            "03_backtest_strategy/strategy.py",
            "03_backtest_strategy/config.json",
            "03_backtest_strategy/backtest_report.html",
            "03_backtest_strategy/backtest_logs/equity_curve.csv",
            "03_backtest_strategy/backtest_logs/performance_metrics.csv",
            "03_backtest_strategy/backtest_logs/signal_log.jsonl",
            "manifest.json",
        ]
        for f in req:
            p = self.d / f
            if p.is_file() and p.stat().st_size > 0:
                self.ok(f"文件存在 ({p.stat().st_size} bytes): {f}")
            else:
                self.err(f"文件缺失/为空: {f}")
        # translation 可选（仅英文研报必需）
        if (self.d / "01_translation/full_translation.md").is_file():
            self.ok("translation 存在（英文研报）")
        # final_report 或 failure_report 至少一个
        if (self.d / "04_delivery/final_report.md").is_file() or (self.d / "failure_report.md").is_file():
            self.ok("final_report.md 或 failure_report.md 至少一个")
        else:
            self.err("final_report.md 和 failure_report.md 都不存在")

    def manifest(self):
        header("Check 3: manifest.json")
        mp = self.d / "manifest.json"
        if not mp.exists():
            self.err("manifest.json 不存在"); return
        try:
            m = json.loads(mp.read_text(encoding="utf-8-sig"))
        except Exception as e:
            self.err(f"manifest 解析失败: {e}"); return
        for k in ["report_id", "title", "data_sources", "run_history", "artifacts"]:
            (self.ok if k in m else self.err)(f"manifest {'含' if k in m else '缺'}键: {k}")
        if m.get("run_history"):
            self.ok(f"run_history 记录数: {len(m['run_history'])}")
        else:
            self.warn("run_history 为空（回测可能未跑）")

    def signal_log(self):
        header("Check 4: signal_log.jsonl 格式（引擎产出的实现方向）")
        lp = self.d / "03_backtest_strategy/backtest_logs/signal_log.jsonl"
        if not lp.exists():
            self.err("signal_log.jsonl 不存在"); return
        lines = lp.read_text(encoding="utf-8-sig").splitlines()
        if not lines:
            self.err("signal_log.jsonl 为空"); return
        self.ok(f"signal_log 行数: {len(lines)}")
        valid = 0
        for i, line in enumerate(lines[:10]):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "date" in rec and "signals" in rec:
                    valid += 1
                else:
                    self.err(f"第 {i+1} 行缺 date/signals")
            except json.JSONDecodeError as e:
                self.err(f"第 {i+1} 行 JSON 错误: {e}")
        if valid:
            self.ok(f"格式正确: {valid}/{min(10, len(lines))} 行")

    def run(self):
        print(f"\n{Colors.C}Quality Gate (cta-ts) for: {self.d}{Colors.X}")
        print(f"{Colors.C}时间: {datetime.now().isoformat()}{Colors.X}")
        self.dirs(); self.files(); self.manifest(); self.signal_log()
        header("汇总")
        print(f"  通过 {self.passes}  警告 {len(self.warns)}  错误 {len(self.errors)}")
        if self.errors:
            print(f"\n{Colors.R}【结果】未通过 — {len(self.errors)} 错误，修复后才能交付。{Colors.X}"); return 1
        if self.warns:
            print(f"\n{Colors.Y}【结果】有条件通过 — {len(self.warns)} 警告。{Colors.X}"); return 0
        print(f"\n{Colors.G}【结果】全部通过 — 可以交付。{Colors.X}"); return 0


def main():
    if len(sys.argv) < 2:
        print("Usage: python quality_gate_check.py {report_id_dir}"); sys.exit(1)
    if not os.path.exists(sys.argv[1]):
        print(f"错误: 目录不存在: {sys.argv[1]}"); sys.exit(1)
    sys.exit(Q(sys.argv[1]).run())


if __name__ == "__main__":
    main()
