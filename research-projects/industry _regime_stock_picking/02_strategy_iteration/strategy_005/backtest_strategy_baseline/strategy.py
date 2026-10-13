"""strategy_005 · **同目录对照 = 基线**（云端原版：变盘行业轮动 + 四因子恒反转）。

本目录不引入任何新逻辑 —— 它就是 **strategy_002/`backtest_strategy_baseline`** 那份策略，
在这里重跑一遍只为给 strategy_005 的 4 因子版提供**同引擎、同成本、同行情**的同目录对照。

★ 复用的 targets：`shared/_cache/targets_daily_baseline_indpre.parquet`
  由**冻结的** `shared/build_weekly_targets.py`（MODE=baseline）产出，本文件不重新生成逻辑，
  仅在缺失时才调用冻结流水线重建（保证逐值一致）。

★ 引擎：`local_weight_backtest.py`（权重引擎）。两套引擎不可混用。
运行：`python strategy.py`（打印引擎命令）
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
SHARED = PROJ / "shared"
CACHE = SHARED / "_cache"
sys.path.insert(0, str(SHARED))

MARKET = CACHE / "engine_market_weekly_indpre_rawpx.parquet"
TARGETS = CACHE / "targets_daily_baseline_indpre.parquet"


def ensure_targets() -> Path:
    """基线 targets 已存在就直接用；缺失时按**冻结流水线**重建（MODE=baseline + 展开到日频）。"""
    if TARGETS.exists():
        print(f"[baseline] 复用已有 targets：{TARGETS.name}")
        return TARGETS
    print("[baseline] targets 缺失 → 用冻结流水线重建 …")
    env = {**os.environ, "IND": "prefactors", "UNIVERSE": "weekly", "MODE": "baseline", "PRICE": "raw"}
    subprocess.run([sys.executable, str(SHARED / "build_weekly_targets.py")], check=True, env=env)
    subprocess.run([sys.executable, str(SHARED / "expand_targets_daily.py"),
                    "--targets", str(TARGETS)], check=True)
    return TARGETS


def main() -> int:
    ensure_targets()
    engine = PROJ.parents[1] / ".claude/skills/skill-research-assistant/scripts/local_weight_backtest.py"
    print("\n跑引擎（权重引擎）：")
    print(f"  python '{engine}' '{PROJ}' \\")
    print(f"      --market-data '{MARKET}' --targets '{TARGETS}' \\")
    print(f"      --output-dir '{HERE}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
