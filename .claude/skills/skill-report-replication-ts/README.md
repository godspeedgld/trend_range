# skill-report-replication-ts

**时序 CTA / 趋势跟踪研报复现技能**。把一篇时序 CTA 研报、论文、PDF、网页或文本，端到端转化为完整复现交付包：

**全文中文翻译 → 策略逻辑抽取（开仓 / 止损 / 止盈）→ 回测策略代码 → 真实本地回测 → 中文评估报告 → 交付摘要**

## 与 skill-report-replication-factor 的区别

| 维度 | -factor（截面因子） | **-ts（时序 CTA）** |
|------|---------------------|---------------------|
| 适用研报 | 选股/选券截面因子 | 趋势跟踪/动量/反转择时 |
| 核心验证 | IC/分位/多空 | **开仓/止损/止盈 + 净值/Sharpe/Calmar** |
| 因子验证阶段 | ✅ 有 | ❌ **无** |
| 截面分析 | ✅ | ❌（时序无截面） |

## 输入

- 🌐 网页论文（URL，如微信公众号文章）
- 📄 本地 PDF
- 📝 文本

## 数据源（关键）

行情数据由用户以**外部本地路径**提供（`local_backtest.py --market-data <CSV/Parquet>`）。**本技能本身不下载行情。** 来源/路径/品种/区间记录在 `manifest.json`。

## 工作流（7 步）

1. **Initialize** — 建项目骨架 + manifest
2. **Extract & Translate** — 翻译为中文
3. **Extract Strategy Logic** — 抽取开仓/止损/止盈三要素
4. **Generate & Run Backtest** — 写 strategy.py + 跑本地回测
5. **Strategy Evaluation Report** — 中文评估 HTML（净值/回撤/regime/基准）
6. **Final Delivery** — 交付摘要
7. **Quality Gate** — 自动校验

每步有门禁脚本（`check_step2_translation.py`、`check_strategy_logic.py`、`check_step5_strategy.py`、`quality_gate_check.py`）。

## 用法

```bash
# 1. 建项目
python scripts/create_project.py --title "华泰时序CTA方法论综述" --source "https://..." --root /tmp/ts

# 2~6. 由 Claude 按工作流产出各产物
# 7. 终检
python scripts/quality_gate_check.py /tmp/ts/<report_id>
```

## 目录结构

见 `references/output_contract.md`。要点：

```
{report_id}/
  01_translation/full_translation.md
  02_strategy_logic/{strategy_summary.md, reference_implementation.py}
  03_strategy_evaluation/{evaluation_report.html, data/, charts/}
  04_backtest_strategy/{strategy.py, backtest_report.html, backtest_logs/}
  06_delivery/final_delivery_summary.md
  manifest.json
```

## 许可证

GPL-3.0
