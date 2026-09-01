# Weekend Deep Dive

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/weekend_deep_dive.md`

## Identity

| Field | Value |
|-------|-------|
| id | `weekend_deep_dive` |
| agent | `eve` |
| category | `research` |
| cron | `0 10 * * 6` |

## When

Saturdays at 10:00 — one deep question.

## How

1. Pick the single most important open technical question this week.
2. SOTA, 2–3 approaches, trade-offs, concrete recommendation.
3. Include an experiment that would resolve it — actionable Monday.

## Verify

- One question; recommendation + experiment.
- Monday-actionable.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Weekend deep dive. Pick the single most important open technical question for the house this week and go deep: lay out the current state of the art, the 2-3 credible approaches, trade-offs, and a concrete recommendation with an experiment that would resolve it. Aim for something Jon can act on Monday, not a survey.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
