# Coordination Boards — Phase C: Kanban UI at `/boards`

**Status:** ready to implement (after Phase A; benefits from Phase B being live but doesn't strictly require it)
**Drafted:** 2026-06-01 evening
**Predecessor:** `feat(coordination): Agent Coordination Boards` (vnext d9d4db7)
**Scope:** ~half day for read-only v1.

## Goal

Give Jon the "God View" Aetheria's spec calls out — a three-column Kanban at `/boards` showing the current state of every non-archived coord node. Read-only in v1: operations stay through chat where the persona context lives. The UI is for *seeing*, not *driving*.

## In scope

### Backend
- New Flask blueprint `soveryn/app/routes/boards.py`
- `GET /boards` — renders `templates/boards.html` (full page)
- `GET /api/boards` — returns JSON of current state, columns + nodes
- `GET /api/boards/<node_id>` — single node detail with full content + Lesson Learned link if Archived (for the detail panel)
- Both API routes accept `?include_archived=true` for audit view

JSON response shape:
```json
{
  "columns": {
    "Signal":    [{"id": "...", "owner": "vett", "content_head": "first 200 chars", "status": "Open", "blocked_by": [], "created_at": "..."}],
    "Blueprint": [...],
    "Friction":  [...]
  },
  "totals": {"Signal": 12, "Blueprint": 4, "Friction": 1, "Archived": 47}
}
```

### Frontend
- `templates/boards.html` — three-column flex layout, matching the existing chat-page styling (var(--glass-bg), var(--gold), etc.)
- Polling refresh every 5s via `fetch('/api/boards')` (no SSE — keeps it stateless)
- Each card shows: dot (board color), owner, content preview (200 chars), status pill (color-coded), `blocked_by` indicator if non-empty
- Click card → side panel with full content + lattice_ref link (clicks to the lattice node if present) + archived_lesson_id link (if Archived) + cross-reference count (read from `store.reference_count(node_id)`)
- Search box (client-side, filters across content text)
- Toggle: "Show archived" checkbox in header → re-fetches with `?include_archived=true`

### CSS additions
- `.board-column` (flex, ~33% width, scrollable)
- `.board-card` (variant of `.bubble`)
- `.status-pill` (small badge with color per status)
- `.board-card[data-board="Signal"]` → blue accent
- `.board-card[data-board="Blueprint"]` → gold accent
- `.board-card[data-board="Friction"]` → red accent
- `.blocked-indicator` (small lock icon when `blocked_by` non-empty)

### Tests (`tests/test_boards_route.py`, new file)
- `test_get_boards_returns_three_columns`
- `test_get_boards_excludes_archived_by_default`
- `test_get_boards_includes_archived_when_query_param_set`
- `test_get_board_node_detail_returns_full_content`
- `test_get_board_node_detail_returns_404_for_missing`
- `test_get_boards_html_route_renders_template`

## Out of scope

- **Drag-drop state transitions:** would force WebSocket/optimistic-update infra and cross the read-only line. Defer until chat-as-transport actually chafes.
- **Inline node editing:** content edits bypass the tool layer's audit trail. If editing is wanted, it should go through `update_coordination_status` etc., not a direct DB write.
- **Real-time SSE updates:** 5s polling is fine for the coordination cadence (boards change minutes-to-hours, not seconds).
- **Mobile responsive layout:** desktop-first. Mobile can come later if you actually use it from a phone.
- **Per-agent view filters** ("show only my owned nodes"): use search box for now; dedicated filter UI is overkill for three-agent fleet.
- **Cross-board promote button** (Phase A pipeline visualized): Phase A ships the tool; UI visualization can come once you've used the tool and know what shape the button needs.

## Reason

Right now you can only see the boards by asking Aetheria to read them through chat. The God View is a usability gap, not a capability gap — the substrate is there, you just can't *glance* at it. A read-only Kanban closes that gap without crossing into "second UI for everything" territory. Keep operations in chat (where personas live); use the UI for awareness.

## Implementation order

1. Backend: `boards.py` blueprint with both API routes + the HTML route
2. JSON endpoint first, test with curl — confirm response shape
3. Template: `boards.html` with three columns, card render loop, basic CSS
4. Polling refresh script
5. Detail panel + reference_count display
6. Search filter (client-side)
7. Tests
8. Restart, navigate to `/boards`, verify it renders cleanly + reflects current DB state + updates when you create a node from chat
9. Commit

## Visual sketch

```
┌─ /boards ────────────────────────────────────────────────────────────┐
│ [search: ___________ ]                              [ ] show archived│
│                                                                       │
│ ┌─ Signal (12) ──┐  ┌─ Blueprint (4) ─┐  ┌─ Friction (1) ──┐         │
│ │ ● vett · OPEN   │  │ ● aetheria·READY │  │ ● aetheria·OPEN  │         │
│ │ lead about EU…  │  │ exec plan X      │  │ "VETT says X,    │         │
│ │                 │  │ 🔒 blocked       │  │ Lattice says Y"  │         │
│ │ ● vett · OPEN   │  │                  │  └──────────────────┘         │
│ │ funding stream… │  │ ● scotty·REFINING│                              │
│ └─────────────────┘  │ blueprint y      │                              │
│                      └──────────────────┘                              │
│                                                                       │
│ click card → side panel with full content + lesson_learned link       │
└────────────────────────────────────────────────────────────────────────┘
```
