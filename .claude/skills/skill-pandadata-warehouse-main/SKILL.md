---
name: pandadata-warehouse
description: Build, repair, query, and maintain a local Pandadata market-data warehouse backed by DuckDB and Parquet for repeat quant research, backtests, factor studies, and batch reports. Use when the user asks to cache Pandadata or panda_data results locally, create or update a local market-data database layer, perform incremental data refreshes, query downloaded data with DuckDB SQL, design table partitions and watermarks, validate local data against Pandadata APIs, or avoid repeated Pandadata API calls.
license: GPL-3.0-only
metadata:
  organization: QuantSkills
  organization_url: https://github.com/quantskills
  repository: skill-pandadata-warehouse
  repository_url: https://github.com/quantskills/skill-pandadata-warehouse
  project_type: skill
  collection: pandadata-warehouse
  creator: abgyjaguo
  creator_url: https://github.com/abgyjaguo
  maintainer: abgyjaguo
  maintainer_url: https://github.com/abgyjaguo
quantSkills:
  project_type: skill
  category: data-api
  tags:
    - pandadata
    - warehouse
    - duckdb
    - parquet
    - data-engineering
  platforms:
    - claude-code
    - codex
    - openclaw
    - cursor
  status: stable
  requires:
    - skill-pandadata-api
  validation_level: runnable
  maintainer_type: community
  summary_zh: "Pandadata 本地数据仓库：用 DuckDB 与 Parquet 缓存、增量刷新、查询和校验行情数据，减少重复 API 调用。"
  summary_en: "Pandadata warehouse skill for caching, refreshing, querying, and validating local DuckDB and Parquet market-data stores."
---

# Pandadata Warehouse

Use this skill to design and operate a local Pandadata warehouse for heavy data reuse. Keep the warehouse faithful to Pandadata source fields, store raw data in partitioned Parquet, expose query views through DuckDB, and refresh only the missing trading periods unless a table requires a full partition rewrite.

## Workflow

1. Clarify the user's target scope: asset class, table family, symbol universe, date range, frequency, warehouse path, and whether the request is initialize, refresh, query, validate, or repair.
2. Load `references/warehouse-playbook.md` before designing tables, writing refresh code, rebuilding partitions, or deciding validation rules.
3. Use the `pandadata-api` skill or local Pandadata documentation to confirm exact `panda_data.get_*` method names, parameters, response fields, credentials, and date formats before writing or running API calls.
4. Keep raw warehouse data close to the API contract. Preserve source column names and types when practical; place derived calculations in downstream analysis views or reports.
5. Store Parquet under a stable warehouse root, defaulting to `~/.pandadata/warehouse`, and keep metadata such as source method, partition keys, date coverage, row counts, refresh time, and validation status in `_meta.json` or an equivalent manifest.
6. Create or refresh DuckDB views that read the Parquet partitions with `read_parquet`, then run downstream analysis through SQL against the local view layer.
7. Validate each material refresh by checking row counts, date ranges, duplicate keys, partition coverage, and a small sample against fresh Pandadata API results.
8. Report any missing credentials, unavailable SDK, failed partitions, stale datasets, or destructive repair actions clearly before continuing.

## Supported Warehouse Families

Use this skill for these local table families unless the user narrows the scope:

| Family | Typical source methods | Default partition |
|---|---|---|
| Trading calendar | `get_trade_cal`, `get_last_trade_date` | exchange |
| A-share daily bars | `get_stock_daily` and adjusted daily variants | year |
| A-share minute bars | `get_stock_min` | symbol and month |
| Index bars | `get_index_daily`, `get_index_min` | year or month |
| Futures bars | `get_future_daily`, adjusted futures daily variants, `get_future_min` | year or month |
| Options bars | `get_option_daily` | year |
| HK/US daily bars | `get_hk_daily`, `get_us_daily` | year |
| Adjustment factors | `get_adj_factor` | year |
| Research factors | `get_factor` | factor name and year |

Treat the method list as a routing map, not an API contract. Confirm the exact method details with `pandadata-api` before coding.

## Core Rules

- Prefer incremental refreshes keyed by the latest completed trading date. Use full partition rewrites only for datasets whose history can change, such as forward-adjusted prices.
- Do not run broad minute-bar or all-market downloads unless the user explicitly supplies a symbol universe or confirms the expected size.
- Never delete, overwrite, or rebuild existing partitions silently. First list the affected files, explain why the rebuild is needed, and get explicit confirmation unless the user already authorized that exact destructive action.
- Keep failed downloads resumable. Record failed partitions and leave successful partitions intact.
- Make freshness visible in answers and generated code: include source method, last local date, latest API/trading date checked, and any stale-data warning.

## Maintainer, License, and Limits

- Created and maintained by `abgyjaguo` for the QuantSkills community in the `quantskills/skill-pandadata-warehouse` repository.
- Licensed under GNU GPL v3.0 only (`GPL-3.0-only`); keep the root `LICENSE` file with the full GPLv3 text when publishing or packaging.
- Treat outputs as data engineering and research support, not investment advice. Do not promise returns, profitability, production readiness, certification, or official endorsement.
- Keep credentials, API tokens, private datasets, and confidential material out of examples, metadata, logs, warehouse files, and generated reports.

## Runtime Compatibility

- Codex: use this `SKILL.md` directly and `agents/openai.yaml` for UI metadata.
- Cursor: use `agents/cursor-rule.mdc` as the project rule/loader.
- Claude Code, Hermes, and OpenClaw: use `agents/portable-loader.md` to point the runtime at this skill root and require it to read `SKILL.md` first.
- Keep runtime-specific files as thin adapters. Update this file first when behavior changes, then sync the adapters so they do not contradict the canonical workflow.
