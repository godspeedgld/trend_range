# SQL 查询模板

所有查询通过 `dai.query(sql).df()` 执行。

---

## 股票日线

```sql
-- 单只股票，指定日期范围
SELECT date, instrument, open, high, low, close, volume, amount, turn, change_ratio
FROM cn_stock_bar1d
WHERE instrument = '000001.SZ'
  AND date >= '2024-01-01' AND date <= '2025-06-30'
ORDER BY date

-- 多只股票
SELECT date, instrument, close, volume
FROM cn_stock_bar1d
WHERE instrument IN ('000001.SZ', '600000.SH', '000300.SH')
  AND date >= '2024-01-01'
ORDER BY date, instrument

-- 全字段
SELECT * FROM cn_stock_bar1d
WHERE instrument = '000001.SZ' AND date >= '2024-01-01'
```

---

## 期货日线

```sql
-- 指定合约
SELECT * FROM cn_future_bar1d
WHERE instrument IN ('AU2506.SHF', 'IF2506.CFX', 'IC2506.CFX')
  AND date >= '2024-01-01' AND date <= '2025-06-30'
ORDER BY date, instrument

-- 按品种代码过滤
SELECT date, instrument, close, volume, open_interest
FROM cn_future_bar1d
WHERE product_code = 'AU'
  AND date >= '2024-01-01'
ORDER BY date, instrument

-- 主力合约
SELECT * FROM cn_future_bar1d
WHERE instrument LIKE '%DOMINANT%'
  AND date >= '2024-01-01'
ORDER BY date, instrument
```

---

## 期货复权日线

```sql
SELECT *, close * adjust_factor AS close_adjusted
FROM cn_future_bar1d_adjust
WHERE instrument = 'AU_DOMINANT.SHF'
  AND date >= '2024-01-01'
ORDER BY date
```

---

## 基金日线

```sql
SELECT date, instrument, name, open, high, low, close, volume, amount, turn
FROM cn_fund_bar1d
WHERE instrument = '510050.SH'
  AND date >= '2024-01-01'
ORDER BY date
```

---

## A股1分钟（截面）

```sql
-- 注意：分钟数据量大，必须限制日期范围 + 品种
SELECT date, instrument, open, high, low, close, volume, amount
FROM cn_stock_bar1m_c
WHERE instrument = '000001.SZ'
  AND date >= '2025-06-01 09:30:00' AND date <= '2025-06-01 15:00:00'
ORDER BY date
```

---

## 期货1分钟（截面）

```sql
SELECT date, instrument, open, high, low, close, volume, amount
FROM cn_future_bar1m_c
WHERE instrument = 'AU2506.SHF'
  AND date >= '2025-06-01 09:00:00' AND date <= '2025-06-01 15:00:00'
ORDER BY date
```

---

## 交易日历

```sql
-- 日期范围
SELECT date, market_code
FROM all_trading_days
WHERE date >= '2024-01-01' AND date <= '2025-12-31'
ORDER BY date

-- 最新交易日
SELECT MAX(date) AS latest_trade_date FROM all_trading_days
```

---

## 指数日线

```sql
SELECT date, instrument, open, high, low, close, volume, amount
FROM cn_index_bar1d
WHERE instrument IN ('000300.SH', '000905.SH')
  AND date >= '2024-01-01'
ORDER BY date, instrument
```

---

## 常见条件

| 条件 | SQL |
|------|-----|
| 日期范围 | `date >= 'yyyy-mm-dd' AND date <= 'yyyy-mm-dd'` |
| 多品种 | `instrument IN ('A.SH', 'B.SZ')` |
| 品种过滤（期货） | `product_code = 'AU'` |
| 主力合约 | `instrument LIKE '%DOMINANT%'` |
| 排除停牌 | `volume > 0` |
| 分钟精确时间 | `date >= '2025-06-01 09:30:00'` |
