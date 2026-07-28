#!/usr/bin/env python3
"""
Quality Gate Check Script — 时序 CTA 研报复现交付前自动检查

Usage:
    python quality_gate_check.py /home/coder/project/replication/report-replication/{report_id}

检查项：
    1. 目录结构完整性
    2. 强制产出物存在性（文件级别）
    3. HTML 评估报告标准章节结构（TSCTA 口径，无因子验证）
    4. 图表数量和命名规范
    5. 数据文件完整性
    6. manifest.json 完整性 + 诚实性
    7. signal_log.jsonl 格式检查

Exit codes:
    0 — 全部通过（或仅有警告）
    1 — 存在错误
"""

import sys
import os
import json
import re
import io
import csv
from pathlib import Path
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


class Colors:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    RESET = "\033[0m"


def print_header(title):
    print(f"\n{Colors.CYAN}{'='*70}{Colors.RESET}")
    print(f"{Colors.CYAN}{title}{Colors.RESET}")
    print(f"{Colors.CYAN}{'='*70}{Colors.RESET}")


def print_pass(msg): print(f"  {Colors.GREEN}[PASS]{Colors.RESET} {msg}")
def print_fail(msg): print(f"  {Colors.RED}[FAIL]{Colors.RESET} {msg}")
def print_warn(msg): print(f"  {Colors.YELLOW}[WARN]{Colors.RESET} {msg}")
def print_info(msg): print(f"  {Colors.CYAN}[INFO]{Colors.RESET} {msg}")


