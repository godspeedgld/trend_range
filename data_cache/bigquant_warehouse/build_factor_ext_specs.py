"""生成「扩展因子」的 SPEC 网格 —— 用 QuantSkills 库里**已实现但没出厂**的 12 个 base。

背景：`factor.py` 实现了 **33 个 base**，但 512 个 SPEC 只用了 **21 个**。剩下 12 个
（`upper_wick` / `lower_wick` / `intraday` / `gap_sum` / `range_ratio` / `atr_ratio` /
`realized_vol` / `downside_vol` / `rsi` / `rsi_reversal` / `stoch` / `drawdown`）**代码在、没因子**。
这批对**形态分析**（假突破 / 破底翻）格外有用 —— 尤其上影/下影是假突破最直接的指纹，
而现成的 512 个里偏偏没有。

做法：**不改库代码**，只按它与现成 512 相同的命名网格（base × 8 变换 × 窗口 {5,7,10}）
造一份 SPEC JSON；计算时用 `build_factor_weekly.py --lib ext`，它复用**同一个** factor.py
（`_base` 本来就支持这 33 个 base）。

产物：`factor_specs_ext.json`（288 个 SPEC）
用法：python build_factor_ext_specs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
OUT = HERE / "factor_specs_ext.json"

# ── 12 个未出厂的 base（中文名 + 一句话语义）──
BASES = {
    "upper_wick":   ("上影线占比", "近 N 期平均「上影÷全幅」—— ★假突破指纹：冲高回落留长上影"),
    "lower_wick":   ("下影线占比", "近 N 期平均「下影÷全幅」—— ★破底翻指纹：砸下去拉回留下影"),
    "intraday":     ("日内涨跌",   "近 N 期平均（收/开−1）—— 突破日收在高位才健康"),
    "gap_sum":      ("跳空累计",   "近 N 期跳空(开/昨收−1)累计 —— 跳空突破的持续性"),
    "range_ratio":  ("平均振幅",   "近 N 期平均（高−低)/收 —— 小=收敛整理（三角形/平台）"),
    "atr_ratio":    ("ATR占比",    "ATR(N)/收 —— 波动率水平（定止损距离）"),
    "realized_vol": ("已实现波动", "近 N 期收益标准差 —— 波动率水平"),
    "downside_vol": ("下行波动",   "只算跌日的收益标准差 —— 下行风险"),
    "rsi":          ("RSI",        "N 期 RSI − 0.5 —— 超买超卖"),
    "rsi_reversal": ("RSI反转",    "0.5 − N 期 RSI —— 超买超卖（反向）"),
    "stoch":        ("随机指标",   "KD 的 K（收在 N 期高低区间的位置−0.5）"),
    "drawdown":     ("回撤深度",   "收/N 期最高 − 1 —— 距区间高点多远"),
}
TRANSFORMS = {
    "z": "标准化", "delta": "变化", "smooth": "平滑", "rank": "时序排名",
    "vol_scaled": "波动缩放", "stability": "稳定度", "confirm_volume": "量能确认", "compress": "压缩",
}
WINDOWS = [5, 7, 10]


def main() -> int:
    specs, n = [], 0
    for base, (cn, _sem) in BASES.items():
        for w in WINDOWS:
            # params 与现成 512 同构（norm/lag/smooth/fast/slow 随窗口走，见库 R001 的规律）
            params = {"window": w, "norm": 20, "lag": 1 if w <= 7 else 2, "skip": 5,
                      "smooth": 3, "fast": 3, "slow": w}
            for tr, tr_cn in TRANSFORMS.items():
                n += 1
                specs.append({
                    "factor_id": f"X{n:03d}", "slug": f"{w}d-{tr}-{base}",
                    "name_cn": f"{w}日{tr_cn}{cn}", "base": base, "transform": tr,
                    "params": params, "category_cn": "扩展",
                    "formula_cn": f"{tr}({base}, window={w})",
                })
    OUT.write_text(json.dumps({"specs": specs}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"→ {OUT.name}：{len(specs)} 个 SPEC（{len(BASES)} base × {len(TRANSFORMS)} 变换 × "
          f"{len(WINDOWS)} 窗口 {WINDOWS}）")
    print("\n各 base 的因子（首个窗口的 8 个变换）：")
    for b, (cn, sem) in list(BASES.items())[:12]:
        print(f"  {b:<15}{cn:<8}{sem}")
    cols = [s["base"] + f"_{s['params']['window']}w_" + s["transform"] for s in specs]
    assert len(set(cols)) == len(cols), "列名重复"
    print(f"\n列名唯一性 ✓（{len(set(cols))} 个）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
