# Shepherd Missed/Overdue — Full-Lifecycle Obligation Tracking (Design)

**Date:** 2026-06-26
**Status:** Approved design (brainstormed + green-lit).
**Builds on:** [[project_soveryn_shepherd_fcc_build]] — the deterministic engine + dashboard + the compliance agent. Repo `~/shepherd`.
**Concept:** Shepherd currently only surfaces *upcoming* deadlines. For a "never miss a deadline" tool, that's a blind spot exactly where the fine lives — a missed filing means the penalty already triggered and the owner needs to remediate *now*. This adds the missed/overdue lane: the engine looks **back** as well as forward, and a "mark filed" acknowledgment overlay distinguishes what was **Done** from what was genuinely **Missed**.

## Decisions (from brainstorming)

- **Unified lifecycle:** surface overdue/missed AND let the owner mark items "filed" — built together (so a past-but-filed deadline shows **Done**, not a false MISSED). This folds in the previously-designed "address obligations" feature.
- **Lookback:** ~1 year back (fixed default) — covers recent quarterly filings + a recent renewal, the window where an un-remediated miss still matters. Not per-station configurable (YAGNI).
- **Engine stays pure:** the engine computes instances + a *temporal* status from dates alone; it NEVER reads acknowledgments. "Did you file it?" is a separate overlay.
- **Backward-compatible:** the engine change is opt-in (`lookback_days` defaults to 0), so existing forward-only callers are unaffected.

## The honesty spine (intact)

- **Overdue/missed dates are real, engine-computed past dates** — authoritative, just in the past. Nothing fabricated; the engine produces them the same deterministic way it produces upcoming ones.
- **The acknowledgment overlay is the ONLY thing that distinguishes "done" from "missed,"** and it's the licensee's own input (they mark what they filed). The engine never guesses whether something was filed.
- **The agent** now surfaces misses honestly (the MISSED section is in its context) and still never authors a date.

## Architecture & components (each small, isolated, testable)

1. **Engine — full window + temporal status (pure).** `compute_schedule(profile, rules, today, horizon_days, lookback_days=0) -> (instances, flags)`. Computes due dates across `[today − lookback_days, today + horizon_days]` by passing each rule's `due_dates` an earlier start (`start = today − lookback_days`, `horizon = lookback_days + horizon_days`) — **no rule-interface change.** `ObligationInstance` gains `status: str` — `"overdue"` if `due_date < today`, else `"upcoming"`. Default `lookback_days=0` → forward-only, current behavior preserved. Flags unchanged. (The self-enforcing cited-or-nothing + type-filter + never-guess invariants are untouched.)
2. **Acknowledgment store (the "mark filed" persistence).** `ObligationStatusStore` over SQLite, table `obligation_status` keyed `(call_sign, rule_id, due_date_iso)` → `{addressed_on: date, note: str}`. Methods: `mark_addressed(call_sign, rule_id, due_date, note="")` (upsert), `get_addressed(call_sign) -> dict[(rule_id, due_date)] = {addressed_on, note}`, `clear(call_sign, rule_id, due_date)`. Idempotent table init. (May live alongside `ProfileStore` or as a sibling — plan-time call.)
3. **Status overlay (pure).** `apply_statuses(instances, addressed_map) -> instances` — returns instances with `status="done"` (carrying `addressed_on`/`note`) for any instance whose `(rule_id, due_date)` is in the addressed map; others pass through unchanged. Pure function; the engine stays ack-free.
4. **Routes.** `POST /address/<call_sign>` (form/JSON: `rule_id`, `due_date`, optional `note`) → `mark_addressed` → redirect to calendar; `POST /reopen/<call_sign>` (`rule_id`, `due_date`) → `clear` → redirect. The calendar route: load acks → `compute_schedule(..., lookback_days=365)` → `apply_statuses` → render grouped. (Both guard unknown station → 404, same pattern as existing routes.)
5. **Context builder update.** `build_compliance_context` groups instances by status into **MISSED (overdue & not done)**, **UPCOMING**, and **DONE** sections (DONE shows the filed date). The agent can now answer "what did I miss?" — from real computed dates.
6. **UI.** The calendar page renders three sections: **Missed — Action Needed** (red, top, each with a "Mark filed" button → `/address`), **Upcoming**, and **Done** (muted, with filed date + a "Reopen" link). The status hero counts any missed item as ACTION NEEDED (red).

## Data flow

acks loaded from `ObligationStatusStore` → `compute_schedule(profile, ALL_RULES, today, horizon_days=365, lookback_days=365)` → `apply_statuses(instances, acks)` → grouped Missed/Upcoming/Done → calendar UI **and** (for chat) the context builder. Mark filed → ack written → recompute → item moves to Done. Reopen → ack cleared → back to Missed/Upcoming.

## Error handling

- Unknown station on `/address` or `/reopen` → friendly 404 (same as existing routes). Don't create an ack for a station with no profile.
- Store failure → never 500 the calendar render; the deterministic schedule (without the overlay) is still shown. (Acks are additive — a missing overlay degrades to "everything past-due shows as overdue," never a crash.)
- **Degradation fails SAFE + is surfaced (not silent):** a down/erroring ack store means items show as **overdue/missed**, NOT falsely "Done" — over-alert, never false-clear, the correct direction for a compliance tool. AND the calendar surfaces an **"ack status temporarily unavailable"** indicator so the owner understands why nothing shows as filed (rather than silently seeing everything red). The route catches the store error, renders the deterministic schedule, and sets the flag.
- The engine remains pure/deterministic; no I/O, no ack dependency.
- **Time is date-only:** `due_date` and `today` are calendar dates (matching the CFR's date-only deadlines); overdue = `due_date < today`. `today` is the server's local date — correct for the **on-site sovereign appliance** (the box is at the station). No datetime/UTC-boundary handling needed at this scope; revisit only if Shepherd is ever cloud-hosted across multiple timezones.

## Testing

- **Engine:** a past due_date in the window → `status="overdue"`; a future one → `"upcoming"`; `lookback_days=0` → identical to current forward-only output (backward-compat regression test); cited-or-nothing + type-filter + missing-data still hold with a lookback.
- **`apply_statuses` (pure):** an addressed `(rule_id, due_date)` → `status="done"` + carries `addressed_on`; non-matching instances untouched; reopening (absence from map) → not done.
- **`ObligationStatusStore`:** mark/get/clear round-trip; upsert (re-mark updates, single row); clear removes.
- **Routes:** `/address` persists + the item shows Done on the calendar; `/reopen` clears + it returns to Missed/Upcoming; unknown station → 404; a genuinely-missed (past, unaddressed) obligation appears in Missed.
- **Context builder:** the MISSED section renders with real past dates + citations; a filed item appears under DONE, not MISSED.
- **Honesty:** no fabricated dates anywhere; overdue dates equal the engine's computed values.

## Scope / out of scope

- **In:** engine lookback + temporal status; the ack store + overlay; address/reopen routes; the three-section UI; the context-builder grouping (so the agent surfaces misses).
- **Out (YAGNI / later):** auto-detecting that a filing happened (the owner marks it — Shepherd doesn't watch the FCC); per-station configurable lookback; auth; chat-driven "mark filed" (the agent is read-only this slice — it can *report* misses, the owner clicks to file).

## Where it lives

`~/shepherd`: extend `shepherd/engine.py` (lookback + status); new `shepherd/status_store.py` (or fold into `store.py`); `shepherd/agent/context.py` (grouping); `shepherd/ui/app.py` (routes + calendar grouping) + templates/css. Reuses the existing engine, store, and context patterns.
