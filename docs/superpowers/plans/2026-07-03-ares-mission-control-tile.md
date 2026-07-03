# Ares Findings Tile + Twin-Panel Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Ares's findings on Mission Control as a read-only tile, placed beside the existing heartbeat panel as a 50/50 twin-panel row.

**Architecture:** A pure `read_active_findings(bus_path)` (dedupes the ares event-bus to current active state, grouped by severity) behind a thin `/api/ares/findings` blueprint route, plus an `.ares-panel` in `command_center.html` that fetches it and renders finding cards, wrapped with the heartbeat panel in a `grid 1fr 1fr` row.

**Tech Stack:** Flask blueprint (mirrors `api_heartbeat`), SQLite (`ares_bus.sqlite3`), vanilla JS in `command_center.html`, pytest.

## Global Constraints
- **Read-only, best-effort.** A missing/locked DB or malformed row returns empty — the panel must never 500.
- **Current state, not the raw log.** Dedupe to the latest event per finding key (`payload.$.id`), `status=='active'` only. The bus flaps active↔cleared; raw display is noise.
- **Severity order:** emergency(0) < critical(1) < warning(2). Colors reuse existing red/amber/muted tokens.
- **No new daemon, no LLM, no write actions.** Heartbeat panel internals unchanged — it only gains a neighbor.
- **DB read-only open:** `sqlite3.connect(f"file:{path}?mode=ro", uri=True)` so the panel never locks Ares's writer.

---

### Task 1: Backend — `read_active_findings` + `/api/ares/findings` route

**Files:**
- Create: `soveryn/app/routes/api_ares.py`
- Modify: `soveryn/app/startup.py` (register the blueprint in `_register_blueprints`)
- Test: `tests/test_api_ares.py`

**Interfaces:**
- Produces: `read_active_findings(bus_path: str) -> dict` with keys `findings` (list of `{severity, finding_type, key, evidence, last_seen}`), `counts` (`{emergency,critical,warning}` ints), `generated_at`; blueprint `bp` named `"api_ares"` serving `GET /api/ares/findings`.

- [ ] **Step 1: Write the failing test** — `tests/test_api_ares.py`:

```python
"""Ares findings surface — dedup + grouping, offline with a temp bus."""
import json
import sqlite3
from soveryn.app.routes.api_ares import read_active_findings


def _bus(tmp_path, rows):
    """rows: list of (payload_dict_or_str, created_at). Builds an ares_bus.sqlite3."""
    db = tmp_path / "ares_bus.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL)")
    for payload, created in rows:
        pj = payload if isinstance(payload, str) else json.dumps(payload)
        conn.execute(
            "INSERT INTO events (event_type, payload, actor, created_at) VALUES (?,?,?,?)",
            ("anomaly.detected", pj, "ares", created))
    conn.commit()
    conn.close()
    return str(db)


def _f(key, sev, status, ftype="network.x", ev="ev"):
    return {"id": key, "severity": sev, "status": status, "finding_type": ftype, "evidence": ev}


def test_cleared_latest_is_excluded(tmp_path):
    p = _bus(tmp_path, [
        (_f("k1", "warning", "active"), "2026-07-03T01:00:00+00:00"),
        (_f("k1", "warning", "cleared"), "2026-07-03T02:00:00+00:00"),
    ])
    out = read_active_findings(p)
    assert out["findings"] == []
    assert out["counts"]["warning"] == 0


def test_active_latest_included_counted_and_emergency_first(tmp_path):
    p = _bus(tmp_path, [
        (_f("k1", "warning", "cleared"), "2026-07-03T01:00:00+00:00"),
        (_f("k1", "warning", "active"), "2026-07-03T02:00:00+00:00"),
        (_f("k2", "emergency", "active"), "2026-07-03T03:00:00+00:00"),
    ])
    out = read_active_findings(p)
    assert {f["key"] for f in out["findings"]} == {"k1", "k2"}
    assert out["counts"] == {"emergency": 1, "critical": 0, "warning": 1}
    assert out["findings"][0]["severity"] == "emergency"    # emergency sorts first


def test_missing_db_returns_empty(tmp_path):
    out = read_active_findings(str(tmp_path / "nope.sqlite3"))
    assert out["findings"] == [] and out["counts"] == {"emergency": 0, "critical": 0, "warning": 0}


def test_malformed_and_unknown_severity_rows_skipped(tmp_path):
    p = _bus(tmp_path, [
        ("not-a-json-object", "2026-07-03T01:00:00+00:00"),                    # non-dict payload
        (_f("k3", "bogus", "active"), "2026-07-03T02:00:00+00:00"),            # unknown severity
        (_f("k4", "critical", "active"), "2026-07-03T03:00:00+00:00"),         # good
    ])
    out = read_active_findings(p)
    assert [f["key"] for f in out["findings"]] == ["k4"]
    assert out["counts"]["critical"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_ares.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.app.routes.api_ares'`.

- [ ] **Step 3: Write `soveryn/app/routes/api_ares.py`**

