# Service Crash Watch

> Rakazo-style routine doc: readable, editable, commit-able.
> Override locally: `$SOVERYN_DATA_ROOT/automations/routines/service_crash_watch.md`

## Identity

| Field | Value |
|-------|-------|
| id | `service_crash_watch` |
| agent | `aetheria` |
| category | `ops` |
| cron | `*/30 * * * *` |
| monitor | `automations/watches/systemd_health.txt` |

## When

Every 30 minutes, around the clock. House services do not keep business hours.

## How

1. Read the MONITOR block. It is the source of truth: user units that are
   failed, stuck in activating (start-pre), or above the restart threshold.
2. If the block shows problems: one line per unit — name, state, restart
   count — plus the single most likely fix (the restart command or the
   missing upstream port).
3. If the diff shows a unit recovered, or the block is empty: one short
   all-clear line naming the unit.
4. Do not speculate beyond the block. Never restart services yourself.
   Report only; Jon or Kernel takes the action.

## Rules

- Under 120 words. A pager message, not an essay.
- No restarts from the chat seat. Reporting is the whole job.
- Repeats of the same unit get shorter each time: name, state, "still down,
  last said X".

## Example output

```
soveryn-representation: activating (start-pre) for 12m, 3 restarts.
Likely: upstream :8091 not ready. Restart: systemctl --user restart
soveryn-representation.service after checking the router unit.
```

## Verify

- Routine fires every 30 minutes and the MONITOR block is non-empty only
  when a real unit is failed, activating, or over the restart threshold.
- Output names each affected unit once, states the most likely fix, and
  never restarts anything itself.
- An empty MONITOR block after a problem produces exactly one all-clear
  line, then silence.
