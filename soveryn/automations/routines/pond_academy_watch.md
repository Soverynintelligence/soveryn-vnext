# Pond Academy Watch

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/pond_academy_watch.md`

## Identity

| Field | Value |
|-------|-------|
| id | `pond_academy_watch` |
| agent | `eve` |
| category | `ops` |
| cron | `0 7 * * *` |
| monitor | `data/automations/watches/pond_academy.txt` |

## When

Daily at 07:00 local — goldfish watch: **no LLM if the watch file hash is unchanged**.

## How

1. Scheduler hashes `$SOVERYN_DATA_ROOT/automations/watches/pond_academy.txt`.
2. Missing or empty file → persist empty baseline, skip the model (no inbox ping).
3. Unchanged hash → `no_change`, skip the model.
4. Changed (or first non-empty observation) → inject MONITOR CHANGE / baseline and run Eve.
5. Eve reports only what changed for CWG / pond / academy-class content. Use `cron_notepad` for a cursor.

Drop competitor snapshots, academy pages, or price-sheet excerpts into that watch file when you want a tick to spend tokens.

## Verify

- Unchanged file does not call the model and does not fill CC inbox.
- A real change produces a short delta, not a restatement of the whole file.
- No invented prices.

## Prompt (source of truth in catalog)

```
Pond Academy watch for CWG. The MONITOR block is the source of truth for this tick — do not invent a page that was not in it. Report only what changed for pond work, competitors, or academy-class training/content. If the change is noise, say so in one line. Use cron_notepad to keep a short watchlist/cursor. No prices unless they appear in the monitor output.
```

## Delivery

- Default surface: **Command Center inbox** (`command_center`)
- Signal: preview-only until `signal_live_armed`
- Acked failures: same error signature stays silent until the error text changes
