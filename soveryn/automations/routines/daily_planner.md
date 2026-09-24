# Daily Planner

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/daily_planner.md`

## Identity

| Field | Value |
|-------|-------|
| id | `daily_planner` |
| agent | `aetheria` |
| category | `productivity` |
| cron | `30 8 * * *` |

## When

Daily at 08:30 — right after AI digest.

## How

1. Pull open tasks, meetings, due/overdue.
2. Propose a focused top-3 with rough time blocks.
3. Mark what can slip; name the one must-happen for the day to count.
4. Be opinionated — do not re-list the inbox.

## Verify

- Top-3 present with time blocks.
- One named must-happen.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Build today's plan for Jon. Pull from: open tasks, scheduled meetings, and anything due today or overdue. Propose a focused top-3 with rough time blocks, mark what can slip, and name the one thing that must happen for the day to count. Be opinionated; do not just re-list the inbox.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
