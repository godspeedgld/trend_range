"""strategy_005 用的选股层扩展 —— **4 因子复合**，其余与基线/迭代四一字不差。

★ 与 `build_weekly_targets_b6.py`（strategy_004 用）的**唯一差别 = 因子集合**：
    b6（方案 B，6 因子）：turn_ratio · **px_ma20** · breakdown_5w_smooth · **liq_amount** · R221 · R222
    b4（本文件，4 因子）：turn_ratio · breakdown_5w_smooth · R221 · R222
    ⇒ 去掉 `px_ma20` 与 `liq_amount`：
      · `px_ma20` 与 R076（breakdown_5w_smooth）池内 |ρ|=0.69 —— 同一信号，留更强的（R076 IC 0.0659 vs 0.0605）
      · `liq_amount` 是全组最弱（IC 0.0290 / t 3.25）

★ shared 已投产文件冻结 → 本文件是**新增**（不改 `build_weekly_targets.py` / `build_weekly_targets_b6.py`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_weekly_targets import (      # noqa: E402  ★ 复用冻结件
    BUF_MULT, CACHE, N_IND, N_PER_IND, WAREHOUSE, industry_weights, pick_industries,
)

# ── 4 因子与固定方向（"买弱"框架）──
FACTORS4 = ["turn_ratio", "breakdown_5w_smooth",
            "price_volume_corr_5w_confirm_volume", "obv_slope_5w_confirm_volume"]
DIRS4 = {"turn_ratio": -1, "breakdown_5w_smooth": +1,
         "price_volume_corr_5w_confirm_volume": -1, "obv_slope_5w_confirm_volume": -1}
NEW_COLS = [c for c in FACTORS4 if c not in ("turn_ratio",)]     # 面板里没有、要从仓库 join 的
PANEL = CACHE / "signal_panel_weekly_indpre.parquet"


def load_panel4() -> pd.DataFrame:
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
    print(f"[b4] 面板 {len(panel):,} 行 + 新因子 {len(NEW_COLS)} 列（齐备率 {cov:.1%}）")
    return out


def score_stocks4(sub: pd.DataFrame, dirs: dict = None) -> pd.Series:
    """与基线 `score_stocks` 逐字相同，只是因子表换成 FACTORS4 / DIRS4。"""
    dirs = dirs or DIRS4
    return pd.concat([sub[f].mul(dirs[f]).rank(pct=True) for f in FACTORS4],
                     axis=1).mean(axis=1)


def factor_directions4() -> dict:
    """方向固定（不随 regime 切换）。"""
    return dict(DIRS4)


def build_targets4(cand: pd.DataFrame, inds: list[str], dirs: dict,
                   held: dict) -> dict[str, list[str]]:
    """与基线 `build_targets` 逐字相同（每行业挑 2 只 + 老仓前 6 名内保留），只把打分换成 `score_stocks4`。"""
    buf = N_PER_IND * BUF_MULT
    out = {}
    for ind in inds:
        sub = cand[cand["ind_name"] == ind].copy()
        if sub.empty:
            out[ind] = []
            continue
        sub["score"] = score_stocks4(sub, dirs)
        sub = sub.dropna(subset=["score"])          # 四因子全 NaN 的候选剔除（同云端）
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
