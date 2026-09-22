"""strategy_001 预计算 —— 行业层（申万一级官方指数）+ 变盘指数 T′。

数据源：`stock_industry_sw_bar1d`（BigQuant `cn_stock_industry_sw_bar1d`，801xxx.SWI 官方指数，
市值加权口径）。**注意与 analysis_001 不同源**：analysis_001 用的是 `stock_industry_bar1d`
的 784 叶子行业按 2 位前缀 `avg(change_ratio)` 等权聚合；本版用官方指数。

口径铁律（2026-09-22 数据核查）：
  ① 剔除 `801020.SWI`（旧「采掘」，2021-12-10 截断）—— 它与 801950 煤炭 + 801960 石油石化
     在 2015-2021 并存且重叠，留着会让横截面排名有一个冗余项。
  ② 名称映射 31 个 SW2021 一级：名称集合与 component 双向完全匹配；801 码↔名对应关系
     已用「成分股等权收益 vs 指数收益」相关矩阵对角线验证（31/31 列对角线均为该列最大）。

产物（`_cache/`）：
  industry_index.parquet  (date, ind_code, ind_name, close)         31 行业 × 日频
  regime.parquet          (date, rank_change, T, T_prime)           变盘指数日频标量
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]                      # trend_range
WAREHOUSE = ROOT / "data_cache/bigquant_warehouse/bigquant_warehouse.duckdb"
OUT = HERE / "_cache"

START, END = "2015-01-01", "2026-08-21"
DROP_CODE = "801020"                        # 旧「采掘」，已废弃

# SW2021 一级：801 代码 → 行业名（名称集合已与 stock_industry_component 双向核对一致）
SW801 = {
    "农林牧渔": "801010", "基础化工": "801030", "钢铁": "801040", "有色金属": "801050",
    "电子": "801080", "汽车": "801880", "家用电器": "801110", "食品饮料": "801120",
    "纺织服饰": "801130", "轻工制造": "801140", "医药生物": "801150", "公用事业": "801160",
    "交通运输": "801170", "房地产": "801180", "商贸零售": "801200", "社会服务": "801210",
    "银行": "801780", "非银金融": "801790", "综合": "801230", "建筑材料": "801710",
    "建筑装饰": "801720", "电力设备": "801730", "机械设备": "801890", "国防军工": "801740",
    "计算机": "801750", "传媒": "801760", "通信": "801770", "煤炭": "801950",
    "石油石化": "801960", "环保": "801970", "美容护理": "801980",
}
CODE2NAME = {v: k for k, v in SW801.items()}

# 变盘指数参数（用户 2026-09-22 指定；analysis_001 用的是 trailing-21，本版为 20）
RET_WIN = 20            # 行业"月度"收益率窗口（交易日）
MIG_WIN = 220           # 排名迁移回看
VOL_WIN = 220           # 二阶波动窗口
SMOOTH_WIN = 20         # 平滑窗口


def load_industry_index() -> pd.DataFrame:
    """31 个申万一级官方指数收盘价（长表）。"""
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    df = con.execute(f"""
        SELECT date, replace(instrument, '.SWI', '') AS ind_code, close
        FROM stock_industry_sw_bar1d
        WHERE date >= '{START}' AND date <= '{END}'
          AND instrument NOT LIKE '{DROP_CODE}%'
        ORDER BY date, ind_code
    """).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    df["ind_name"] = df["ind_code"].map(CODE2NAME)
    assert df["ind_name"].notna().all(), "存在未映射的行业代码"
    assert df["close"].notna().all(), "行业指数存在空值"
    return df


def build_regime(piv: pd.DataFrame) -> pd.DataFrame:
    """变盘指数 T′（银河研报口径，用户指定参数）。

    piv: index=date, columns=ind_code, values=close
    """
    month_ret = piv / piv.shift(RET_WIN) - 1                    # 各行业"月度收益率"
    rank_now = month_ret.rank(axis=1, ascending=False)           # 每日横截面排名（1=最强）
    rank_change = (rank_now - rank_now.shift(MIG_WIN)).abs().mean(axis=1)   # 排名迁移强度
    T = rank_change.rolling(VOL_WIN).std().rolling(SMOOTH_WIN).mean()       # 二阶波动 + 平滑
    T_prime = T.diff()
    out = pd.DataFrame({"rank_change": rank_change, "T": T, "T_prime": T_prime})
    out.index.name = "date"
    return out.reset_index()


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    ind = load_industry_index()
    piv = ind.pivot(index="date", columns="ind_code", values="close").sort_index()
    print(f"行业指数: {piv.shape[1]} 个行业 × {len(piv)} 交易日 "
          f"({piv.index.min().date()} ~ {piv.index.max().date()})")

    # 行业动量（行业层选行业用）
    mom = pd.DataFrame({
        "mom_240": (piv / piv.shift(240) - 1).stack(),
        "mom_60": (piv / piv.shift(60) - 1).stack(),
    })
    mom.index.names = ["date", "ind_code"]
    ind = ind.set_index(["date", "ind_code"]).join(mom).reset_index()

    reg = build_regime(piv)
    valid = reg["T_prime"].notna()
    print(f"变盘指数: {len(reg)} 日，T′ 有效 {valid.sum()} 日 "
          f"（首个有效 {reg.loc[valid, 'date'].min().date()}）")
    print(f"  T′<0 占比 {(reg.loc[valid, 'T_prime'] < 0).mean():.1%}（动量期）")

    ind.to_parquet(OUT / "industry_index.parquet", index=False)
    reg.to_parquet(OUT / "regime.parquet", index=False)
    print(f"→ {OUT}/industry_index.parquet  ({len(ind):,} 行)")
    print(f"→ {OUT}/regime.parquet          ({len(reg):,} 行)")

    # 行业动量覆盖率抽查
    print("\n行业动量非空数（应随年份递增到 31）:")
    chk = ind.copy()
    for y, g in chk.groupby(chk["date"].dt.year):
        n240 = g.dropna(subset=["mom_240"])["ind_name"].nunique()
        n60 = g.dropna(subset=["mom_60"])["ind_name"].nunique()
        print(f"  {y}: mom_240 {n240:>2} 行业 / mom_60 {n60:>2} 行业")


if __name__ == "__main__":
    main()
