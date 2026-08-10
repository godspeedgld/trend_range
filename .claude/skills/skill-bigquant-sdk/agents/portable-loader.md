# BigQuant SDK Skill — Portable Loader

Load this skill in the agent runtime by pointing it at the skill root:

```
.claude/skills/skill-bigquant-sdk/
```

The runtime MUST read `SKILL.md` first, then use `references/data_tables.md` for table lookups and `scripts/call_api.py` for data fetching.

This skill uses the `bigquant` Python SDK (install with `pip install bigquant -U`). First-time use requires browser-based OAuth login.
