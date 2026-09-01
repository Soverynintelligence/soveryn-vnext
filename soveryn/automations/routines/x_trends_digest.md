# X Trends Digest

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/x_trends_digest.md`

## Identity

| Field | Value |
|-------|-------|
| id | `x_trends_digest` |
| agent | `eve` |
| category | `news` |
| cron | `0 12 * * *` |

## When

Daily at 12:00 — midday pulse on X.

## How

1. Identify 3–5 driving threads in AI/ML + developer tooling.
2. Who is driving them; real shift vs spike.
3. Flag product implications; no engagement bait or verbatim dump.

## Verify

- 3–5 threads; shift vs spike called out.
- No verbatim thread dumps.
- Lands in CC inbox.

## Prompt (source of truth in catalog)

```
Summarize what is trending on X in AI/ML and developer tooling right now. Identify the 3-5 threads driving conversation, who is driving them, and whether they represent a real shift or a spike. Flag any trend with product implications for the house. No engagement bait, no restating thread content verbatim.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Approval Gate: read tools auto-approved for `source=automation`; writes stay gated
