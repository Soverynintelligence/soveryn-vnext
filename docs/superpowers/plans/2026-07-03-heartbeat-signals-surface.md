# Heartbeat "What She's Flagging" Surface Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface Aetheria's current material signals (deadlines/stalls) on the Mission Control heartbeat panel, so it shows *what she's flagging* instead of only pulse rhythm.

**Architecture:** A pure `read_recent_material_signals(thoughts_path)` (latest pulse's signals from `heartbeat_thoughts.jsonl`) behind a new `/api/heartbeat/signals` route, plus a "flagging" block atop the existing heartbeat panel that fetches + renders it — mirroring the just-built Ares tile.

**Tech Stack:** Flask (extend `api_heartbeat`), JSONL read, vanilla JS in `command_center.html`, pytest.

## Global Constraints
- **Read-only, best-effort.** Missing/malformed thoughts file → empty signals, never a 500.
- **Show CURRENT only** — the most recent pulse that *had* signals (walk backward past trailing NO_OP/empty pulses). Cap the read to the last ~200 lines.
- **No daemon/LLM/decision change.** Pulse-rhythm feed stays; the flagging block is added above it.
- **Reuse the Ares card styling** (`.ares-finding` shape) for visual consistency with the neighbor tile.

---

### Task 1: Backend — `read_recent_material_signals` + `/api/heartbeat/signals`

**Files:**
- Modify: `soveryn/app/routes/api_heartbeat.py`
- Test: `tests/test_heartbeat_signals.py`

**Interfaces:**
- Produces: `read_recent_material_signals(thoughts_path: str) -> dict` (`{signals:[{kind,ref,detail}], ts, decision}`); route `GET /api/heartbeat/signals`.

- [ ] **Step 1: Write the failing test** — `tests/test_heartbeat_signals.py`:

```python
"""Heartbeat material-signals reader — latest pulse's signals, offline."""
import json
from soveryn.app.routes.api_heartbeat import read_recent_material_signals


def _write(tmp_path, entries):
    p = tmp_path / "ht.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(p)


def _entry(ts, decision, sigs):
    return {"ts": ts, "decision": decision, "snapshot": {"material_signals": sigs}}


def test_returns_latest_entry_with_signals(tmp_path):
    p = _write(tmp_path, [
        _entry("2026-07-03T13:00:00", "SURFACE", [{"kind": "stall", "ref": "old", "detail": "x"}]),
        _entry("2026-07-03T14:00:00", "SURFACE", [{"kind": "deadline", "ref": "**New Proj", "detail": "due in 7 days"}]),
    ])
    out = read_recent_material_signals(p)
    assert out["ts"] == "2026-07-03T14:00:00"
    assert len(out["signals"]) == 1
    assert out["signals"][0]["kind"] == "deadline"
    assert out["signals"][0]["ref"] == "New Proj"          # leading ** stripped


def test_walks_back_past_trailing_empty(tmp_path):
    p = _write(tmp_path, [
        _entry("2026-07-03T13:00:00", "SURFACE", [{"kind": "stall", "ref": "real", "detail": "Open 457h"}]),
        _entry("2026-07-03T14:00:00", "NO_OP", []),         # trailing pulse, no signals
    ])
    out = read_recent_material_signals(p)
    assert out["ts"] == "2026-07-03T13:00:00"
    assert out["signals"][0]["ref"] == "real"


def test_unknown_kind_becomes_other(tmp_path):
    p = _write(tmp_path, [_entry("t", "SURFACE", [{"kind": "weird", "ref": "r", "detail": "d"}])])
    assert read_recent_material_signals(p)["signals"][0]["kind"] == "other"


def test_missing_file_and_malformed_are_safe(tmp_path):
    assert read_recent_material_signals(str(tmp_path / "nope.jsonl")) == {"signals": [], "ts": None, "decision": None}
    p = tmp_path / "bad.jsonl"
    p.write_text("not json\n" + json.dumps(_entry("t", "SURFACE", [{"kind": "stall", "ref": "ok", "detail": "d"}])) + "\n")
    out = read_recent_material_signals(str(p))
    assert out["signals"][0]["ref"] == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_heartbeat_signals.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_recent_material_signals'`.

- [ ] **Step 3: Extend `soveryn/app/routes/api_heartbeat.py`**

Add to the imports at the top (with the existing ones):
```python
import json
import os
from pathlib import Path
```

Add these (after the `_state()` helper, before the `/recent` route):
```python
_DEFAULT_THOUGHTS = Path.home() / "soveryn_vnext" / "data" / "heartbeat_thoughts.jsonl"
_KNOWN_KINDS = {"deadline", "stall"}


def _clean_ref(ref) -> str:
    return (ref or "").lstrip("*").strip()[:70]


def read_recent_material_signals(thoughts_path: str) -> dict:
    """Most recent pulse's material signals — what Aetheria is currently flagging.

    Walks backward to the last pulse that actually had signals (so a trailing
    NO_OP/empty pulse doesn't blank the panel). Best-effort: missing/malformed
    file -> empty, never raises.
    """
    empty = {"signals": [], "ts": None, "decision": None}
    if not os.path.exists(thoughts_path):
        return empty
    try:
        with open(thoughts_path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-200:]
    except OSError:
        return empty
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        raw = (d.get("snapshot") or {}).get("material_signals") or []
        out = []
        for s in raw:
            if not isinstance(s, dict):
                continue
            kind = s.get("kind")
            out.append({
                "kind": kind if kind in _KNOWN_KINDS else "other",
                "ref": _clean_ref(s.get("ref")),
                "detail": (s.get("detail") or "")[:120],
            })
        if out:
            return {"signals": out, "ts": d.get("ts"), "decision": d.get("decision")}
    return empty


def _thoughts_path() -> str:
    override = current_app.config.get("HEARTBEAT_THOUGHTS_PATH")
    return str(override) if override else str(_DEFAULT_THOUGHTS)


@bp.get("/api/heartbeat/signals")
def api_heartbeat_signals():
    return jsonify(read_recent_material_signals(_thoughts_path())), 200
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_heartbeat_signals.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add soveryn/app/routes/api_heartbeat.py tests/test_heartbeat_signals.py
git commit -m "feat(mission-control): /api/heartbeat/signals — current material signals from thoughts log"
```

---

### Task 2: Frontend — "flagging" block on the heartbeat panel

**Files:**
- Modify: `soveryn/app/templates/command_center.html`
- Test: `tests/test_heartbeat_signals_render.py`

**Interfaces:**
- Consumes: `GET /api/heartbeat/signals` (Task 1). Reuses the `.ares-finding` card styling + the existing `fetchJson()` helper.

- [ ] **Step 1: Write the failing test** — `tests/test_heartbeat_signals_render.py`:

```python
"""command_center renders the heartbeat 'flagging' block; /api/heartbeat/signals reachable."""
import json


def _write_thoughts(tmp_path):
    p = tmp_path / "ht.jsonl"
    p.write_text(json.dumps({
        "ts": "2026-07-03T16:00:00", "decision": "SURFACE",
        "snapshot": {"material_signals": [
            {"kind": "deadline", "ref": "AI Companion Funding", "detail": "July 10 due in 7 days"}]},
    }) + "\n")
    return str(p)


def test_command_center_has_flagging_block(client):
    # `client` fixture from tests/conftest.py (added with the Ares tile)
    resp = client.get("/")
    html = resp.get_data(as_text=True) if resp.status_code == 200 else \
           client.get("/command-center").get_data(as_text=True)
    assert "heartbeat-signals" in html
    assert "renderHeartbeatSignals" in html


def test_api_heartbeat_signals_endpoint(client, tmp_path):
    client.application.config["HEARTBEAT_THOUGHTS_PATH"] = _write_thoughts(tmp_path)
    resp = client.get("/api/heartbeat/signals")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) >= {"signals", "ts", "decision"}
    assert data["signals"][0]["kind"] == "deadline"
    assert "July 10" in data["signals"][0]["detail"]
```

> Implementer note: match the actual command-center route (`/` or `/command-center`) as done in `tests/test_ares_panel_render.py`. Use the same `client` fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_heartbeat_signals_render.py -v`
Expected: FAIL — `heartbeat-signals` not in the template.

- [ ] **Step 3: Add CSS** — in `command_center.html`, after the `.ares-feed .empty` rule added by the Ares tile, add:

```html
  /* ─── Heartbeat "flagging" block — what Aetheria is currently surfacing. ─── */
  .heartbeat-signals { display:flex; flex-direction:column; gap:6px; margin-bottom:10px; }
  .hb-signal {
    display:flex; align-items:flex-start; gap:8px; padding:7px 10px;
    background:rgba(255,255,255,0.025); border:1px solid rgba(255,255,255,0.04);
    border-left-width:3px; border-radius:6px; font-size:11px; line-height:1.4;
    color:rgba(232,227,213,0.78);
  }
  .hb-signal[data-kind="deadline"] { border-left-color:#f59e0b; }
  .hb-signal[data-kind="stall"]    { border-left-color:rgba(232,227,213,0.3); }
  .hb-signal[data-kind="other"]    { border-left-color:rgba(232,227,213,0.18); }
  .hb-signal .k { color:rgba(232,227,213,0.55); text-transform:uppercase; font-size:9px; letter-spacing:0.5px; }
  .hb-signal .r { color:rgba(232,227,213,0.9); font-weight:500; }
  .hb-signal .d { color:rgba(232,227,213,0.6); }
  .heartbeat-signals .empty { font-size:11px; color:rgba(232,227,213,0.4); padding:8px 10px; }
```

- [ ] **Step 4: Add the block to the heartbeat panel** — find `<section class="panel heartbeat-panel" ...>` and its `<div class="heartbeat-feed" ...>`. Insert, immediately **before** the `heartbeat-feed` div (so signals sit above the rhythm):

```html
      <div class="heartbeat-signals" data-heartbeat-signals aria-live="polite" aria-label="What Aetheria is flagging"></div>
```

- [ ] **Step 5: Add `renderHeartbeatSignals()` JS + wire it in** — after `renderAres()` (added by the Ares tile), add:

```javascript
  async function renderHeartbeatSignals() {
    const data = await fetchJson("/api/heartbeat/signals");
    const box = document.querySelector("[data-heartbeat-signals]");
    if (!box) return;
    const sigs = (data && data.signals) || [];
    if (sigs.length === 0) {
      box.innerHTML = '<div class="empty">Nothing flagged.</div>';
      return;
    }
    box.innerHTML = sigs.map(s => `
      <div class="hb-signal" data-kind="${s.kind}">
        <div><span class="k">${s.kind}</span> <span class="r">${(s.ref || "").replace(/</g, "&lt;")}</span>
        <br><span class="d">${(s.detail || "").replace(/</g, "&lt;")}</span></div>
      </div>`).join("");
  }
```

Then find where `renderAres();` is called in the refresh cycle and add `renderHeartbeatSignals();` beside it.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_heartbeat_signals_render.py -v`
Expected: PASS (2 passed).

- [ ] **Step 7: Regression check (explicit paths — avoid the trafilatura collection error)**

Run: `python -m pytest tests/test_heartbeat_signals.py tests/test_heartbeat_signals_render.py tests/test_api_ares.py tests/test_ares_panel_render.py tests/test_app_ui_routes.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add soveryn/app/templates/command_center.html tests/test_heartbeat_signals_render.py
git commit -m "feat(mission-control): heartbeat panel shows what Aetheria is flagging (material signals)"
```

---

## Manual verification (human, after both tasks)
Restart `soveryn-vnext.service` (loads the new route + template), load Mission Control: the heartbeat
panel now shows a "flagging" block at the top with her current signals (the July-10 deadline + stalls),
above the pulse rhythm. Requires the fleet up.
