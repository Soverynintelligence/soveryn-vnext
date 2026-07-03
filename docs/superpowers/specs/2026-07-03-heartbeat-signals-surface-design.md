# Heartbeat "What She's Flagging" Surface (Design)

**Date:** 2026-07-03
**Status:** Design for review (approach approved by Jon — mirror the Ares tile).
**Scope:** Make the Mission Control heartbeat panel show **what Aetheria is flagging** (her material
signals — deadlines, stalls), not just pulse rhythm. Read-only, no daemon/LLM change.

## Problem
The heartbeat daemon surfaces on nearly every pulse (`decision=SURFACE, surfaced=True`,
`material_signals=4`) — e.g. a July-10 funding deadline + three stalls. But the panel + existing
`/api/heartbeat/recent` only expose pulse *metadata* (`eligible/skip_reason/surfaced_to_chat`), so
the tile reads as silent. The actual signal content lives in `data/heartbeat_thoughts.jsonl`
(`snapshot.material_signals`) and is otherwise routed to a chat thread Jon doesn't watch.

## Data (heartbeat_thoughts.jsonl)
One JSON object per line: `{ts, pulse_id, decision, surfaced, snapshot:{material_signals:[...]}}`.
Each material signal: `{kind: "deadline"|"stall", ref: <item title>, detail: <human string, e.g.
"mentions July 10 due in 7 days" / "status=Open for 457h (threshold=48h)">}`.
Path default: `~/soveryn_vnext/data/heartbeat_thoughts.jsonl` (daemon's `DEFAULT_THOUGHTS_LOG`).

## Components

### 1. Backend — extend `soveryn/app/routes/api_heartbeat.py`
Add a pure reader + a route (mirrors the Ares `read_active_findings` shape):
```python
def read_recent_material_signals(thoughts_path: str) -> dict:
    """The most recent pulse's material signals — what Aetheria is currently flagging.
    Returns {"signals": [{kind, ref, detail}], "ts": <str|None>, "decision": <str|None>}.
    Missing/empty/malformed file -> {"signals": [], "ts": None, "decision": None}. Never raises.
    """
```
- Read the file, take the **last non-empty line** that parses as JSON with a non-empty
  `snapshot.material_signals` (walk backward so a trailing skipped/NO_OP pulse with no signals doesn't
  blank the panel). Cap the file read (tail ~200 lines) so it stays cheap.
- Sanitize each signal: `kind` ∈ {deadline, stall} (else "other"); `ref` stripped of leading `**`/
  markdown and truncated ~70 chars; `detail` truncated ~120 chars.
- Route: `@bp.get("/api/heartbeat/signals")` → `read_recent_material_signals(_thoughts_path())`.
- `_thoughts_path()`: `current_app.config.get("HEARTBEAT_THOUGHTS_PATH")` else the default. (Injectable
  for tests.) Best-effort — the panel never 500s.

### 2. Frontend — a "flagging" block atop the heartbeat panel (`command_center.html`)
- Add a `.heartbeat-signals` block at the **top** of the existing `.heartbeat-panel`, above the pulse
  feed (rhythm stays, secondary).
- Fetch `/api/heartbeat/signals`; render one card per signal: a kind chip (deadline=amber ⚑,
  stall=muted ⏳, other=neutral), the `ref`, and the `detail` sub-line. Reuse the `.ares-finding`
  card shape (severity-rail styling) for visual consistency with the neighbor tile.
- Empty state: "Nothing flagged." Wire `renderHeartbeatSignals()` into the same refresh cycle as
  `renderHeartbeat()`/`renderAres()`.

## Testing
- **`tests/test_heartbeat_signals.py`** (offline): write a temp thoughts jsonl and assert
  `read_recent_material_signals`:
  - returns the **latest** entry's signals (multiple lines → last one with signals wins).
  - walks back past a trailing no-signals/NO_OP line to the last pulse that had signals.
  - `kind`/`ref`/`detail` sanitized (markdown `**` stripped, truncated); unknown kind → "other".
  - missing file / malformed lines → empty `signals`, no raise.
- **Route smoke** (reuse the `client` fixture / `conftest.py`): `GET /api/heartbeat/signals` with a
  config-pointed temp file → 200 + `{signals, ts, decision}` shape.
- **Template presence**: rendered `command_center` contains `heartbeat-signals` + a
  `renderHeartbeatSignals` hook.

## Scope / out
**IN:** the `read_recent_material_signals` reader + `/api/heartbeat/signals` route, the panel
"flagging" block, tests.
**OUT:** changing the daemon or its decision logic; the `_surface_to_primary_thread` chat routing
(separate); ack/dismiss actions (read-only); history of past pulses' signals (show *current* only).
