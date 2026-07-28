# Data Source Rules（时序 CTA）

策略复现与回测必须使用真实、可溯源的数据。

## 外部本地路径，技能不下载（核心规则）

- **行情数据由用户以外部本地路径提供**：`local_backtest.py --market-data <CSV/Parquet 路径>`。
- **本技能本身绝不下载行情数据**（不内置任何数据 API、爬虫、网络取数）。
- 若需 OHLC（止损/止盈判断），行情文件可含 `open/high/low/volume`，由 `strategy.py` 读取。
- 路径/来源/品种/区间/复权/可用时点假设 必须记录在 `manifest.json` 与评估报告中。

## Required Provenance

在 `manifest.json` 与 HTML 报告中记录：

- 数据提供方或文件来源。
- 本地文件路径 / URL / 数据库路径 / 回测配置来源。
- 品种/宇宙。
- 样本区间。
- 频率。
- 复权规则。
- 数据可用时点 / 发布时点假设（用于防前视）。
- 缺失值处理。

## Prohibited Data

禁止用合成 / mock / 随机生成的行情数据证明策略有效。

定种随机信号仅可作"阴性对照"基准，在同一份真实收益数据上运行，绝不可替代真实行情。

## Insufficient Data

数据不足以支撑研报策略测试时：

- 保留对应必需章节。
- 中文写明具体卡点。
- 结论标 `inconclusive`。
- 项目无法继续时建/更新 `failure_report.md`。