```python
"""SOVERYN vNext — /api/ares/* — Ares findings surface for Mission Control.

Ares publishes an append-only event log (findings flap active<->cleared) to
ares_bus.sqlite3. This exposes the CURRENT active state: the latest event per
finding key, active only, grouped by severity. Read-only, best-effort — a
missing/locked DB or malformed row yields an empty result, never a 500.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, current_app, jsonify

bp = Blueprint("api_ares", __name__)

_DEFAULT_BUS = Path.home() / "soveryn_vnext" / "data" / "ares" / "ares_bus.sqlite3"
_SEV_ORDER = {"emergency": 0, "critical": 1, "warning": 2}

# latest event per finding key (payload.$.id), newest event id wins
_QUERY = """
SELECT payload, created_at FROM (
    SELECT payload, created_at,
           ROW_NUMBER() OVER (
               PARTITION BY json_extract(payload, '$.id') ORDER BY id DESC) AS rn
    FROM events)
WHERE rn = 1
"""


def read_active_findings(bus_path: str) -> dict:
    result = {
        "findings": [],
        "counts": {"emergency": 0, "critical": 0, "warning": 0},
        "generated_at": None,
    }
    if not os.path.exists(bus_path):
        return result
    try:
        conn = sqlite3.connect(f"file:{bus_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(_QUERY).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return result

    findings = []
    for r in rows:
        try:
            p = json.loads(r["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(p, dict) or p.get("status") != "active":
            continue
        sev = p.get("severity")
        if sev not in _SEV_ORDER:
            continue
        ev = p.get("evidence")
        ev_str = ev if isinstance(ev, str) else json.dumps(ev)
        findings.append({
            "severity": sev,
            "finding_type": p.get("finding_type", ""),
            "key": p.get("id", ""),
            "evidence": (ev_str or "")[:120],
            "last_seen": r["created_at"],
        })
        result["counts"][sev] += 1

    # Two stable sorts: newest-first within each severity, then group by severity.
    # ISO-8601 strings sort lexically, so reverse=True on last_seen == newest-first.
    findings.sort(key=lambda f: f["last_seen"] or "", reverse=True)
    findings.sort(key=lambda f: _SEV_ORDER[f["severity"]])
    result["findings"] = findings
    return result


def _ares_bus_path() -> str:
    override = current_app.config.get("ARES_BUS_PATH")
    return str(override) if override else str(_DEFAULT_BUS)


@bp.get("/api/ares/findings")
def api_ares_findings():
    data = read_active_findings(_ares_bus_path())
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return jsonify(data), 200
```

- [ ] **Step 4: Register the blueprint** — in `soveryn/app/startup.py`, in `_register_blueprints`, after the `api_heartbeat` registration (~line 949), add:

```python
    from soveryn.app.routes.api_ares import bp as api_ares_bp
    app.register_blueprint(api_ares_bp)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_api_ares.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/routes/api_ares.py soveryn/app/startup.py tests/test_api_ares.py
git commit -m "feat(mission-control): /api/ares/findings — current active findings, deduped by key"
```

---

### Task 2: Frontend — Ares panel + twin-panel layout in `command_center.html`

**Files:**
- Modify: `soveryn/app/templates/command_center.html` (CSS + the `.ares-panel` section + the twin-row wrapper + `renderAres()` JS + wire into refresh)
- Test: `tests/test_ares_panel_render.py`

**Interfaces:**
- Consumes: `GET /api/ares/findings` (Task 1). Mirrors the existing `heartbeat-panel` markup + `renderHeartbeat()` JS in the same file.

- [ ] **Step 1: Write the failing test** — `tests/test_ares_panel_render.py`:

```python
"""The command_center template renders an Ares panel inside the twin row,
and /api/ares/findings is reachable through the app."""
import json
import sqlite3


def _seed_bus(tmp_path):
    db = tmp_path / "ares_bus.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, payload TEXT, actor TEXT, created_at TEXT)")
    conn.execute("INSERT INTO events (event_type,payload,actor,created_at) VALUES (?,?,?,?)",
                 ("anomaly.detected", json.dumps({"id": "k1", "severity": "emergency", "status": "active",
                  "finding_type": "network.public_listener_unallowlisted", "evidence": {"port": 5055}}),
                  "ares", "2026-07-03T03:00:00+00:00"))
    conn.commit(); conn.close()
    return str(db)


def test_command_center_has_ares_panel(client):
    # `client` is the existing app-test fixture used by tests/test_app_ui_routes.py
    html = client.get("/").get_data(as_text=True) if client.get("/").status_code == 200 else \
           client.get("/command-center").get_data(as_text=True)
    assert 'ares-panel' in html
    assert 'data-ares-feed' in html
    assert 'pulse-row' in html          # heartbeat + ares wrapped in the twin row


def test_api_ares_findings_endpoint(client, tmp_path):
    client.application.config["ARES_BUS_PATH"] = _seed_bus(tmp_path)
    resp = client.get("/api/ares/findings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) >= {"findings", "counts", "generated_at"}
    assert data["counts"]["emergency"] == 1
    assert data["findings"][0]["finding_type"] == "network.public_listener_unallowlisted"
```

