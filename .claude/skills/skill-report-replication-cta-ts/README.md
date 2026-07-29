# skill-report-replication-cta-ts

**AI 复现 CTA 研报/论文**：把一篇时序 CTA / 趋势研报或论文，转化为完整复现包。两类价值：

1. **量化方法提取（头条）**：按 regime/指标分析/多指标融合/止盈止损/风控 分类提取，每方法含 思路/原理/公式/推导/优缺点 + 衍生方法 + 参考资料 + 未来 → `02_approach/main_approach.md`。**可迁移、可复用，比回测更重要。**
2. **实证回测验证**：事件驱动引擎（开仓+止盈止损+策略逻辑即时触发，ATR 吊灯止损用 high/low 命中价成交）→ `03_backtest_strategy/`。

## 与其他 skill 的区别

| skill | 用途 |
|-------|------|
| **-cta-ts**（本） | 时序 CTA 研报：方法提取 + 事件驱动回测 |
| -factor | 截面因子研报（IC/分位/多空） |
| -ts |（旧，待废弃）| cta-ts 的前身 |

## 输入 / 数据

- 输入：🌐 网页 URL / 📄 本地 PDF / 📝 文本
- 数据：外部本地路径 `--market-data`，**技能不下载**（配置指向本地/远程 API，技能读取 + 合法性检查）

## 工作流（7 步）

1. Initialize（create_project）2. Translate（非中文）3. **Extract Quant Methods**（头条）4. Extract Backtest Features 5. Backtest（事件驱动引擎）6. Final Report 7. Quality Gate

门禁：`check_translation` / `check_approach` / `check_strategy` / `quality_gate_check`。可手动跳过步骤。

## 抽取默认值（研报未明确时）

regime=无 ｜ 开仓=双均线 ｜ 止盈止损=ATR 吊灯 ｜ 仓位=满仓 ｜ 优化=网格

## 用法

```bash
python scripts/create_project.py --title "华泰时序CTA方法论" --source "https://..."
# 由 Claude 按 7 步产出各产物
python scripts/quality_gate_check.py {root}/{report_id}
```

输出根：`REPLICATION_ROOT`(.env) > 云环境 > `~/report-replication`；可 `--root` 覆盖。

## 许可证

GPL-3.0
