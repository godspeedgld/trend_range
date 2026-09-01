---
name: python-bigquant-ssquant-tbquant
description: Convert local Python trading strategies to BigQuant (aistudio/bigtrader/dai), ssquant, or tbquant platform code. Use when the user asks to port/migrate/adapt a local backtest strategy to one of these platforms, write bigtrader initialize/handle_data code, build dai.query SQL for data fetching, or debug platform-specific strategy code.
---

# skill-python-bigquant-ssquant-tbquant — 本地 Python 策略 → 平台代码转换

**目的**：把本地 Python 回测策略转换为 **BigQuant**（aistudio + dai + bigtrader）、**ssquant**、或 **tbquant** 平台可运行代码。

## 目录结构

```
references/          # 平台语法参考文档（只读）
  bigquant/          # BigQuant 参考
    bq_trader.md     #   bigtrader 交易引擎（initialize/before_trading/handle_data、下单/查询接口、撮合规则）
    bq_dai.md        #   dai 数据平台（query/DataSource/表达式）
    bq_dai_fun.md    #   DAI SQL 函数列表（ta_*/m_* 等，策略指标优先 SQL 计算）
    bq_dai_sql_fqa.md#   DAI SQL FAQ（常见坑）
    bq_tables.md     #   数据表表头（cn_stock_bar1d / cn_stock_valuation / cn_stock_index_component / cn_stock_index_bar1d 等）
  ssquant/           # ssquant 参考（待补）
  tbquant/           # tbquant 参考（待补）
examples/
  bigquant/          # dai.query 示例 + bigtrader 组合策略完整示例
  ssquant/           # 待补
  tbquant/           # 待补
templates/
  bigquant/          # 三段 cell 结构的策略模板
outputs/
  bigquant/ ssquant/ tbquant/   # 转换产物输出目录
scripts/
  convert_local_html.py  # bigquant_references/ 本地 HTML wiki → references/bigquant/*.md
```

## 转换步骤（BigQuant）

本地策略 → BigQuant 一般两步：**数据获取/处理、引擎回测**。

### 1. 数据获取/处理
1. 提取原策略中的**数据集时长、标的、字段**；对照 `references/bigquant/bq_tables.md` 表头，
   确定哪些字段可以从 bigquant 数据表**直接获取**（如 open/close/high/low）
2. 再提取原策略中**不能从表直接提取**的字段（如 MACD/ATR 等指标，表里没有），
   **构造 SQL 计算语句**——两者都用 SQL 方式提取；指标计算 bigquant 一般用 SQL 实现
3. 数据查询和计算，bigquant 策略通过 **dai 模块 + SQL** 实现
4. **策略指标优先用 SQL 计算**（ta_*/m_* 函数），不要在 Python 里逐行算——参考 `examples/bigquant/`
5. 参考说明：
   - dai 模块用法 → `references/bigquant/bq_dai.md`
   - 函数列表 → `references/bigquant/bq_dai_fun.md`
   - SQL 常见问题 → `references/bigquant/bq_dai_sql_fqa.md`
   - 表头 → `references/bigquant/bq_tables.md`
6. 数据读取处理完后，**生成一张 DataFrame** 交给后续步骤
7. 如果 SQL 确实不能处理，再用 Python：SQL 读取计算生成 DataFrame 一个 cell，
   Python 处理再起一个 cell
8. **表名/字段名只能从 `references/bigquant/bq_tables.md` 中查证使用**，
   绝对不能擅自添加、创造或修改一个表或字段——不存在的表直接 Catalog Error，
   表里没有的指标一律用 SQL 从已有字段推导（见第 2 条），而不是虚构字段

### 2. 引擎回测
1. 根据原策略，提取**开仓规则 / 平仓规则 / 仓位规则 / 优先级规则**等规则；
   规则中**可以预计算的部分都优先预计算**（信号表、指标、日期集合等）
2. bigquant 的预计算**放在 SQL 中效率更高**，SQL 放不了就放在 Python 里
3. 初始化（initialize）获取数据，或把之前 cell 计算好的 DataFrame 设成 `context.data`
4. 初始化设置交易费用、持仓数量、持仓时间等参数
5. `handle_data` 根据**开仓/平仓/仓位/优先级**等规则调整仓位

引擎回调与下单接口细节 → `references/bigquant/bq_trader.md`

### 3. 策略结构（aistudio = Jupyter Notebook）
回测策略分三部分 cells（划分原则 = 降低重复计算）：
1. **定义 cell**：导入包、起止时间、常量
2. **数据获取/处理 cell(s)**：可预计算的都预计算（BigQuant 一般用 SQL 预计算）→ 生成大 DataFrame；
   SQL 能完成的构成一个 cell，需要 Python 的再一个 cell
3. **回测 cell**：开仓/平仓/优先级/仓位规则写进 trader 引擎回调函数

每部分可以是多个 cell。参考模板：
- **`templates/bigquant/portfolio_strategy_template.ipynb`（组合策略首选）**——池式开仓组合策略
  的完整骨架（取数/指标兜底/事件预计算/六步 handle_data/诊断导出），2026-09-01 strategy_006
  三轮对账收敛后的已验证写法（含 pending 确认、拒单回池、成分 asof、暖期闸），策略特定处
  以 TODO 标记；首 cell 含**本地引擎参数语义对照表**与数据流纪律。
