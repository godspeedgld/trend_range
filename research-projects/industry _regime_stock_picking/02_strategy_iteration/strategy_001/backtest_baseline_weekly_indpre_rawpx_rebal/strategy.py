"""对照回测 · 修 ①价格=原始价 ②行业来源=prefactors 后的 baseline（云端等价版）。

与 backtest_baseline_weekly 的唯一差异：
  ① IND=prefactors → panel 的行业归属改用 stock_prefactors_attr.sw_level_index_code
     （覆盖 5,830 只，与云端 cn_stock_prefactors 同源；旧版用 stock_industry_component_daily
      只 5,033 只，池差 6%）
  ② PRICE=raw → 引擎行情用**原始价**（后复权价 ÷ adjust_factor）
     实证：云端 bigtrader 5,548 笔成交价 = 原始价，99.7% 逐笔吻合

产物：shared/_cache/{signal_panel_weekly_indpre, weekly_targets_baseline_weekly_indpre_rawpx,
      engine_market_weekly_indpre_rawpx}.parquet
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from targets_lookup import make_interfaces  # noqa: E402

entry_signal, exit_check, pool_invalidate, select_order, position_weight = \
    make_interfaces("baseline_weekly_indpre_rawpx")