> Implementer note: match the existing app-test fixture. Read `tests/test_app_ui_routes.py` to see how `client` / the Flask test app is constructed (fixture name + the correct route for the command-center page — `/` or `/command-center`). Adjust the two `client.get(...)` targets to the real route. Do not invent a fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ares_panel_render.py -v`
Expected: FAIL — `ares-panel` not in the template / fixture mismatch (fix the fixture per the note, then it fails on the missing panel).

- [ ] **Step 3: Add the Ares panel CSS** — in `command_center.html`, after the `.heartbeat-feed .empty { ... }` block (~line 575), add:

```html
  /* ─── Ares panel ─── sibling of .heartbeat-panel in the .pulse-row twin. */
  .pulse-row { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .ares-feed { display:flex; flex-direction:column; gap:6px; max-height:320px; overflow-y:auto; }
  .ares-counts { font-size:11px; color:rgba(232,227,213,0.6); margin-bottom:8px; }
  .ares-counts .sev-emergency { color:#ef4444; }
  .ares-counts .sev-critical  { color:#f59e0b; }
  .ares-finding {
    display:flex; align-items:flex-start; gap:8px; padding:7px 10px;
    background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.04);
    border-left-width:3px; border-radius:6px; font-size:11px; line-height:1.4;
    color:rgba(232,227,213,0.78);
  }
  .ares-finding[data-sev="emergency"] { border-left-color:#ef4444; }
  .ares-finding[data-sev="critical"]  { border-left-color:#f59e0b; }
  .ares-finding[data-sev="warning"]   { border-left-color:rgba(232,227,213,0.25); }
  .ares-finding .ftype { color:rgba(232,227,213,0.9); font-weight:500; }
  .ares-finding .ev { color:rgba(232,227,213,0.55); }
  .ares-feed .empty { font-size:11px; color:rgba(232,227,213,0.4); padding:10px; }
```

- [ ] **Step 4: Add the panel + wrap the twin row** — find the heartbeat `<section class="panel heartbeat-panel" ...>` (~line 827). Wrap it and a new ares section in a `.pulse-row` div. Replace the opening of the heartbeat section:

Change:
```html
    <section class="panel heartbeat-panel" data-testid="heartbeat-panel">
```
to:
```html
    <div class="pulse-row">
    <section class="panel heartbeat-panel" data-testid="heartbeat-panel">
```
and immediately after the heartbeat section's closing `</section>`, add the ares section + close the row:
```html
    <section class="panel ares-panel" data-testid="ares-panel">
      <h3>Ares — host findings</h3>
      <div class="ares-counts" data-ares-counts></div>
      <div class="ares-feed" data-ares-feed aria-live="polite" aria-label="Active Ares findings"></div>
    </section>
    </div>
```
(Locate the heartbeat section's own `</section>` by reading the file; it is the close of the block opened at ~line 827.)

- [ ] **Step 5: Add `renderAres()` JS + wire into the refresh** — after `renderHeartbeat()` (~line 1498-1520), add:

```javascript
  function severityLabel(counts) {
    const parts = [];
    if (counts.emergency) parts.push(`<span class="sev-emergency">${counts.emergency} emergency</span>`);
    if (counts.critical)  parts.push(`<span class="sev-critical">${counts.critical} critical</span>`);
    parts.push(`${counts.warning || 0} warning`);
    return parts.join(" · ");
  }

  async function renderAres() {
    const data = await fetchJson("/api/ares/findings");
    const feed = document.querySelector("[data-ares-feed]");
    const counts = document.querySelector("[data-ares-counts]");
    if (!feed) return;
    const d = data || { findings: [], counts: { emergency: 0, critical: 0, warning: 0 } };
    if (counts) counts.innerHTML = severityLabel(d.counts || {});
    if (!d.findings || d.findings.length === 0) {
      feed.innerHTML = '<div class="empty">All clear — no active findings.</div>';
      return;
    }
    feed.innerHTML = d.findings.map(f => `
      <div class="ares-finding" data-sev="${f.severity}">
        <div><span class="ftype">${f.finding_type}</span><br><span class="ev">${(f.evidence || "").replace(/</g, "&lt;")}</span></div>
      </div>`).join("");
  }
```

Then find where `renderHeartbeat();` is called in the refresh cycle (~line 1699) and add `renderAres();` beside it.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_ares_panel_render.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Run the app-UI suite (no regressions)**

Run: `python -m pytest tests/test_app_ui_routes.py tests/test_api_ares.py tests/test_ares_panel_render.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add soveryn/app/templates/command_center.html tests/test_ares_panel_render.py
git commit -m "feat(mission-control): Ares tile beside heartbeat in a 50/50 twin row"
```

---

## Manual verification (after both tasks, human — not an automated step)
Load Mission Control in the browser: the heartbeat and Ares panels sit side-by-side (50/50); the Ares panel shows the current active findings (severity-colored) or "All clear"; it refreshes on the normal cycle. (Requires the fleet up.)
