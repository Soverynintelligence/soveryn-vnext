# Ares Findings Tile + Heartbeat/Ares Twin-Panel Split (Design)

**Date:** 2026-07-03
**Status:** Design for review.
**Scope:** Give Ares a **visible surface** on Mission Control (`command_center.html`) — a read-only
findings tile — and place it beside the existing heartbeat panel as a 50/50 twin-panel row. Ares
already scans and publishes to a bus; nothing reaches Jon because the only surface is Signal-on-
EMERGENCY. This closes that gap. No new daemon, no LLM, no write actions.

## Problem (diagnosed 2026-07-03)
Ares (`--no-dry-run`) publishes findings to `data/ares/ares_bus.sqlite3` (an event log: 563 rows).
The only surface is a Signal alert gated on `Severity.EMERGENCY`, so criticals/warnings are invisible
and nothing new is emergency-level. The heartbeat panel already exists in Mission Control; Ares has
**no** panel and **no** `/api/ares` route.

## The data (ares bus)
`events(id, event_type, payload TEXT(json), actor, created_at)`. Each `payload` carries
`{id (finding key), finding_type, severity ∈ {emergency,critical,warning}, status ∈ {active,cleared},
evidence}`. The bus is an append-only transition log — a finding flaps `active`↔`cleared`. **The tile
must show CURRENT state**: the latest event per finding key, `status=='active'` only. Raw-log display
would be pure noise (the flapping loopback listeners).

## Components

### 1. Backend — `soveryn/app/routes/api_ares.py`
A pure query function + a thin blueprint route (mirrors `api_heartbeat`'s shape).

```python
def read_active_findings(bus_path: str) -> dict:
    """Current active Ares findings, deduped to latest-per-key, grouped by severity.

    Returns:
      {
        "findings": [ {severity, finding_type, key, evidence, last_seen}, ... ],  # sorted emergency>critical>warning, then last_seen desc
        "counts":   {"emergency": int, "critical": int, "warning": int},
        "generated_at": <ISO str, stamped by caller/route>,
      }
    Missing/empty DB -> {"findings": [], "counts": {...zeros}, ...} (never raises).
    """
```
- **Dedup SQL** (the core, validated against the real bus):
  `ROW_NUMBER() OVER (PARTITION BY json_extract(payload,'$.id') ORDER BY id DESC)` → keep `rn=1` with
  `status='active'`. Severity order: emergency(0) < critical(1) < warning(2).
- `evidence` is JSON in the payload; return it as a compact string (truncate to ~120 chars for display).
- Route: `@bp.get("/api/ares/findings")` → `read_active_findings(_ares_bus_path())` → `jsonify`.
- `_ares_bus_path()`: config override (`current_app.config.get("ARES_BUS_PATH")`) else the daemon's
  default `~/soveryn_vnext/data/ares/ares_bus.sqlite3`. (Injectable for tests.)
- Register in `soveryn/app/startup.py::_register_blueprints` alongside `api_heartbeat_bp`.
- **Read-only, best-effort**: a missing DB or malformed row returns empty/skips — never 500s the panel.

### 2. Frontend — Ares panel in `command_center.html`
- A `.ares-panel` section, shell mirroring `.heartbeat-panel` (same `.panel` wrapper + section header).
- Header shows the counts: `⚠ 1 emergency · 0 critical · 36 warnings` (color-coded).
- `.ares-feed`: one compact card per finding — severity dot/rail (emergency=red, critical=amber,
  warning=muted), `finding_type`, truncated evidence, relative age from `last_seen`. Reuse the
  green/amber/red tokens already in the stylesheet.
- Empty state: "All clear — no active findings." (`.ares-feed .empty`, mirrors `.heartbeat-feed .empty`).
- JS: fetch `/api/ares/findings` on load + on the same refresh interval the other panels use; render
  the cards. Mirror the existing heartbeat-panel fetch/render JS in the same file.

### 3. Layout — the twin-panel row
- Wrap the existing heartbeat `<section>` and the new ares `<section>` in a row with
  `grid-template-columns:1fr 1fr; gap:16px` (mirror `.orch-row`). Name it e.g. `.pulse-row`.
- Heartbeat left half, Ares right half, 50/50. The heartbeat panel's internals are **unchanged** —
  it just gets a neighbor.

## Testing
- **`tests/test_api_ares.py`** (the meat, offline): seed a temp `ares_bus.sqlite3` with events and assert
  `read_active_findings`:
  - a key with latest `cleared` is **excluded**; a key with latest `active` is **included** (dedup).
  - multiple severities → correct `counts` and emergency-first ordering.
  - malformed/missing payload rows are skipped, not raised; missing DB → empty result.
- **Route smoke** (`tests/test_app_ui_routes.py` or a new test): `GET /api/ares/findings` → 200 + JSON
  with `findings`/`counts`/`generated_at` keys (using a test app pointed at a temp bus via config).
- **Template presence**: assert the rendered `command_center` contains the `ares-panel` inside the
  twin row (a light render/string test in the existing app-UI test style).

## Scope / out
**IN:** `api_ares` route + `read_active_findings`, the ares panel, the twin-panel layout, tests.
**OUT (deferred, named):**
1. The **heartbeat content-upgrade** (showing *what* she flagged vs. just rhythm) — Jon's call, separate.
2. The **loopback-noise fix** (allowlisting normal local listeners so Ares stops *generating* the
   flapping warnings) — an Ares-config change, separate from the display tile. The dedup already keeps
   the noise out of the tile.
3. Any **write/ack actions** on findings (dismiss/acknowledge) — read-only v1.
4. No new daemon, no LLM.
