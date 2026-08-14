# 数据源规则（data_sources.md）

## 外部提供，技能不下载（核心规则）

- 行情数据由用户**以外部本地路径**提供：`local_backtest.py --market-data <CSV/Parquet>`。
- **本技能本身绝不下载行情数据**（不内置取数 API/爬虫）。可用配置文件指向本地数据或远程数据 API（技能读取）。
- 引擎需 OHLC（date/symbol/open/high/low/close[+volume]）——止损/止盈判断用 high/low。

## 数据合法性检查（5.1.2，必做）

技能必须检查数据合法性，不合格则中文写明卡点、结论降级：
- **NaN 处理**：是否有未处理的 NaN？是否已 fillna/dropna？
- **复权**：是否前复权/后复权？混用会导致信号失真。
- **价格正负**：open/high/low/close 是否均 > 0？
- **时序**：是否按 date 升序？是否有重复 (date,symbol)？
- **可用时点**：信号在 close[t] 决策，成交在 t+1（或 close[t]），防前视。
- **覆盖率**：样本区间内数据是否完整？缺失区间标注。

## 溯源记录（manifest.json）

在 manifest.data_sources 记录：数据提供方/文件源、本地路径、品种/宇宙、样本区间、频率、复权规则、可用时点假设、缺失值处理。

## 禁止数据

禁止用合成/mock/随机生成的行情证明策略有效。定种随机信号仅可作阴性对照基准，在同一份真实收益数据上运行。

## 数据不足时

保留对应必需章节、中文写明卡点、结论标 `inconclusive`、必要时建 `failure_report.md`。
