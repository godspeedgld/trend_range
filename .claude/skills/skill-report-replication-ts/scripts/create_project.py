#!/usr/bin/env python
"""Create a standard research output directory for a time-series CTA report replication task."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path


DEFAULT_ROOT = Path("/home/coder/project/replication/report-replication")
SUBDIRS = [
    "01_translation",
    "02_strategy_logic",
    "03_strategy_evaluation/data",
    "03_strategy_evaluation/charts",
    "04_backtest_strategy/backtest_logs",
    "06_delivery",
]


ARTIFACTS = {
    # Step 2: 翻译
    "translation": "01_translation/full_translation.md",
    # Step 3: 策略逻辑抽取（开仓/止损/止盈）
    "strategy_summary": "02_strategy_logic/strategy_summary.md",
    "strategy_reference_implementation": "02_strategy_logic/reference_implementation.py",
    # Step 5: 策略评估报告（TSCTA 口径，非因子验证）
    "evaluation_report": "03_strategy_evaluation/evaluation_report.html",
    "direction_matrix": "03_strategy_evaluation/data/direction_matrix_from_strategy.csv",
    "portfolio_returns_full": "03_strategy_evaluation/data/portfolio_returns_dir_full.csv",
    "backtest_alignment_audit": "03_strategy_evaluation/data/backtest_alignment_audit.csv",
    "benchmark_comparison": "03_strategy_evaluation/data/benchmark_comparison.csv",
    "regime_metrics": "03_strategy_evaluation/data/regime_metrics.csv",
    "chart_nav": "03_strategy_evaluation/charts/01_nav.png",
    "chart_drawdown": "03_strategy_evaluation/charts/02_drawdown.png",
    "chart_regime": "03_strategy_evaluation/charts/03_regime_nav.png",
    "chart_benchmark": "03_strategy_evaluation/charts/04_benchmark_nav.png",
    "chart_yearly": "03_strategy_evaluation/charts/05_yearly_return.png",
    "chart_rolling_sharpe": "03_strategy_evaluation/charts/06_rolling_sharpe.png",
    "chart_cost_sensitivity": "03_strategy_evaluation/charts/07_cost_sensitivity.png",
    "chart_walkforward": "03_strategy_evaluation/charts/08_walkforward.png",
    # Step 4: 策略 + 本地回测
    "backtest_strategy": "04_backtest_strategy/strategy.py",
    "backtest_config": "04_backtest_strategy/config.json",
    "backtest_report": "04_backtest_strategy/backtest_report.html",
    "backtest_raw_report": "04_backtest_strategy/backtest_report_raw.html",
    "backtest_signal_log": "04_backtest_strategy/backtest_logs/signal_log.jsonl",
    "backtest_equity_curve": "04_backtest_strategy/backtest_logs/equity_curve.csv",
    "backtest_trades": "04_backtest_strategy/backtest_logs/trades.csv",
    "backtest_performance_metrics": "04_backtest_strategy/backtest_logs/performance_metrics.csv",
    "backtest_position_return_detail": "04_backtest_strategy/backtest_logs/position_return_detail.csv",
    # Step 6: 交付
    "final_delivery_summary": "06_delivery/final_delivery_summary.md",
    "failure_report": "failure_report.md",
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "report"


def build_manifest(report_id: str, title: str, source: str | None) -> dict:
    return {
        "report_id": report_id,
        "title": title,
        "source": source,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "backtest_engine": {
            "name": "ts-cta local BACKTEST",
            "version": None,
            "status": "bundled_available",
            "script": "scripts/local_backtest.py",
            "notes": "bundled signal-driven engine; consumes external --market-data (skill never downloads). Stop-loss/take-profit live in strategy.py (emit direction).",
        },
        "backtest_entrypoint": "scripts/local_backtest.py",
        "backtest_command": None,
        "data_sources": [],
        "assumptions": [],
        "parameters": {},
        "code_hashes": {},
        "run_history": [],
        "artifacts": dict(ARTIFACTS),
        "quality_control": {
            "status": "initialized",
            "incident": None,
            "notes": [],
        },
        "status": "initialized",
    }


def read_json_utf8(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def merge_defaults(existing: dict, defaults: dict) -> dict:
    merged = dict(defaults)
    merged.update(existing)
    merged["artifacts"] = {**defaults.get("artifacts", {}), **existing.get("artifacts", {})}
    merged["backtest_engine"] = {
        **defaults.get("backtest_engine", {}),
        **existing.get("backtest_engine", {}),
    }
    merged["quality_control"] = {
        **defaults.get("quality_control", {}),
        **existing.get("quality_control", {}),
    }
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True, help="Report or paper title.")
    parser.add_argument("--source", help="Original PDF path, URL, or source note.")
    parser.add_argument("--report-id", help="Stable report id. Defaults to title slug.")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Output root directory.")
    args = parser.parse_args()

    report_id = slugify(args.report_id or args.title)
    project_dir = Path(args.root).expanduser().resolve() / report_id
    project_dir.mkdir(parents=True, exist_ok=True)

    for subdir in SUBDIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    manifest_path = project_dir / "manifest.json"
    defaults = build_manifest(report_id, args.title, args.source)
    if manifest_path.exists():
        manifest = merge_defaults(read_json_utf8(manifest_path), defaults)
        manifest.setdefault("status", "initialized")
    else:
        manifest = defaults

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps({"project_dir": str(project_dir), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
