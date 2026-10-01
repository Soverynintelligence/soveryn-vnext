# Collab closer — peer DMs that actually close

| Field | Value |
|-------|--------|
| **Status** | Implemented 2026-08-31 |
| **Date** | 2026-08-31 |
| **Scope** | Item 1 of the steal list. No Hermes runtime, no Bot Mode, no MCP dashboard. |
| **Seats** | Aetheria (CoS / 1:1), Kernel, Eve. Keep OpenCode + vLLM. |

Later, not this change: steer/kill a child mid-flight; cron that remembers; 32K lean-tail.

---

## What we are stealing

Hermes/OpenClaw **peer**: bot-to-bot work lands in an inspectable chat with a state machine (`working → done|failed`), a TTL, and a transcript you can open. That is why leftover commissions made Aetheria look like she was still “working with Kernel” after the ticket was dead.

We already have most of the pieces. The desk still lies. Close the loop on **our** rooms + commissions. Do not copy Discord Bot Mode.

---

## Live vNext (observed 2026-08-31)

### Already true

| Piece | Where | What it does |
|-------|--------|----------------|
| Commission ticket | `soveryn/citizens/commissions.py` | `queued → running → done\|failed`. Atomic claim. `complete()` needs `result_ref`. `abandoned()` exists. |
| Drain | `soveryn/citizens/runtime.py` | Claims, runs AgentLoop, writes outbox, `report_to_cos`, projects into room, then **queues a second Aetheria job** `[COS_RELAY]`. |
| Phone execute | `direct_communication/tools.py` | If a DM is live: enqueue commission, `record_house_post_collab`, return. No nested `/chat`. Correct instinct. |
| Nested `/chat` | same file, fall-through | Mints `[direct:{coord}]` session, `mark_working=True` **with no `commission_id`**, waits on peer GPU. |
| Room sidecar | `data/rooms/*.json` | `messaged_peer` events with `state: working`. Kernel room `cfe0554f…` has **45 events**. |
| Overlay | `overlay_collab_commission_states` | On `GET /api/rooms/collabs`, if chip is `working` and commission is `done/failed`, rewrite chip and persist. |
| Desk subtitle | `messages.html` | First collab with `state===working` and age &lt; 2h → **“Working with {peer}”**. |
| Thread chips | `chat.html` `isActiveCollab` | `state===working` is **always** live — **no TTL**. Transcript regex `⟦room:messaged:kernel⟧` + `/working/i` can keep the pulse. |

### Live queue right now

Zero `queued`/`running` commissions. Overlay has already flipped room chips off `working`. The leftover-test class is still real: this afternoon Kernel docs-pass `50128827` (and re-dispatches `97f8a63e`, `f1e3eb63`, `48a52b91`, `0e6d4eec`) each spawned a `[COS_RELAY]` onto Aetheria. She briefed Jon **five times**. The ticket was done; the desk and her mouth were not.

### Why the desk lies

1. **`working` is a sidecar, not the ticket.** Chip state lives in room JSON. Commission state lives in `citizens.db`. Overlay only runs when someone polls `/api/rooms/collabs`. If the UI is on another thread, or the chip has **no `commission_id`**, it never closes.
2. **`mark_working=True` without a ticket.** Nested `/chat` and any collab that only sets the flag cannot be closed by overlay.
3. **Transcript is a second source of truth.** `chat.html` infers `working` from the system line text. Old “Messaged Kernel — working…” turns keep the icon hot even after overlay patched the sidecar.
4. **`isActiveCollab` has no TTL on `working`.** A stuck chip is immortal until a GET happens to persist a close.
5. **CoS relay is a new job on Aetheria.** Peer `done` immediately looks like Aetheria is still working. Relay is useful as a brief; it must not keep the Kernel collab `working`.
6. **Aetheria cannot inspect the collab.** She gets a tool result “looped in kernel via commission `0e6d4eec`” and no later `done`. Continuity / standing objectives re-dispatch. Fire-and-forget.

The group room **is** the inspectable chat. It is just not the closer.

---

## Non-goals

- Bot Mode / Discord clone
- Switching Kernel onto Hermes
- MCP dashboard, in-app browser, provider catalog, terminal pets
- Mid-flight steer/kill (item 2)
- Cron memory / monitor-mode (item 3)
- Lean-tail / turn-reaper (item 4)
- Giving Kernel Aetheria’s pinned-memory relationship block

---

## Design

One collab = one commission ticket + one group-room thread + one chip on Jon’s Aetheria 1:1.

```
open:   Aetheria DM execute → enqueue Kernel/Eve commission
        → room event messaged_peer {state:working, commission_id, opened_at, ttl}
        → DM system line (no “working…” as the only truth)

run:    citizens-runtime claims + runs peer
        → turns append to the same room session (already happens)

close:  complete() / fail() / TTL / abandon
        → persist chip done|failed in the sidecar in the same transaction path
        → one system line on the 1:1: "Kernel done" | "Kernel failed"
        → CoS brief (optional) is Aetheria summarizing a CLOSED collab
```

### 1. Never open `working` without a ticket

`record_house_post_collab(..., mark_working=True)` without `commission_id` is forbidden.

