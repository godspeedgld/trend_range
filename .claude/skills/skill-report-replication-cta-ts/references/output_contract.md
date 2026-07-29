# Output Contract（时序 CTA 研报 AI 复现）

每个复现项目遵守本契约。**与 -factor 的差异**：去因子（无 IC/分位/多空/因子验证）；新增 02_approach 量化方法提取（头条）；回测用事件驱动引擎。

## Directory

输出根平台自适应（`REPLICATION_ROOT`(.env/环境变量) > 云环境 `/home/coder/project` > 本地 `~/report-replication`），可用 `--root` 覆盖。

```
{输出根}/{report_id}/
  01_translation/full_translation.md(+ images/)      # 非中文→中文（英文研报才需要）
  02_approach/
    main_approach.md        # 【仅】量化方法提取（分类+思路/原理/公式/推导/优缺点+衍生方法+参考资料+未来）← headline
  03_backtest_strategy/
    backtest_features.md         # 回测特征（regime/开仓/止盈止损/开平仓/风控，文字+可执行代码）
    reference_implementation.py  # 指标/信号可审计实现
    strategy.py             # build_strategy(df)->spec，喂事件驱动引擎
    config.json             # 成本/滑点/年化/品种等参数
    backtest_report.html    # 中文回测解释
    backtest_report_raw.html
    backtest_logs/(equity_curve.csv, performance_metrics.csv, position_return_detail.csv, signal_log.jsonl[实现方向])
  04_delivery/
    final_report.md         # 综合"方法总结 + 回测结果"
  failure_report.md
  manifest.json
```

## Language

- 用户可见产出全程中文：translation、main_approach、backtest_features、backtest_report、final_report、代码注释。
- 英文仅用于公式、代码/API 名、指标缩写（Sharpe/Calmar/ATR）、原文标题、合约代码、CSV 列名。
- 引擎英文/数值输出存 `backtest_report_raw.html`，另做中文 `backtest_report.html`。

## Chart Image Text

- 图内文字仅英文 ASCII（标题/轴/图例）；中文解释放图周边。用 DejaVu Sans/Arial，不设中文字体。

## Data Source

- 外部本地路径 `--market-data`，**技能不下载**。必做合法性检查（NaN/复权/正价格/时序/覆盖），记 manifest。详见 data_sources.md。

## manifest.json

含：report_id、title、source、created_at、python、backtest_engine（事件驱动）、backtest_command、data_sources、assumptions、parameters、code_hashes、run_history、artifacts、status。

## 各步验收

1. **Translation**（若英文）：`full_translation.md` 保留结构/公式/图片，OCR 低置信标"待核验"，不臆造。
2. **Approach（头条）**：`main_approach.md` 按 approach.md 的 taxonomy 分类，每方法 5 部分 + 衍生方法 + 参考资料 + 未来。
3. **Backtest Features**：`backtest_features.md`（5 项特征，文字+代码）+ `reference_implementation.py`（可审计）。
4. **Backtest**：`strategy.py` 暴露 `build_strategy`；跑事件驱动引擎；产 equity/trades/metrics + 中文 backtest_report.html；记录已知局限。
5. **Final Report**：`final_report.md` 综合"方法总结 + 回测结果"，决策导向。

## Failure Report

任一必需阶段未完成时建 `failure_report.md`：失败阶段、命令、错误、部分产物、原因、下一步。
