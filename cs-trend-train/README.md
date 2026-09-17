# cs-trend-train — 手动趋势画线交易训练工具

在 K 线图上手工画趋势线、记录交易（买入/止损/止盈），支持自动按后续行情判定平仓
（止损 / 止盈 / 吊灯 = 最高价 − 3×ATR14）。像 TradingView 一样画线，但线和交易记录
落在本地 JSON，可反复加载复盘。

## 启动

```bash
python cs-trend-train/server.py
# → http://127.0.0.1:8710   （默认标的 中国平安，2025-01 ~ 2026-08）
```

零第三方 web 依赖（标准库 http.server）；数据读本地 DuckDB warehouse。

## 功能对照

| 需求 | 实现 |
|---|---|
| K 线：滚轮缩放 / 左键拖动 | klinecharts v10 内置（默认开启） |
| 画线：两点画 / 拖动 / 右键删除 | overlay 内置交互；`✏ 画趋势线` 进入绘制模式 |
| 画线记录 | `data/lines.json`（标的/起止日期价格/复权状态 hfq）；加载标的时重建 |
| 交易录入 | 右侧面板：买入/止损/止盈/（可选）实际平仓价 |
| 自动平仓 | 留空平仓价 + 勾「自动判定」→ 后端逐日模拟：止损/止盈/吊灯(收盘 < 最高−3×ATR14前一日) |
| 交易标注 | ▲买 / 绿虚线止损 / 红虚线止盈 / ▼平仓（按原因着色） |
| 标的选择 | 输入代码或名称（模糊搜索下拉），默认 601318.SH 中国平安 |
| 时间选择 | 起/止日期选择器，默认 2025-01-01 ~ 2026-08-31 |
| 播放 | `◀10 ◀1 ▶1 ▶10`（结束时间前后移动，逐根复盘） |
| 未来遮蔽 | 线/交易终点晚于当前最后 bar 则不显示（训练时"看不见未来"） |
| 加载开关 | 工具栏「线」「交易」两个 checkbox |

## API

| 端点 | 说明 |
|---|---|
| `GET /api/symbols?q=` | 代码/名称模糊搜索 |
| `GET /api/klines?symbol=&start=&end=` | K 线 + ATR14 + 原始价（后复权为主口径） |
| `GET/POST/DELETE /api/lines?symbol=` | 画线记录 CRUD |
| `GET/POST/DELETE /api/trades?symbol=` | 交易记录 CRUD（POST 带 `auto:true` 触发自动平仓判定） |

## 数据

- 行情：warehouse `stock_bar1d`（后复权；`raw` 字段 = 后复权 ÷ adjust_factor）
- ATR14：Wilder ewm(α=1/14)（与 hs300 工程 `shared/atr14_precompute.py` 同式）
- 记录：`data/lines.json` / `data/trades.json`（按标的分组，肉眼可查可手改）