- Phone `direct_message_agent` execute already commissions. Keep that.
- Nested `/chat` fall-through: **do not** mark working. Either enqueue a commission (same as phone) or run query-mode without a chip. Heartbeat/coord execute without a live DM can stay nested `/chat` but must not paint Jon’s desk.
- `ask_peer` already stores `commission_id`. Keep.

### 2. Close on the writer, not on GET

Today overlay patches JSON only when the Messages list or Aetheria thread polls collabs.

On `runtime.execute_claimed` after `complete()` / `fail()`:

- load room via `find_room_for_commission`
- `_close_matching_messaged_peer` (already exists)
- persist sidecar
- write a **terminal** DM system line, e.g. `⟦room:closed:kernel⟧ done` / `failed`

`GET /api/rooms/collabs` overlay stays as a safety net, not the primary closer.

### 3. UI: ticket overlay is the only “working”

- `isActiveCollab`: `working` only if overlay `commission_state` is `queued`/`running` **or** (no ticket and age &lt; TTL). Terminal `done`/`failed` is never active.
- `messages.html` “Working with {peer}”: same rule. 2h cap stays as a backstop.
- Stop inferring `working` from `/working/i` on old system lines. Use `⟦room:closed:…⟧` and collab JSON.
- Pulse/poll while `working`; stop when closed.

TTL (proposal): **45 minutes** for Kernel/Eve collab chips. Matches stale-running requeue (~600s) plus slack for CoS brief. After TTL, overlay treats as `failed` (`ttl_expired`) even if the row is still `running` — the ticket can keep running; the **desk** stops lying. (Abandon/requeue of the ticket is existing runtime; this spec only closes the chip.)

### 4. One live collab per (dm_session, peer)

If Aetheria loops Kernel again while a Kernel collab for that DM is `working`:

- attach to the existing commission if still `queued`/`running` (do not enqueue a twin), **or**
- refuse with the open `commission_id` and a one-liner to `read_collab`

This is the leftover-test killer: five docs-pass re-dispatches in one hour would have been one thread.

### 5. Inspectable transcript = the group room

Do not mint a second `[direct:coord]` session for phone execute (already true).

Add a small CoS tool, **`read_collab`**:

- args: `peer` (kernel|eve) and optional `commission_id`
- returns: state, age, last N room turns, outbox path if done, error if failed

Aetheria’s standing line: if the collab is `working`, read it; do not re-dispatch. If `done`/`failed`, brief Jon from the transcript.

Keep `[COS_RELAY]` as the brief to Jon, but:

- it must run **after** the chip is closed
- it must not set Kernel (or anyone) back to `working`
- duplicate relays for the same `source_commission` are no-ops (today `50128827` produced multiple relays)

### 6. Abandoned tickets become failed chips

`abandoned()` already lists stale `running`. When runtime requeues or fails them, run the same close path. A requeued ticket is a **new** `working` only after a fresh claim — not a ghost chip from the previous attempt.

---

## Files (when implementing)

| File | Change |
|------|--------|
| `soveryn/rooms/store.py` | Forbid working-without-id; TTL on overlay; `⟦room:closed:⟧`; close helper used by runtime |
| `soveryn/citizens/runtime.py` | Close chip on complete/fail; dedupe CoS relay by `source_commission` |
| `soveryn/agents/direct_communication/tools.py` | No `mark_working` without ticket; reuse open collab |
| `soveryn/app/templates/chat.html` | `isActiveCollab` + stop regex working; honor closed marker |
| `soveryn/app/templates/messages.html` | Same overlay rule for “Working with” |
| `soveryn/app/templates/room.html` | Face pulse follows overlay, not last messaged line |
| new tool | `read_collab` on Aetheria only |
| tests | `tests/test_rooms.py` + new closer tests (open/close/TTL/dedupe/no-chip-without-id) |

No schema migration required if we keep using room events + `commissions`. Optional later: a `collabs` table. Not needed for v1.

---

## Tests that must exist

1. Open collab with commission → chip `working`, desk subtitle “Working with kernel”.
2. `complete()` → sidecar `done`, DM `⟦room:closed:kernel⟧`, desk subtitle not hot, chip gone.
3. `fail()` → `failed`, same.
4. `mark_working=True` without id → no chip (or hard error in unit test).
5. Overlay GET is not required for (2); runtime close is enough.
6. Second execute while first `running` → no second commission.
7. Two CoS relays for one `source_commission` → one brief.
8. `working` older than TTL with missing/stale ticket → not active.
9. Nested `/chat` without DM does not paint Messages.

---

## Acceptance

Jon can tap Kernel’s face, read the group thread, and the 1:1 never says “working with Kernel” after the commission row is `done` or `failed`. Aetheria does not re-dispatch a live collab. CoS still briefs once.

---

## Backlog (do not sneak in)

2. **Steer/kill child** — list running OpenCode/Aider kids, course-correct, stop, keep partial. Grok-Bot MessageSubagent pattern. Separate spec.
3. **Cron that remembers** — 7am digest / Pond Academy: load memory, continuity, notepad, monitor-mode hash, acked failures.
4. **32K window** — lean-tail, spill fat tool results, turn-reaper. Kernel’s actual pain.
