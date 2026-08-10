# BigQuant SDK — 数据获取与本地存储

把自然语言数据需求路由到 BigQuant DataSource / dai API，拉取行情数据并保存到本地。

## 核心能力

- **数据获取**：通过 `DataSource().read()` 拉取期货/股票日线、分钟线、因子等数据
- **本地存储**：保存为 Parquet / CSV
- **SQL 查询**：通过 `dai.query()` 在 BigQuant 云端执行 SQL（可选）

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 拉取期货日线数据
python scripts/call_api.py \
  --table bar1d_CN_FUTURE \
  --instruments AU2506.SHF \
  --start 2024-01-01 --end 2025-06-30 \
  --output ./au_daily.parquet \
  --format parquet

# 拉取A股日线
python scripts/call_api.py \
  --table bar1d_CN_STOCK_A \
  --instruments 000001.SZ,600000.SH \
  --start 2024-01-01 --end 2025-06-30 \
  --output ./stocks.parquet
```

## 目录结构

```
skill-bigquant-sdk/
  SKILL.md              # AI agent 主指令
  README.md             # 人类阅读
  requirements.txt      # Python 依赖
  scripts/
    call_api.py         # CLI 数据拉取工具
    bigquant_runtime.py # SDK 运行时引导
  references/
    data_tables.md      # 数据表目录（字段+示例）
    api_reference.md    # API 详细文档
  agents/               # 多平台适配
```

## 数据表支持

| 表 ID | 说明 |
|-------|------|
| bar1d_CN_FUTURE | 期货日线行情 |
| bar1d_CN_FUTURE_adjust | 期货复权日线 |
| bar1d_CN_STOCK_A | A股后复权日线 |
| bar1d_CN_STOCK_A_adjust | A股前复权日线 |
| bar1d_CN_INDEX | 指数日线 |
| cn_stock_prefactors_community | 预计算因子社区版 |

详见 `references/data_tables.md`。

## 首次使用

1. `pip install bigquant -U`
2. 去 BigQuant 控制台获取 AK/SK：https://bigquant.com/account/settings
3. 配置凭据到 `~/.bigquant/config.json`：

```json
{
  "auth": {
    "ak": "your_access_key",
    "sk": "your_secret_key"
  }
}
```

## 与 Pandadata 的差异

| 维度 | BigQuant | Pandadata |
|------|----------|-----------|
| 日期格式 | yyyy-mm-dd | YYYYMMDD |
| 期货代码 | IF2506.CFX | IF_DOMINANT.CFX |
| 认证 | AK/SK 密钥对 | username/password |

## License

GPL-3.0-only
