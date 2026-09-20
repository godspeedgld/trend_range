---
name: skill-financial-statement-analysis
description: 解析东方财富导出的上市公司财务四表（利润/资产负债/现金流/综合能力，.xls 季度面板），按六维度框架生成单文件 HTML 分析报告（本地 plotly，零 CDN）。Use when 用户给出东财财务报表 Excel（常见于 quant_doc 下的四表目录）要求做财务分析/出报告。
---

# skill-financial-statement-analysis — 东财四表财务分析

把东方财富导出的**四张 .xls**（利润表 / 资产负债表 / 现金流量表 / 公司综合能力表，
同一日期轴、40+ 期季度、最新期在前）解析成统一面板，按六维度生成带可视化分析报告。

## 快速用法

```bash
PY=/c/Anaconda/envs/quant_env_311/python.exe
# ① 解析（--dir 指向含四表 .xls 的目录；输出面板 + meta.json）
$PY .claude/skills/skill-financial-statement-analysis/scripts/parse_eastmoney_xls.py \
    --dir "<四表目录>" --out <面板目录>
# ② 生成报告（单文件 HTML，双击即开）
$PY .claude/skills/skill-financial-statement-analysis/scripts/build_report.py \
    --panel <面板目录> --out <报告.html> --profile bank
```

`--profile bank|general`：银行科目映射见 `references/metrics_bank.md`（首批落地）；
general（毛利率/周转率体系）为占位，遇到非银数据时补。

## 六维度（定义见 references/framework.md）

1. **成长性**：营收/归母净利 YTD 同比 + 单季差分序列
2. **盈利质量**：ROE/净利率 + 经营现金流÷净利润（银行：仅跟踪）
3. **偿债与资本**：银行=资本充足率三档（7.5/10.5 参考线）
4. **效率与资产质量**：NIM / 收入成本比 / 不良率 / 拨备覆盖率
5. **勾稽与信号**：fraud-index 三桶纪律（明确异常/弱信号/缺失数据）+ 单季突增扫描
6. **指标全景**：综合能力表核心项矩阵

## 口径铁律（最容易错的地方）

- 利润表/现金流量表是 **YTD 累计**：同比=同财年同期比；单季=年内差分
- 资产负债表/综合能力表是**时点/当期比率**：不做差分
- 值清洗：'--'→缺失、'62.72%'→62.72、千分位逗号、`\xa0` 尾巴
- **宁缺毋错**：源缺的季度字段（贷款总额/员工人数常见）显示"—"；解析层带抽查断言
  （打印首末期与东财原表比对）——旧版 sparkline 技能手抓错列（206.71 vs 真实 706.17）的教训

## 设计来源（为什么长这样）

- 框架骨架：借 DB-GPT 版 financial-report-analyzer 的四维度 + HTML 结构
- 信号纪律：借 financial-fraud-index 的三桶分类
- 数据层：全新（xlrd 读 .xls + 布局假设按东财实际格式写死）
- 可视化：plotly 本地 vendor（沿用 cs-trend-train 方案，`assets/plotly.min.js`）

## 文件

| 路径 | 作用 |
|---|---|
| `scripts/parse_eastmoney_xls.py` | 四表 → panel_*.parquet + meta.json（含抽查断言） |
| `scripts/build_report.py` | 面板 → 六维度计算 → 单文件 HTML |
| `references/framework.md` | 六维度 + 口径铁律 + 三桶纪律 |
| `references/metrics_bank.md` | 银行科目映射 + 行业解读常识 |
| `assets/plotly.min.js` | 本地可视化引擎（build 时自动拷一份到报告旁边，`报告.html + plotly.min.js` 两个文件一起移动/分享） |
