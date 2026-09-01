# Paper Watch

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/paper_watch.md`

## Identity

| Field | Value |
|-------|-------|
| id | `paper_watch` |
| agent | `eve` |
| category | `research` |
| cron | `0 9 * * 3` |

## When

Wednesdays at 09:00 — mid-week research.

## How

1. Scan new papers in agent systems, LLM inference/efficiency, evaluation.
2. Shortlist max 5: contribution, why it matters, assumption change?
3. Skip incremental work with no takeaway.

## Verify

- ≤ 5 papers; each has takeaway.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Mid-week paper watch. Review new papers in the tracked research areas (agent systems, LLM inference/efficiency, and evaluation). For each shortlisted paper: one-line contribution, why it matters, and whether it changes a current assumption. Shortlist max 5, skip incremental work with no takeaway.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