- `templates/bigquant/strategy_template.ipynb`——历史示例（分钟因子）。

## 移植 checklist

1. **指标口径对表**：本地凡用 rolling/ewm 的指标（ATR/均线/布林等），移植前必须查
   `references/bigquant/bq_dai.md` 的等价 SQL 确认口径（SMA vs Wilder vs EMA），
   禁止假设"应该一样"；平台函数口径与本地不一致时，一律走 Python 兜底重算。
   ⚠ 实证教训（strategy_006 分歧复盘 2026-09-01）：`m_ta_atr` = `m_avg(TR)` =
   **SMA 口径**，与本地 pandas Wilder `ewm(alpha=1/14)` 在 TR 突变期（暴跌/暴涨转折）
   差 3~16%（实测中兴 000063 2017-11-30：Wilder 31.74 vs SMA 36.73），足以翻转贴线
   吊灯止损判定——"仅 warmup 初始化不同、差异<0.1%"是错误断言，勿再犯。
2. **本地引擎参数语义冻结**：移植前逐个确认本地回测引擎参数的真实语义再翻译
   （例：`--warmup 60` 是"全市场回测前 60 个交易日禁开仓 + 个股≥60 bar"双重语义，
   译成"仅个股≥60 bar"会凭空多出暖期交易）。完整对照表见
   `templates/bigquant/portfolio_strategy_template.ipynb` 首 cell。
3. **执行层差异显式声明**：bigtrader 为真实现金账户（拒单/部分成交/涨跌停/退市），
   本地引擎多为虚拟记账（固定名义可透支、未成交保留池）——产物头部 markdown 必须列出
   已知差异清单；未成交/拒单语义尽量向本地对齐（信号留池重试，而非直接丢弃）。
4. **数据流纪律（单一 panel）**：所有派生数据（指标/事件/透视）必须从**同一个**
   `_ensure_indicators` 处理后的 panel 派生，禁止原始 panel 与处理后 panel 并存。
   ⚠ 实证教训：Wilder 重算只发生在 build_signals 内部 copy、`build_pivots` 仍拿 SQL
   的 SMA 口径 → 吊灯长期不触发（44 笔平仓分叉全部"云端晚卖"、修复形似无效的根因）。

## 移植验收（对账）——产物必须过验收才算完成

云端跑完策略后**必须**跑产物尾部的诊断导出 cell（模板 Cell 5），下载 `cloud_export/`
目录，本地跑标准工具七层对账：

```
python scripts/parity_check.py --cloud-export <cloud_export目录> \
  --panel <本地面板.parquet> --events <本地事件.parquet> \
  --warehouse <bigquant_warehouse.duckdb> --index-code 000300.SH \
  --cloud-trades <云端成交csv> --local-trades <trades_paired.csv>
```

分层定位：L1/L2 差 → 原始数据（复权/数据源）；L3 差 → 事件表；L4/L5/L6 差 →
闸门/指数/成分；全 PASS 而交易分歧 → 撮合/资金执行层。

**验收标准（strategy_006 实证基线）**：L1~L6 偏差浮点级（<1e-9）；L7 平仓同步率
（±3 天）≥95% 且同步笔收益差 <1pp（≈佣金口径）；分叉笔方向不单边倒——
**全晚卖 = 指标口径偏松或兜底未传导到 pivot，全早卖 = 口径偏紧**（单边倒必是 bug，
双向才是随机执行分歧）。

## 铁律：严禁未来数据

- 回测代码生成时**严格审查未来数据**的使用
- 股票交易严格采用 **t 时刻收盘计算/分析指标 → 产生调仓信号 → t+1 开盘执行**
- 股票/期货/期权在 t 时刻计算数据产生交易信号时，只能用 **t 时刻之前的已知数据**

## 输出

- bigquant转换产物写到 `outputs/bigquant/` 下，**必须是标准 `.ipynb` 文件**（aistudio = Jupyter Notebook）：
  - 模块 docstring / 策略说明 → 首个 **markdown cell**；每个 `# %%` 分段 → 一个 **code cell**
  - **禁止**输出带 `# %%` 分段的 `.py` 冒充 notebook；本地校验脚本需要加载产物时，
    用 json 读 ipynb 拼接 code cells 后 `exec` 成模块（见 `outputs/bigquant/_local_parity_check.py`）

## 参考文档维护

`references/bigquant/*.md` 由 `scripts/convert_local_html.py` 从 `bigquant_references/` 本地
HTML 快照转换生成；远程 wiki 为最新版（bq_trader: bigquant.com/wiki/doc/nxDOuIdhm2 等，见各 md 头部链接）。
⚠ 手工补注（如 bq_dai_fun.md 中 m_ta_atr 的口径警示）**不来自 HTML 源**——重新运行转换脚本后
须检查补注是否被覆盖，被覆盖则按 SKILL.md 移植 checklist 第 1 条的实证数据重新补上。
