"""shared.sector — 期货品种板块分类（CATEGORY_MAP）。

按板块对品种分组，用于趋势 / 截面分析时的板块聚合（如"黑色系整体趋势性"）。
分类手工维护，已与 ssquant 的 90 个品种（``shared.data_fetcher.list_varieties``）
核对：90 个品种全部被"板块分类 + no_use 忽略"覆盖。

约定
----
- 低流动性 / 近僵尸 / 特殊品种**不进**此分类，统一在
  ``trend_following.check_trend_valid.no_use_symbols`` 里忽略（含 zc 动力煤、
  l_f/pp_f/v_f 月均价期货等）。
- 代码大小写不敏感（ssquant 返回大写，内部统一小写比对）。
"""

from typing import Dict, List, Optional

# 板块 → 品种代码（小写）
CATEGORY_MAP: Dict[str, List[str]] = {
    "黑色":     ["rb", "hc", "i", "j", "jm", "sf", "sm", "ss", "wr"],
    "有色金属": ["cu", "al", "zn", "pb", "ni", "sn", "ao", "bc", "ad"],
    "化工":     ["ru", "ta", "ma", "eg", "pf", "sh", "eb", "sa", "l", "v", "pp",
                 "ur", "pl", "pr", "px", "br", "bz", "lc", "nr", "ps", "si"],
    "能源":     ["sc", "pg", "lu", "fu", "bu"],
    "轻工":     ["sp", "op", "lg", "fb", "fg"],
    "油脂油料": ["oi", "pk", "rm", "a", "b", "m", "p", "y"],
    "谷物":     ["c", "cs", "rr"],
    "软商品":   ["cy", "cf", "sr"],
    "农副产品": ["ap", "jd", "cj", "lh"],
    "贵金属":   ["au", "ag", "pd", "pt"],
    "股指":     ["if", "ih", "ic", "im"],
    "国债":     ["t", "tf", "ts", "tl"],
    "集运":     ["ec"],
}

# 反向索引：品种代码(小写) → 板块名
_SYMBOL_TO_CATEGORY = {sym.lower(): cat for cat, syms in CATEGORY_MAP.items() for sym in syms}


def get_category(symbol: str) -> Optional[str]:
    """品种代码 → 所属板块（如 'rb' → '黑色'、'RB' → '黑色'）；未分类返回 None。"""
    return _SYMBOL_TO_CATEGORY.get(symbol.lower())


def symbols_of(category: str) -> List[str]:
    """板块名 → 该板块品种代码列表（副本；不存在返回空列表）。"""
    return list(CATEGORY_MAP.get(category, []))


def all_categories() -> Dict[str, List[str]]:
    """返回全部板块及其品种（副本）。"""
    return {cat: list(syms) for cat, syms in CATEGORY_MAP.items()}


if __name__ == "__main__":
    for cat, syms in CATEGORY_MAP.items():
        print(f"{cat}({len(syms)}): {syms}")
    print(f"\n品种总数: {len(_SYMBOL_TO_CATEGORY)}")
    print("rb →", get_category("rb"), "| cu →", get_category("CU"), "| RS →", get_category("RS"))
