#!/usr/bin/env python
"""Create a standard research output directory for a report replication task."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def _load_env_upward(start: Path, max_up: int = 8) -> None:
    """从 start 向上逐级查找 .env，找到则载入 os.environ（不覆盖已存在的变量）。"""
    p = start.resolve()
    for _ in range(max_up):
        env_file = p / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return
        if p.parent == p:
            break
        p = p.parent


def _default_root() -> Path:
    """默认输出根：平台自适应。
    优先级：REPLICATION_ROOT（.env 或环境变量）> 云环境 /home/coder/project（若存在）> 本地 ~/report-replication。
    """
    _load_env_upward(Path(__file__).parent)
    env = os.environ.get("REPLICATION_ROOT")
    if env:
        return Path(env)
    cloud = Path("/home/coder/project/replication/report-replication")
    if cloud.parent.parent.exists():
        return cloud
    return Path.home() / "report-replication"


DEFAULT_ROOT = _default_root()
SUBDIRS = [
    "01_translation",
    "02_approach",
    "03_backtest_strategy/backtest_logs",
    "04_delivery",
]


ARTIFACTS = {
    "translation": "01_translation/full_translation.md",
    "approach": "02_approach/main_approach.md",
    "backtest_features": "03_backtest_strategy/backtest_features.md",
    "reference_implementation": "03_backtest_strategy/reference_implementation.py",
    "backtest_strategy": "03_backtest_strategy/strategy.py",
    "backtest_config": "03_backtest_strategy/config.json",
    "backtest_report": "03_backtest_strategy/backtest_report.html",
    "backtest_raw_report": "03_backtest_strategy/backtest_report_raw.html",
    "backtest_signal_log": "03_backtest_strategy/backtest_logs/signal_log.jsonl",
    "backtest_equity_curve": "03_backtest_strategy/backtest_logs/equity_curve.csv",
    "backtest_trades": "03_backtest_strategy/backtest_logs/trades.csv",
    "backtest_performance_metrics": "03_backtest_strategy/backtest_logs/performance_metrics.csv",
    "backtest_position_return_detail": "03_backtest_strategy/backtest_logs/position_return_detail.csv",
    "final_report": "04_delivery/final_report.md",
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
            "name": "ts-cta event-driven engine",
            "version": None,
            "status": "bundled_available",
            "script": "scripts/local_backtest.py",
            "notes": "Use the bundled local engine by default. Record external BACKTEST runner only when the user explicitly supplies one.",
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
