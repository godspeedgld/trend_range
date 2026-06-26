# Warehouse Playbook

Use this reference when implementing or reviewing Pandadata warehouse work. Keep exact API signatures in the `pandadata-api` skill or source Pandadata docs; this file defines local storage and operating conventions.

## Layout

Default root:

```text
~/.pandadata/warehouse/
  _meta.json
  catalog.duckdb
  trade_cal/
  stock_daily/
  stock_daily_pre/
  stock_daily_post/
  stock_min/
  index_daily/
  index_min/
  future_daily/
  future_daily_post/
  future_min/
  option_daily/
  hk_daily/
  us_daily/
  adj_factor/
  factor/
```

Recommended partition paths:

```text
trade_cal/exchange=SH/part.parquet
stock_daily/year=2026/part.parquet
stock_min/symbol=000001.SZ/year=2026/month=06/part.parquet
index_daily/year=2026/part.parquet
future_min/symbol=IF2606/year=2026/month=06/part.parquet
factor/factor_name=<name>/year=2026/part.parquet
```

Use one file per logical partition unless the dataset is too large for practical reads and writes. For large partitions, use deterministic shard names and record them in metadata.

## Metadata

Track one metadata record per table or table partition. Include:

- `table`: local table family.
- `source_method`: Pandadata method used to populate it.
- `partition_keys`: ordered partition key names.
- `primary_keys`: columns used to detect duplicates.
- `date_column`: source date or datetime field.
- `start_date` and `end_date`: local coverage as `YYYYMMDD` strings when the source uses trading dates.
- `last_refresh_at`: local timestamp with timezone when available.
- `row_count`: latest known row count for the partition.
- `schema`: source columns and local types when known.
- `status`: `ok`, `partial`, `failed`, or `needs_rebuild`.
- `notes`: stale-data, adjustment, retry, or repair notes.

Do not advance a partition watermark until the Parquet write, metadata write, and validation checks all succeed.

## Refresh Strategy

1. Resolve the latest completed trading day with the Pandadata calendar methods before assuming today's data exists.
2. Compare the local watermark with the requested end date and latest completed trading date.
3. Fetch only missing trading dates for append-stable datasets.
4. Rewrite the full affected partition for history-mutable datasets.
5. Write new data to a temporary file, validate it, then replace or append to the final partition path.
6. Rebuild or refresh DuckDB views after partition changes.
7. Record failed partitions in metadata without discarding successful work.

Append-stable examples:

- Unadjusted daily bars.
- Backward-adjusted daily bars when the API contract documents stable history.
- Trading calendars after the date range closes.
- Most daily index, futures, options, HK, and US bar datasets.

History-mutable examples:

- Forward-adjusted prices after dividends or corporate actions.
- Research factor tables whose provider revises prior values.
- Partitions repaired after duplicate-key or schema validation failures.

## DuckDB View Pattern

Use views over Parquet instead of copying raw data into DuckDB tables unless the user explicitly wants a materialized database.

```sql
CREATE OR REPLACE VIEW stock_daily AS
SELECT *
FROM read_parquet('~/.pandadata/warehouse/stock_daily/**/*.parquet', hive_partitioning = true);
```

When portability matters, resolve the warehouse root to an absolute path before creating the view. Use `union_by_name = true` only when schema drift is expected and documented.

## Validation Checklist

Run these checks after each refresh or repair:

- Parquet files exist for every expected partition.
- Required source columns are present.
- Date range covers the requested range and does not extend past the latest completed trading day unless the API explicitly supports realtime data.
- Primary key duplicates are absent within each partition.
- Row count is nonzero unless the source legitimately returns an empty result.
- A small sample matches fresh Pandadata API results. Prefer three symbols and three dates for broad bar tables.
- DuckDB can query the refreshed view and returns the expected date range.

If a check fails, mark the partition `partial` or `failed`, keep the previous valid data when available, and explain the retry or rebuild plan.

## Safety Rules

- Before destructive operations, list exact target files and expected replacement data.
- Preserve user-created warehouse paths and manifests unless explicitly asked to migrate them.
- Keep credentials out of warehouse metadata, Parquet files, logs, and generated reports.
- Warn before broad all-market minute downloads, because they can be slow and large.
- When an API call fails, distinguish credentials, network, method contract, empty data, rate limits, and local write failures.
