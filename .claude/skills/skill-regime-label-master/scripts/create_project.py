#!/usr/bin/env python
"""Create a regime-label-master project directory structure."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path


def _load_env_upward(start: Path, max_up: int = 8) -> None:
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
    _load_env_upward(Path(__file__).parent)
    env = os.environ.get("REPLICATION_ROOT")
    if env:
        return Path(env) / "regime-projects"
    return Path.home() / "regime-projects"


DEFAULT_ROOT = _default_root()
SUBDIRS = [
    "01_initial",
    "02_iteration",
    "03_cross_validation",
    "04_delivery",
]

ARTIFACTS = {
    "regime_label": "01_initial/regime_label.md",
    "regime_label_view": "01_initial/regime_label_view.html",
    "reference_idea": "01_initial/reference_idea.md",
    "final_report": "04_delivery/final_report.md",
}


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9一-鿿]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "project"


def build_manifest(project_id: str, title: str) -> dict:
    return {
        "project_id": project_id,
        "title": title,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": {"executable": sys.executable,
                   "major_minor": f"{sys.version_info.major}.{sys.version_info.minor}"},
        "data": {
            "core": {"symbol": "510300.SH", "name": "沪深300 ETF", "role": "核心（迭代优化）"},
            "validation": [
                {"symbol": "518880.SH", "name": "黄金 ETF", "role": "验证（长周期趋势）"},
                {"symbol": "511010.SH", "name": "国债 ETF", "role": "验证（高自相关低波动）"},
            ],
        },
        "label_source": None,          # "manual" | "zigzag_binseg"
        "label_stats": None,           # {trend_pct, range_pct, ...}
        "iterations": [],              # [{id, date, accuracy, changes_summary}]
        "cross_validation": None,      # {symbol, accuracy, decay_rate}
        "stop_reason": None,           # "accuracy>85%" | "max_iterations"
        "artifacts": dict(ARTIFACTS),
        "status": "initialized",
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--title", required=True)
    p.add_argument("--report-id", help="project id，默认 title slug")
    p.add_argument("--root", default=str(DEFAULT_ROOT))
    args = p.parse_args()

    project_id = slugify(args.report_id or args.title)
    project_dir = Path(args.root).expanduser().resolve() / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    for subdir in SUBDIRS:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    manifest_path = project_dir / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        defaults = build_manifest(project_id, args.title)
        merged = {**defaults, **m}
        merged["artifacts"] = {**defaults["artifacts"], **m.get("artifacts", {})}
        manifest = merged
    else:
        manifest = build_manifest(project_id, args.title)

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps({"project_dir": str(project_dir), "manifest": str(manifest_path)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
