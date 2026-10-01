# Task Extractor

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/task_extractor.md`

## Identity

| Field | Value |
|-------|-------|
| id | `task_extractor` |
| agent | `aetheria` |
| category | `productivity` |
| cron | `0 17 * * *` |

## When

Daily at 17:00 — end-of-day commitments.

## How

1. Scan today's notes/threads/conversations for commitments and follow-ups.
2. Output tasks with owner, due hint, context link.
3. Deduplicate against open tasks; label new vs duplicate.

## Verify

- Tasks have owner + due hint.
- New vs duplicate labeled.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
End-of-day task extraction. Scan today's notes, threads, and conversations for anything that became a commitment, an action item, or a follow-up. Output a clean task list with owner, due hint, and context link where applicable. Deduplicate against existing open tasks and say which are new vs. duplicates.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