class QualityGateChecker:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir).resolve()
        self.report_id = self.project_dir.name
        self.errors = []
        self.warnings = []
        self.infos = []
        self.passes = 0

    def error(self, msg):
        self.errors.append(msg); print_fail(msg)

    def warn(self, msg):
        self.warnings.append(msg); print_warn(msg)

    def info(self, msg):
        self.infos.append(msg); print_info(msg)

    def pass_(self, msg):
        self.passes += 1; print_pass(msg)

    # ── Check 1: 目录结构 ────────────────────────────────
    def check_directory_structure(self):
        print_header("Check 1: 目录结构完整性")
        required_dirs = [
            "01_translation",
            "02_strategy_logic",
            "03_strategy_evaluation",
            "03_strategy_evaluation/data",
            "03_strategy_evaluation/charts",
            "04_backtest_strategy",
            "04_backtest_strategy/backtest_logs",
            "06_delivery",
        ]
        for d in required_dirs:
            full = self.project_dir / d
            if full.exists() and full.is_dir():
                self.pass_(f"目录存在: {d}/")
            else:
                self.error(f"目录缺失: {d}/")

    # ── Check 2: 强制文件清单 ────────────────────────────
    def check_required_files(self):
        print_header("Check 2: 强制产出物存在性")
        required_files = [
            # Step 2~3
            "01_translation/full_translation.md",
            "02_strategy_logic/strategy_summary.md",
            "02_strategy_logic/reference_implementation.py",
            # Step 5: 评估报告 + data
            "03_strategy_evaluation/evaluation_report.html",
            "03_strategy_evaluation/data/direction_matrix_from_strategy.csv",
            "03_strategy_evaluation/data/portfolio_returns_dir_full.csv",
            "03_strategy_evaluation/data/benchmark_comparison.csv",
            "03_strategy_evaluation/data/backtest_alignment_audit.csv",
            # Step 4: 策略 + 回测
            "04_backtest_strategy/strategy.py",
            "04_backtest_strategy/config.json",
            "04_backtest_strategy/backtest_report.html",
            "04_backtest_strategy/backtest_logs/signal_log.jsonl",
            "04_backtest_strategy/backtest_logs/equity_curve.csv",
            "04_backtest_strategy/backtest_logs/performance_metrics.csv",
            "04_backtest_strategy/backtest_logs/trades.csv",
            "manifest.json",
        ]
        for f in required_files:
            full = self.project_dir / f
            if full.exists() and full.is_file():
                size = full.stat().st_size
                if size == 0:
                    self.error(f"文件为空: {f}")
                else:
                    self.pass_(f"文件存在 ({size} bytes): {f}")
            else:
                self.error(f"文件缺失: {f}")

        has_failure = (self.project_dir / "failure_report.md").exists()
        has_summary = (self.project_dir / "06_delivery/final_delivery_summary.md").exists()
        if has_failure or has_summary:
            self.pass_("failure_report.md 或 final_delivery_summary.md 至少存在一个")
            for p in ["failure_report.md", "06_delivery/final_delivery_summary.md"]:
                if (self.project_dir / p).exists() and (self.project_dir / p).stat().st_size == 0:
                    self.error(f"{p} 为空")
        else:
            self.error("failure_report.md 和 final_delivery_summary.md 都不存在")

    # ── Check 3: HTML 评估报告结构 ───────────────────────
    def check_html_report_structure(self):
        print_header("Check 3: HTML 评估报告章节结构（TSCTA 口径）")
        html_path = self.project_dir / "03_strategy_evaluation/evaluation_report.html"
        if not html_path.exists():
            self.error("evaluation_report.html 不存在，跳过 HTML 结构检查")
            return
        try:
            html_content = html_path.read_text(encoding="utf-8-sig")
        except Exception as e:
            self.error(f"无法读取 HTML 报告: {e}")
            return

        size = len(html_content)
        if size < 10000:
            self.warn(f"HTML 报告过小 ({size} bytes)，可能内容不完整")
        else:
            self.pass_(f"HTML 报告大小: {size} bytes")

        img_count = html_content.count("data:image/png;base64,")
        if img_count < 3:
            self.error(f"HTML 内嵌图表数量不足: {img_count} < 3")
        else:
            self.pass_(f"HTML 内嵌图表: {img_count} 张")

        explanation_markers = [
            "How To Read", "阅读指南", "metric dictionary", "指标字典",
            "chart-note", "怎么看", "本图解读", "这张图回答什么",
        ]
        if any(m in html_content for m in explanation_markers):
            self.pass_("HTML 包含阅读指南/图表解释层")
        else:
            self.error("HTML 缺少阅读指南或图表解释层")

        chart_note_count = html_content.count('class="chart-note"') + html_content.count("class='chart-note'")
        if chart_note_count < img_count:
            self.error(f"图表解释块数量不足: {chart_note_count}，图表数: {img_count}")
        else:
            self.pass_(f"图表解释块数量: {chart_note_count}")

        # TSCTA 关键指标（非 IC/分位）
        required_metric_terms = ["Sharpe", "Calmar", "Max DD", "NAV", "开仓", "止损", "止盈"]
        missing = [t for t in required_metric_terms if t not in html_content]
        if missing:
            self.warn(f"指标/要素解释可能不完整，缺少关键词: {missing}")
        else:
            self.pass_("TSCTA 关键指标/三要素术语已覆盖")

        robustness_markers = {
            "RAG 打分卡": ["RAG Scorecard", "红黄绿", "打分卡"],
            "基准对照": ["Benchmark Comparison", "基准对照", "buy_hold", "buy-hold", "买入持有"],
            "口径/已知局限": ["口径差异", "已知局限", "alignment", "limitation"],
        }
        for name, markers in robustness_markers.items():
            if any(m in html_content for m in markers):
                self.pass_(f"HTML 包含{name}")
            else:
                self.error(f"HTML 缺少{name}")

        blocker_terms = ["QUALITY_GATE_BLOCKER", "requires review", "scorecard_missing",
                         "benchmark_comparison_missing"]
        found = [t for t in blocker_terms if t in html_content]
        if found:
            self.error(f"HTML 仍包含占位/阻塞内容: {found}")

        # TSCTA 标准章节
        required_sections = [
            ("报告头", [r"评估报告", r"策略评估", r"时序\s*CTA", r"Trend"]),
            ("策略逻辑/三要素", [r"开仓", r"止损", r"止盈", r"Entry", r"Stop"]),
            ("数据说明", [r"数据", r"Data", r"品种", r"周期"]),
            ("净值/NAV", [r"NAV", r"净值", r"净值曲线"]),
            ("回撤", [r"回撤", r"Drawdown", r"最大回撤"]),
            ("市场状态/regime", [r"市场状态", r"regime", r"趋势.*震荡", r"分 regime"]),
            ("基准对照", [r"基准", r"Benchmark", r"买入持有", r"恒空仓"]),
            ("结论", [r"结论", r"Conclusion"]),
        ]
        for name, keywords in required_sections:
            if any(re.search(kw, html_content, re.IGNORECASE) for kw in keywords):
                self.pass_(f"章节存在: {name}")
            else:
                self.error(f"章节缺失: {name} (关键词: {keywords})")

        honesty_keywords = [r"数据不足", r"未执行", r"未计算", r"无法判断", r"inconclusive", r"已知局限"]
        if any(re.search(kw, html_content, re.IGNORECASE) for kw in honesty_keywords):
            self.pass_("报告包含诚实性声明")
        else:
            self.warn("未找到诚实性声明关键词（全部执行完成则正常）")

    # ── Check 4: 图表 ────────────────────────────────────
    def check_charts(self):
        print_header("Check 4: 图表文件清单")
        charts_dir = self.project_dir / "03_strategy_evaluation/charts"
        if not charts_dir.exists():
            self.error("charts/ 目录不存在")
            return
        required_charts = {
            "01_nav.png": "净值曲线",
            "02_drawdown.png": "回撤",
            "03_regime_nav.png": "分市场状态净值",
            "04_benchmark_nav.png": "基准对照净值",
        }
        for fn, desc in required_charts.items():
            full = charts_dir / fn
            if full.exists():
                self.pass_(f"图表存在 ({full.stat().st_size} bytes): {fn} ({desc})")
            else:
                self.error(f"图表缺失: {fn} ({desc})")
        optional_charts = {
            "05_yearly_return.png": "逐年收益",
            "06_rolling_sharpe.png": "滚动 Sharpe",
            "07_cost_sensitivity.png": "成本敏感性",
            "08_walkforward.png": "Walk-forward",
        }
        for fn, desc in optional_charts.items():
            full = charts_dir / fn
            if full.exists():
                self.pass_(f"可选图表存在: {fn} ({desc})")
            else:
                self.warn(f"可选图表缺失: {fn} ({desc})")
        all_charts = list(charts_dir.glob("*.png"))
        bad = [c.name for c in all_charts if " " in c.name or any(ord(ch) > 127 for ch in c.name)]
        if bad:
            self.error(f"图表命名不规范（含中文或空格）: {bad}")
        else:
            self.pass_("图表命名规范（英文小写+下划线）")
        numbered = [c.name for c in all_charts if re.match(r"^\d{2}_", c.name)]
        if len(numbered) >= 4:
            self.pass_(f"图表编号规范: {len(numbered)} 张使用 01_ 前缀")
        else:
            self.warn(f"图表编号不规范: 仅 {len(numbered)} 张使用 01_ 前缀")

    # ── Check 5: 数据文件 ────────────────────────────────
    def check_data_files(self):
        print_header("Check 5: 数据文件完整性")
        data_dir = self.project_dir / "03_strategy_evaluation/data"
        if not data_dir.exists():
            self.error("data/ 目录不存在")
            return
        csv_files = [
            "direction_matrix_from_strategy.csv",
            "portfolio_returns_dir_full.csv",
            "benchmark_comparison.csv",
            "backtest_alignment_audit.csv",
        ]
        for name in csv_files:
            p = data_dir / name
            if not p.exists():
                self.error(f"CSV 缺失: {name}")
                continue
            try:
                lines = p.read_text(encoding="utf-8-sig").splitlines()
            except Exception as e:
                self.error(f"无法读取 {name}: {e}")
                continue
            if len(lines) < 2:
                self.error(f"CSV 无数据行: {name}")
            elif len(lines) < 5:
                self.warn(f"CSV 数据行过少: {name} ({len(lines)} 行)")
            else:
                self.pass_(f"CSV 数据完整: {name} ({len(lines)} 行)")
        self.check_benchmark_csv(data_dir / "benchmark_comparison.csv")

    def check_benchmark_csv(self, csv_path):
        if not csv_path.exists():
            return
        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except Exception as e:
            self.error(f"无法解析 benchmark_comparison.csv: {e}")
            return
        if len(rows) < 2:
            self.error("benchmark_comparison.csv 缺少数据行")
            return
        text = " ".join(",".join(str(c).strip().lower() for c in row) for row in rows[:200])
        # TSCTA 必需基准：买入持有 + 恒空仓（反向/随机因子属截面概念，不强求）
        required = {
            "buy_hold": ["buy_hold", "buy-hold", "买入持有", "equal_weight", "等权"],
            "zero_return": ["zero_return", "always_flat", "恒空仓", "零收益", "flat"],
        }
        missing = [n for n, toks in required.items() if not any(t in text for t in toks)]
        if missing:
            self.error(f"benchmark_comparison.csv 缺少必需基准: {missing}")
        else:
            self.pass_("benchmark_comparison.csv 覆盖必需基准（买入持有/恒空仓）")
        numeric = 0
        for row in rows[1:]:
            for cell in row[1:]:
                try:
                    float(str(cell).strip()); numeric += 1
                except ValueError:
                    pass
        if numeric == 0:
            self.error("benchmark_comparison.csv 无可解析数值")
        else:
            self.pass_(f"benchmark_comparison.csv 含数值: {numeric} cells")

    # ── Check 6: manifest ────────────────────────────────
    def check_manifest(self):
        print_header("Check 6: manifest.json 完整性")
        mp = self.project_dir / "manifest.json"
        if not mp.exists():
            self.error("manifest.json 不存在")
            return
        try:
            manifest = json.loads(mp.read_text(encoding="utf-8-sig"))
        except Exception as e:
            self.error(f"manifest.json 解析失败: {e}")
            return
        required_keys = ["report_id", "title", "data_sources", "parameters", "run_history", "artifacts"]
        for k in required_keys:
            if k in manifest:
                self.pass_(f"manifest.json 包含键: {k}")
            else:
                self.error(f"manifest.json 缺失键: {k}")
        qc = manifest.get("quality_control", {})
        if qc.get("incident"):
            self.pass_(f"manifest.json 记录质量事件: {qc.get('incident')}")
        elif "quality_control" not in manifest:
            self.warn("manifest.json 缺少 quality_control 字段")
        rh = manifest.get("run_history", [])
        if len(rh) > 0:
            self.pass_(f"manifest.json run_history 记录数: {len(rh)}")
        else:
            self.warn("manifest.json run_history 为空")

    # ── Check 7: signal_log ──────────────────────────────
    def check_signal_log(self):
        print_header("Check 7: signal_log.jsonl 格式检查")
        lp = self.project_dir / "04_backtest_strategy/backtest_logs/signal_log.jsonl"
        if not lp.exists():
            self.error("signal_log.jsonl 不存在")
            return
        try:
            lines = lp.read_text(encoding="utf-8-sig").splitlines()
        except Exception as e:
            self.error(f"无法读取 signal_log.jsonl: {e}")
            return
        if not lines:
            self.error("signal_log.jsonl 为空")
            return
        self.pass_(f"signal_log.jsonl 行数: {len(lines)}")
        valid = 0
        sample = None
        for i, line in enumerate(lines[:10]):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if "date" in rec and "signals" in rec:
                    valid += 1
                    if sample is None:
                        sample = rec
                else:
                    self.error(f"signal_log 第 {i+1} 行缺少 date/signals 字段")
            except json.JSONDecodeError as e:
                self.error(f"signal_log 第 {i+1} 行 JSON 解析失败: {e}")
        if valid > 0:
            self.pass_(f"signal_log 格式正确: {valid}/{min(10, len(lines))} 行验证通过")
        if sample:
            signals = sample.get("signals", {})
            if signals:
                first_sym = list(signals.keys())[0]
                first_val = signals[first_sym]
                if ("factor" in first_val or "ie" in first_val) and "direction" in first_val:
                    self.pass_(f"signal_log 字段格式正确: {first_sym} -> {first_val}")
                else:
                    self.error(f"signal_log 字段不完整: {first_val} (需 factor/ie + direction)")

    # ── 汇总 ────────────────────────────────────────────
    def print_summary(self):
        print_header("检查汇总")
        total = self.passes + len(self.warnings) + len(self.errors) + len(self.infos)
        print(f"\n  通过:   {Colors.GREEN}{self.passes}{Colors.RESET}")
        print(f"  警告:   {Colors.YELLOW}{len(self.warnings)}{Colors.RESET}")
        print(f"  错误:   {Colors.RED}{len(self.errors)}{Colors.RESET}")
        print(f"  信息:   {Colors.CYAN}{len(self.infos)}{Colors.RESET}")
        print(f"  总检查: {total}")
        if self.errors:
            print(f"\n{Colors.RED}【结果】Quality Gates 未通过 — {len(self.errors)} 个错误，必须修复后才能交付。{Colors.RESET}")
            return 1
        if self.warnings:
            print(f"\n{Colors.YELLOW}【结果】Quality Gates 有条件通过 — {len(self.warnings)} 个警告，建议修复。{Colors.RESET}")
            return 0
        print(f"\n{Colors.GREEN}【结果】Quality Gates 全部通过 — 可以交付。{Colors.RESET}")
        return 0

    def run_all(self):
        print(f"\n{Colors.CYAN}Quality Gate Check (TSCTA) for: {self.project_dir}{Colors.RESET}")
        print(f"{Colors.CYAN}检查时间: {datetime.now().isoformat()}{Colors.RESET}")
        self.check_directory_structure()
        self.check_required_files()
        self.check_html_report_structure()
        self.check_charts()
        self.check_data_files()
        self.check_manifest()
        self.check_signal_log()
        return self.print_summary()


def main():
    if len(sys.argv) < 2:
        print("Usage: python quality_gate_check.py {report_id_dir}")
        sys.exit(1)
    project_dir = sys.argv[1]
    if not os.path.exists(project_dir):
        print(f"错误: 项目目录不存在: {project_dir}")
        sys.exit(1)
    checker = QualityGateChecker(project_dir)
    sys.exit(checker.run_all())


if __name__ == "__main__":
    main()
