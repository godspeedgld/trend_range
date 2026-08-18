#!/usr/bin/env python
"""区分度评估：算法输出 vs 标注（监督学习基准）。

区分度 = 算法输出与标注相同天数 / 总天数（去掉开头参数暖机期 warmup）。
停止条件：区分度 > 85% 或迭代次数 > 3。

用法：
  python evaluate_regime.py {project_dir} --algo <算法输出csv> --iter iter_001 [--warmup 250]

算法输出 CSV 格式：date,state（state: 1=趋势, 0=震荡；或带表头 date,regime）
标注：自动读取 01_initial/_label_daily.csv（zigzag_label.py 生成）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

STOP_ACCURACY = 0.85
MAX_ITERATIONS = 3


def load_algo(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    # 兼容列名 state / regime / label
    col = next((c for c in ["state", "regime", "label"] if c in df.columns), None)
    if col is None:
        raise ValueError(f"算法输出 CSV 缺少 state/regime/label 列: {path}")
    df = df.rename(columns={col: "state"})
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "state"]]


def load_label(project_dir: Path) -> pd.DataFrame:
    p = project_dir / "01_initial" / "_label_daily.csv"
    if not p.exists():
        raise FileNotFoundError(f"标注文件不存在（先跑 zigzag_label.py）: {p}")
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df[["date", "label"]]


def evaluate(algo: pd.DataFrame, label: pd.DataFrame, warmup: int) -> dict:
    merged = label.merge(algo, on="date", how="inner")
    if merged.empty:
        raise ValueError("算法输出与标注日期无交集（检查数据区间）")
    if warmup >= len(merged):
        warmup = max(0, len(merged) - 1)
    ev = merged.iloc[warmup:]
    ev_same = ev[ev["state"] == ev["label"]]
    accuracy = len(ev_same) / len(ev) if len(ev) else 0.0

    # 差异明细（供归因）
    disagree = ev[ev["state"] != ev["label"]]
    # 聚合为连续差异段
    segs = []
    if len(disagree):
        pos = disagree.index.to_series()
        blocks = (pos.diff() != 1).cumsum()
        dates = ev["date"]
        for _b, grp in disagree.groupby(blocks):
            i0, i1 = grp.index[0], grp.index[-1]
            segs.append({
                "start": dates.loc[i0], "end": dates.loc[i1], "days": int(len(grp)),
                "label": int(grp["label"].iloc[0]),   # 标注（正确）
                "algo": int(grp["state"].iloc[0]),    # 算法（错误输出）
                "error": "趋势→震荡" if grp["label"].iloc[0] == 1 else "震荡→趋势",
            })

    return {
        "n_overlap": len(merged), "warmup_skipped": warmup, "n_evaluated": len(ev),
        "n_same": int(len(ev_same)), "accuracy": round(accuracy, 4),
        "accuracy_pct": round(accuracy * 100, 2),
        "n_disagree_segments": len(segs),
        "disagree_segments": segs[:50],   # 最多列 50 段
    }


def update_manifest(project_dir: Path, iter_id: str, result: dict, stop: bool, reason: str):
    mp = project_dir / "manifest.json"
    if not mp.exists():
        return
    m = json.loads(mp.read_text(encoding="utf-8-sig"))
    iters = m.setdefault("iterations", [])
    entry = next((e for e in iters if e.get("id") == iter_id), None)
    if entry:
        entry["accuracy"] = result["accuracy_pct"]
    else:
        iters.append({"id": iter_id, "accuracy": result["accuracy_pct"]})
    if stop:
        m["stop_reason"] = reason
        m["status"] = "completed"
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("project_dir")
    p.add_argument("--algo", required=True, help="算法输出 CSV（date,state）")
    p.add_argument("--iter", default="iter_001", help="迭代 id")
    p.add_argument("--warmup", type=int, default=250, help="开头跳过天数（参数暖期）")
    args = p.parse_args()

    proj = Path(args.project_dir).resolve()
    algo = load_algo(Path(args.algo))
    label = load_label(proj)
    result = evaluate(algo, label, args.warmup)

    # 停止判断
    n_iters_done = len([d for d in (proj / "02_iteration").iterdir() if d.is_dir()]) \
        if (proj / "02_iteration").exists() else 1
    stop_acc = result["accuracy"] > STOP_ACCURACY
    stop_max = n_iters_done >= MAX_ITERATIONS
    stop, reason = (stop_acc, f"accuracy {result['accuracy_pct']}% > 85%") if stop_acc else \
                   ((stop_max, f"iterations {n_iters_done} >= {MAX_ITERATIONS}") if stop_max else
                    (False, ""))
    result["stop"] = stop
    result["stop_reason"] = reason or None
    result["iter"] = args.iter

    update_manifest(proj, args.iter, result, stop, reason)

    # 结果 JSON 落盘（迭代目录）
    iter_dir = proj / "02_iteration" / args.iter
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "evaluate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
