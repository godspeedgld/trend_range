# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does not natively discover `SKILL.md` folders.

```text
You have access to a local skill named pandadata-warehouse at:
<PANDADATA_WAREHOUSE_SKILL_ROOT>

When the user asks to cache Pandadata or panda_data results locally, build or repair a DuckDB/Parquet warehouse, run incremental refreshes, validate local partitions, or query downloaded market data with SQL:
1. Read <PANDADATA_WAREHOUSE_SKILL_ROOT>/SKILL.md.
2. Read <PANDADATA_WAREHOUSE_SKILL_ROOT>/references/warehouse-playbook.md before designing tables, writing refresh code, rebuilding partitions, or deciding validation rules.
3. Use the Pandadata API skill or local API docs to confirm exact panda_data.get_* signatures before coding or running API calls.
4. Preserve source field names, partition conventions, metadata watermarks, validation rules, and freshness notes from the skill files.
5. Never delete, overwrite, or rebuild existing partitions unless the user explicitly confirms the exact affected files and action.
6. Do not invent credentials, API parameters, factor definitions, destructive repair permission, or runtime behavior that is not supported by the skill files.
```
