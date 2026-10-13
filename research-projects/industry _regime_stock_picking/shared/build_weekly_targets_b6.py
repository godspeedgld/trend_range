"""strategy_004 用的选股层扩展 —— **6 因子复合**（方案 B），其余与基线一字不差。

★ 为什么新增文件而不是改 `build_weekly_targets.py`：shared 已投产文件**冻结**，
  新需求以新增文件扩展（先例：`build_stock_panel_weekly.py` 不改 `build_stock_panel.py`）。
  本文件**只重写"因子集合相关"的三处**，其余（行业层 / 缓冲 / 权重）**直接 import 复用**。

方案 B（analysis_005 选出 3 个新因子 → analysis_006 立标尺，用户 2026-10-13 定）：
  基线四因子把 `mom_20` 换成 R076（`breakdown_5w_smooth`，与 px_ma20 ρ=0.77 同簇冗余）
  + 新增 R221（`price_volume_corr_5w_confirm_volume`）/ R222（`obv_slope_5w_confirm_volume`）
  ⇒ 6 个因子，方向**固定不随 regime 切换**（与基线的"恒反转"一致，6 个方向都是"买弱"）。
  复合方式**完全不变**：行业内 rank(pct)(因子ᵢ × 方向ᵢ) 的等权平均、全 NaN 剔除、并列用 symbol 二级键。

前 3 个基线因子在面板里，3 个新因子在仓库 `v_factor_1w`（周频因子宽表）里，故 `load_panel6()` 要 join。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_weekly_targets import (      # noqa: E402  ★ 复用冻结件，不内联
    BUF_MULT, CACHE, N_IND, N_PER_IND, WAREHOUSE, industry_weights, pick_industries,
)

# ── 方案 B 的 6 因子与固定方向（"买弱"框架，与基线恒反转同向）──
FACTORS6 = ["turn_ratio", "px_ma20", "breakdown_5w_smooth",
            "liq_amount", "price_volume_corr_5w_confirm_volume", "obv_slope_5w_confirm_volume"]
DIRS6 = {"turn_ratio": -1, "px_ma20": -1, "breakdown_5w_smooth": +1,
         "liq_amount": -1, "price_volume_corr_5w_confirm_volume": -1,
         "obv_slope_5w_confirm_volume": -1}
NEW_COLS = [c for c in FACTORS6 if c not in ("turn_ratio", "px_ma20", "liq_amount")]
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"


def load_panel6() -> pd.DataFrame:
    """基线面板 + 从仓库 `v_factor_1w` join 3 个新因子列（按 date + symbol=instrument）。"""
    panel = pd.read_parquet(PANEL)
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    con.register("k", panel[["date", "symbol"]].rename(columns={"symbol": "instrument"}))
    sel = ", ".join(f'f."{c}"' for c in NEW_COLS)
    got = con.execute(f"""SELECT f.date, f.instrument AS symbol, {sel}
        FROM v_factor_1w f JOIN k ON f.instrument = k.instrument AND f.date = k.date""").df()
    con.close()
    got["date"] = pd.to_datetime(got["date"])
    out = panel.merge(got, on=["date", "symbol"], how="left")
    cov = out[NEW_COLS].notna().all(axis=1).mean()
    print(f"[b6] 面板 {len(panel):,} 行 + 新因子 {len(NEW_COLS)} 列（三列齐备率 {cov:.1%}）")
    return out


def score_stocks6(sub: pd.DataFrame, dirs: dict = None) -> pd.Series:
    """与冻结版 `score_stocks` 逐字相同，只是因子表换成 FACTORS6 / DIRS6。"""
    dirs = dirs or DIRS6
    return pd.concat([sub[f].mul(dirs[f]).rank(pct=True) for f in FACTORS6],
                     axis=1).mean(axis=1)


def factor_directions6() -> dict:
    """方案 B 方向固定（不随 regime 切换）。"""
    return dict(DIRS6)


def build_targets6(cand: pd.DataFrame, inds: list[str], dirs: dict,
                   held: dict) -> dict[str, list[str]]:
    """与冻结版 `build_targets` 逐字相同（每行业挑 2 只 + 老仓前 `2×3=6` 名内保留），
    只把打分换成 `score_stocks6`。"""
    buf = N_PER_IND * BUF_MULT
    out = {}
    for ind in inds:
        sub = cand[cand["ind_name"] == ind].copy()
        if sub.empty:
            out[ind] = []
            continue
        sub["score"] = score_stocks6(sub, dirs)
        sub = sub.dropna(subset=["score"])          # 六因子全 NaN 的候选剔除（同云端）
        if sub.empty:
            out[ind] = []
            continue
        ranked = sub.sort_values(["score", "symbol"], ascending=[False, True])["symbol"].tolist()
        top_keep = set(ranked[:buf])
        targets = [s for s in held if s in top_keep][:N_PER_IND]     # 先留老仓（保序）
        for s in ranked:                                            # 再按排名补足
            if len(targets) >= N_PER_IND:
                break
            if s not in targets:
                targets.append(s)
        out[ind] = targets[:N_PER_IND]
    return out
