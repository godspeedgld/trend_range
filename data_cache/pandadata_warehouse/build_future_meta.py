"""建期货品种表 `future_meta`（合约乘数 / 保证金率 / 中文名 / 板块）—— 供 cs-trend-train 期货模式用。

数据来源（**不调 API**：`get_future_detail` 本账号无权限，错误码 200103）：
  · 主源 = `temp/保证金.xlsx` 的「商品」sheet —— 用户手工维护的测算表：
      「保证金率」列是空的，但**「保证金1」（每手保证金）有值** ⇒ 反推
        `费率 = 保证金1 / (开仓 × 乘数)`，实测值很合理（螺纹 8.5~9%、铜 9~12%、原油 16~19%、焦炭 20%）
  · 品种代码 = `future_daily.underlying_symbol`（72 个商品品种）
  · 表里 `代号` 有几处错（焦煤误填 J、燃油误填 RU、塑料/玉米淀粉/纸浆/原木 代号为空）
    → 用**明确的白名单 OVERRIDE** 按中文名纠正（不猜、逐条可查）

产物：`future_meta.parquet` + duckdb 视图 `future_meta`（绝对路径，与 bigquant 仓库同约定）
用法：python build_future_meta.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent          # data_cache/pandadata_warehouse
REPO = ROOT.parents[1]
XLSX = REPO / "temp" / "保证金.xlsx"
DB = ROOT / "warehouse.duckdb"
OUT = ROOT / "future_meta.parquet"

# ── 按中文名纠正表里错/缺的品种代码（逐条可查，不靠猜）──
OVERRIDE = {
    "焦煤": "JM",      # 表里代号误填 J（J 是焦炭）
    "燃油": "FU",      # 表里代号误填 RU（RU 是橡胶）
    "塑料": "L",       # 代号为空
    "玉米淀粉": "CS",  # 代号为空
    "纸浆": "SP",      # 代号为空
    "原木": "LG",      # 代号为空
}


def main() -> int:
    sheet = pd.read_excel(XLSX, sheet_name="商品")
    s = sheet[sheet["类别"].notna() & sheet["乘数"].notna() & sheet["保证金1"].notna()
               & sheet["开仓"].notna() & sheet["开仓"].gt(0)].copy()
    s["code"] = s["代号"].astype(str).str.strip().str.upper()
    s.loc[s["品种"].isin(OVERRIDE), "code"] = s["品种"].map(OVERRIDE)
    s = s[~s["code"].isin(["NAN", ""])]
    s["rate"] = s["保证金1"] / (s["开仓"] * s["乘数"]) * 100      # 反推保证金率 %

    # 同品种多条 → 取中位（表里不同日期的费率会因交易所调整而略异）
    g = (s.groupby("code")
           .agg(中文名=("品种", "first"), 类别=("类别", "first"),
                乘数=("乘数", "first"), 保证金率=("rate", "median"),
                样例数=("rate", "size"), 费率最低=("rate", "min"), 费率最高=("rate", "max"))
           .reset_index())
    g["保证金率"] = g["保证金率"].round(4)
    print(f"从表里得到 {len(g)} 个品种（原始行 {len(s)}）")

    # 与数据里的品种对齐（★ 直接读 parquet：库里 future_daily 视图用的是**相对路径**，
    #   只有在仓库根当 cwd 时才查得到，脚本在别处跑会报 "No files found"）
    con = duckdb.connect()
    fd = (ROOT / "future_daily").resolve().as_posix()
    codes = [r[0] for r in con.execute(
        f"SELECT DISTINCT underlying_symbol FROM read_parquet('{fd}/**/*.parquet') "
        "ORDER BY 1").fetchall()]
    con.close()
    m = pd.DataFrame({"code": codes}).merge(g, on="code", how="left")
    have = m["乘数"].notna()
    print(f"数据里 {len(codes)} 个品种 → 有元数据 {int(have.sum())}，缺 {int((~have).sum())}")
    if (~have).any():
        print("  ⚠ 缺元数据（工具里可看 K 线但**不能开仓**，需要补乘数/费率）："
              + ", ".join(m.loc[~have, "code"]))

    out = m[["code", "中文名", "类别", "乘数", "保证金率", "样例数", "费率最低", "费率最高"]]
    out.to_parquet(OUT, index=False)
    con = duckdb.connect(str(DB))
    con.execute(f"CREATE OR REPLACE VIEW future_meta AS "
                f"SELECT * FROM read_parquet('{OUT.resolve().as_posix()}')")
    n = con.execute("SELECT count(*) FROM future_meta WHERE 乘数 IS NOT NULL").fetchone()[0]
    con.close()
    print(f"→ {OUT.name}（可用 {n} 个品种）")
    print(out[out["乘数"].notna()].head(8).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
