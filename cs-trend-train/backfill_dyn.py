"""回填「动态止盈（吊灯）」结果到已有交易记录（2026-10-16 用户指定）。

口径：**所有已有记录视为「已勾选动态止盈」** ⇒ 逐笔跑 `chandelier_exit()`（复用 server.py 里
**同一个函数**，保证与提交路径口径一致），只写入 `dyn_tp` 与 `dyn_*` 字段，
**绝不触碰** `exit_date/exit_price/exit_reason/holding_days` 等静态字段。

安全：
  ① `--dry-run` 只打印将要改动的笔数与摘要，不写文件；
  ② 正式跑前**先备份**：`data/trades.pre-dyn-<YYYYMMDD-HHMMSS>.json`（期货同理）；
  ③ **幂等**：已有 `dyn_tp`/`dyn_exit_reason` 的记录跳过（`--force` 强制重算）；
  ④ 结尾断言两条硬不变量并打印对账摘要。

用法：
    python backfill_dyn.py --dry-run
    python backfill_dyn.py                    # 股票 + 期货
    python backfill_dyn.py --src stock        # 只股票
    python backfill_dyn.py --force            # 重算已有 dyn_* 的记录
"""
from __future__ import annotations

import argparse
import importlib.util
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent


def load_server():
    spec = importlib.util.spec_from_file_location("srv_bf", HERE / "server.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["srv_bf"] = m
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", choices=["stock", "future", "all"], default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="已有 dyn_* 的记录也重算")
    a = ap.parse_args()
    srv = load_server()
    srcs = ["stock", "future"] if a.src == "all" else [a.src]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    grand = 0

    for src in srcs:
        path = srv.src_paths(src)[1]
        db = srv._load(path)
        if not db:
            print(f"[{src}] {path.name}: 空，跳过")
            continue
        todo, skip, atr_missing, pairs = [], 0, 0, Counter()
        for sym, lst in db.items():
            for i, r in enumerate(lst):
                if not a.force and (("dyn_exit_reason" in r) or ("dyn_tp" in r)):
                    skip += 1
                    continue
                todo.append((sym, i))
                d = srv.chandelier_exit(sym, r, src)          # ★ 与提交路径同一函数
                pairs[(str(r.get("exit_reason")), d["dyn_exit_reason"])] += 1
                if d.get("dyn_atr_missing"):
                    atr_missing += 1
                if a.dry_run:                                  # 只展示，不落库
                    if d["dyn_exit_reason"] != r.get("exit_reason") or d["dyn_exit_price"] != r.get("exit_price"):
                        print(f"   {src} {sym} {r.get('id')} {r.get('entry_date')} "
                              f"静 {r.get('exit_reason')}@{r.get('exit_price')} → "
                              f"动 {d['dyn_exit_reason']}@{d['dyn_exit_price']} (hd={d['dyn_holding_days']})")
                else:
                    lst[i] = srv.apply_dyn(sym, dict(r), src, enabled=True)   # 原地写入 dyn_*
            db[sym] = lst

        print(f"\n[{src}] {path.name}：共 {sum(len(v) for v in db.values())} 笔 | "
              f"待回填 {len(todo)} | 已有 dyn_* 跳过 {skip} | atr 缺失 {atr_missing}")
        print(f"   （静态原因 → 动态原因）分布：{dict(pairs)}")
        n_closed_static = sum(v for (s, _), v in pairs.items() if s not in ("pending", "None"))
        n_closed_dyn = sum(v for (_, d), v in pairs.items() if d != "pending")
        print(f"   已平仓：静态 {n_closed_static} → 动态 {n_closed_dyn}"
              f"（差 {n_closed_dyn - n_closed_static:+d} = 动态把持仓中的笔也收盘了/反之）")
        short = sum(1 for sym, lst in db.items() for r in lst if (r.get("direction") or "long") == "short")
        print(f"   做空 {short} 笔（股票预期 15 / 期货 1）")

        if a.dry_run:
            print("   [dry-run] 未写任何文件")
            continue
        if not todo:
            print("   无需改动（幂等）")
            continue
        # ── 备份 → 落盘 → 校验 ──
        bak = path.with_name(f"{path.stem}.pre-dyn-{ts}{path.suffix}")
        if not bak.exists():
            shutil.copy2(path, bak)
            print(f"   备份 → {bak.name}")
        srv._save(path, db)

        back = srv._load(path)
        bad_a = bad_b = 0
        for sym, lst in back.items():
            for r in lst:
                if r.get("exit_reason") == "止损" and r.get("dyn_exit_reason") == "止损":
                    if (r.get("exit_date"), r.get("exit_price")) != (r.get("dyn_exit_date"), r.get("dyn_exit_price")):
                        bad_a += 1
                        print(f"   ⚠ 不变量 A 违反：{sym} {r.get('id')}")
                if r.get("dyn_exit_reason") == "止盈":
                    bad_b += 1
                    print(f"   ⚠ 不变量 B 违反（动态出现止盈）：{sym} {r.get('id')}")
                if not (r.get("dyn_tp") in (True, False)):
                    print(f"   ⚠ 缺 dyn_tp：{sym} {r.get('id')}")
        print(f"   校验：不变量 A（静态止损 ⇒ 动态逐值相等）违反 {bad_a} | "
              f"不变量 B（动态不出现止盈）违反 {bad_b} | 文件 {path.name} 已更新")
        grand += len(todo)

    print(f"\n{'[dry-run] 预览完成' if a.dry_run else '完成'}：共回填 {grand} 笔")
    if not a.dry_run and grand:
        print(f"回滚：git checkout -- data/trades.json data/trades_future.json"
              f"（或把 *.pre-dyn-{ts}.json 覆盖回去）")


if __name__ == "__main__":
    main()
