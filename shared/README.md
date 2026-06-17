# shared

本目录存放**跨策略复用**的通用代码，供趋势跟踪、震荡、综合三类策略共同使用，避免重复实现。

## 建议结构

```
shared/
├── data/          # 数据加载与清洗（可封装 ssquant 的行情接口）
├── indicators/    # 公共技术指标（MA、ATR、动量、布林等）
├── utils/         # 回测、绩效统计、绘图等工具
└── base/          # 策略基类与通用接口
```

## 与 ssquant 的关系

[../ssquant](../ssquant) 作为 git submodule 提供 K 线、行情、内置指标等基础能力；
`shared/` 在其之上封装本项目统一使用的数据与工具层。
