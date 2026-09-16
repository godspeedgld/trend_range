"""上传迭代三预计算数据到 BigQuant DataSource（aistudio 策略读取用）。

aistudio 是云端环境，读不到本地文件 → 必须先把本地预计算的
  ① 突破事件表（date + instrument + 26变量）→  DataSource `vol_enhance_v2_events`
  ② 半年节点计划（node_date + active + payload JSON）→ DataSource `vol_enhance_v2_nodes`
推上 BigQuant。之后 aistudio 策略用 dai 查这两张表即可。

运行前：AK/SK 配置在 ~/.bigquant/config.json（skill-bigquant-sdk 认证）。
依赖本地缓存：shared/vol_enhance_v2_events.parquet + shared/vol_enhance_v2_nodes.json
（若不存在先跑策略本地回测生成）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from bigquant import bigquant, dai

bigquant.init_from_config()

PROJ = Path(__file__).resolve().parents[1]          # 工程根
SHARED = PROJ / "shared"

# ── 26 变量（与 shared/vol_enhance_v2.py VOL_VARS 一致）──
VOL_VARS = ["Turn", "TurnMean5d", "TurnMean20d", "TurnMean45d",
            "TurnVol5d", "TurnVol20d", "TurnVol45d",
            "AmtMean5d", "AmtMean20d", "AmtMean45d",
            "AmtRatio5d", "AmtRatio20d", "AmtRatio45d",
            "Ret5d", "Ret20d", "Ret45d",
            "Vol5d", "Vol20d", "Vol45d",
            "LnCap", "CapVol5d", "CapVol20d", "CapVol45d",
            "PriceMA5Dev", "PriceMA20Dev", "PriceMA45Dev"]

# 1. 事件表 → vol_enhance_v2_events（date 分区，策略按日查）
events = pd.read_parquet(SHARED / "vol_enhance_v2_events.parquet")
ev = events[["date", "instrument"] + VOL_VARS].copy()
ev["date"] = pd.to_datetime(ev["date"]).dt.strftime("%Y-%m-%d")
print(f"事件表: {len(ev)} 行 | {ev['date'].min()} ~ {ev['date'].max()}")
dai.DataSource().write_bdb(
    ev, id="vol_enhance_v2_events",
    partitioning=["date"], indexes=["instrument", "date"],
    overwrite=True)
print("已上传 vol_enhance_v2_events")

# 2. 节点计划 → vol_enhance_v2_nodes（payload 为 JSON：selected_vars/coef/mu/sigma）
nodes = json.loads((SHARED / "vol_enhance_v2_nodes.json").read_text(encoding="utf-8"))
rows = []
for nd in nodes:
    rows.append({
        "node_date": str(nd["node_date"])[:10],
        "active": bool(nd["active"]),
        "payload": json.dumps({
            "selected_vars": nd["selected_vars"],
            "coef": nd["coef"],
            "mu": nd["mu"],
            "sigma": nd["sigma"],
        }, ensure_ascii=False),
    })
nodes_df = pd.DataFrame(rows)
print(f"节点计划: {len(nodes_df)} 行, 有效 {int(nodes_df['active'].sum())}")
dai.DataSource().write_bdb(
    nodes_df, id="vol_enhance_v2_nodes",
    overwrite=True)
print("已上传 vol_enhance_v2_nodes")
print("\n完成。aistudio 策略将查询这两张 DataSource。")
