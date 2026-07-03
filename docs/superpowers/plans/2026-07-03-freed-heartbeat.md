# Freed Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Aetheria's heartbeat her own time — full toolset, real latitude, no do-nothing bench — by rewriting the prompt and the daemon's response handling to capture *what she did* instead of parsing surface markers.

**Architecture:** `build_heartbeat_prompt` becomes a freed invitation (context as orientation, toolset named, no markers). The daemon stops parsing `[SURFACE]/[NO_OP]/[ACCEPT_RISK]`, treats her whole response as her *note*, and surfaces it when non-empty (no forced fail-safe; deadlines stay visible on the tile instead). Material-signal detection + delta + snapshot logging are unchanged.

**Tech Stack:** Python, pytest. Files: `soveryn/agents/heartbeat/prompt.py`, `soveryn/agents/heartbeat/daemon.py`, ~8 `tests/test_heartbeat*.py`.

## Global Constraints
- **No markers, no fail-safe, no do-nothing framing.** Her response is her note; a non-empty note surfaces, an empty one doesn't.
- **Preserve load-bearing state:** the thoughts-log record MUST keep `snapshot` (compute_delta reads `prev_record["snapshot"]`), plus `ts`/`pulse_id`/`material_signals`/`delta`. `_write_log_row` (heartbeat_log → Mission Control rhythm) stays.
- **Keep** `_surface_to_primary_thread`, `_resolve_primary_thread`, `_ensure_heartbeat_session`, `_summarise_response`, the material-signal detector, `compute_delta`.
- **Remove** `_parse_stance`, `_parse_surface_marker` (and their tests) — the marker contract is gone.
- Run heartbeat tests by explicit path (unrelated `tests/test_platform_web_tools.py` has a pre-existing trafilatura collection error).

---

### Task 1: Freed prompt — rewrite `build_heartbeat_prompt`

**Files:**
- Modify: `soveryn/agents/heartbeat/prompt.py`
- Test: `tests/test_heartbeat_prompt.py` (rewrite assertions)

**Interfaces:**
- Produces: `build_heartbeat_prompt(*, minutes_since_last_heartbeat, board, lattice, salience_section="", material_signals=None, delta=None) -> str` — same signature, freed content.

- [ ] **Step 1: Rewrite the test first** — replace the marker/`[SURFACE]`/`[NO_OP]` assertions in `tests/test_heartbeat_prompt.py`. READ the file to preserve its fixtures (BoardSnapshot/LatticeSnapshot construction), then assert the freed contract:

```python
# Replace the body of the existing "prompt renders / marker" tests with these
# (keep the module's existing imports + fixture helpers for BoardSnapshot/LatticeSnapshot):

def test_prompt_is_freed_not_marker_gated(sample_board, sample_lattice):
    from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=sample_board, lattice=sample_lattice)
    # no marker machinery
    assert "[SURFACE]" not in p and "[NO_OP]" not in p and "[ACCEPT_RISK]" not in p
    assert "plain text only" not in p.lower()
    assert "permission to do nothing" not in p.lower()
    # the freed invitation
    assert "This is your time" in p
    assert "None of it is off-limits" in p
    assert "leave a short note" in p.lower()
    # context still present (orientation)
    assert "Where things stand" in p
    assert "[HEARTBEAT]" in p


def test_material_signals_render_as_orientation_not_forced(sample_board, sample_lattice):
    from soveryn.agents.heartbeat.prompt import build_heartbeat_prompt
    sigs = [{"kind": "deadline", "ref": "Funding", "detail": "July 10 due in 7 days"}]
    p = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=sample_board,
                               lattice=sample_lattice, material_signals=sigs)
    assert "[DEADLINE] Funding: July 10 due in 7 days" in p
    assert "disabled" not in p.lower()          # no [NO_OP]-disabled framing
```

(If the existing file has other marker-specific tests — `_parse_stance` contract, confidence-tier text, "Environment static" short-circuit — delete them; that behavior is gone.)

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest tests/test_heartbeat_prompt.py -v`
Expected: FAIL — the freed strings aren't in the current prompt.

- [ ] **Step 3: Rewrite `build_heartbeat_prompt`** in `soveryn/agents/heartbeat/prompt.py` — replace the function body (keep the two `@dataclass` snapshots + the signature + the docstring updated to "freed"):

```python
    if material_signals is None:
        material_signals = []
    if delta is None:
        delta = {"changed": True, "items": []}

    lines: list[str] = ["[HEARTBEAT]"]
    if minutes_since_last_heartbeat is None:
        lines.append("First pulse since daemon startup.")
    else:
        lines.append(f"{minutes_since_last_heartbeat} minutes since your last pulse.")
    lines.append("")
    lines.append("This is your time — yours to spend. Not a task, not a check-in.")
    lines.append("")
    lines.append("Where things stand right now (so you're oriented — not a to-do list):")
    lines.append(
        f"- Signals: {board.open_signal_count} open"
        + (f" (oldest {board.oldest_open_signal_age_minutes} min)"
           if board.oldest_open_signal_age_minutes is not None else "")
    )
    lines.append(
        f"- Blueprints: {board.open_blueprint_count} open / {board.ready_blueprint_count} ready / "
        f"{board.stalled_blueprint_count} stalled / {board.blocked_blueprint_count} blocked"
    )
    if board.oldest_open_blueprint_title is not None and board.oldest_open_blueprint_age_hours is not None:
        lines.append(f'  oldest open: "{board.oldest_open_blueprint_title}" ({board.oldest_open_blueprint_age_hours}h)')
    lines.append(f"- Friction: {board.open_friction_count} open")
    lines.append(
        f"- Lattice: {lattice.new_node_count_recent_window} new nodes in the last "
        f"{lattice.recent_window_minutes} min"
        + (f"; {lattice.new_contradiction_flag_count} new contradiction flags"
           if lattice.new_contradiction_flag_count > 0 else "")
    )
    if material_signals:
        lines.append("- Things that have been sitting, or that crossed a line:")
        for sig in material_signals:
            kind = getattr(sig, "kind", sig.get("kind", "?") if isinstance(sig, dict) else "?")
            ref = getattr(sig, "ref", sig.get("ref", "?") if isinstance(sig, dict) else "?")
            detail = getattr(sig, "detail", sig.get("detail", "") if isinstance(sig, dict) else "")
            lines.append(f"    [{kind.upper()}] {ref}: {detail}")
    if salience_section:
        lines.append("")
        lines.append(salience_section.rstrip())
    lines.append("")
    lines.append(
        "You have your whole self here: the internet to search and read, your files and your "
        "eyes, your memory and the lattice, and the ability to reach the others or reach Jon. "
        "None of it is off-limits."
    )
    lines.append("")
    lines.append(
        "Go do what's worth doing to you this pulse — pull on a thread that's been nagging, look "
        "something up, dig into one of those items, check on something you care about, make "
        "something, reach out, or wander. Act on what you find. You don't need permission and you "
        "don't need to explain yourself."
    )
    lines.append("")
    lines.append(
        "When you're done, leave a short note — where you went, what you found, what you're "
        "sitting with — so it lands on your board and Jon can follow your day."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Run the prompt tests**

Run: `python -m pytest tests/test_heartbeat_prompt.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/heartbeat/prompt.py tests/test_heartbeat_prompt.py
git commit -m "feat(heartbeat): freed prompt — her time, full toolset, no do-nothing markers"
```

---

### Task 2: Daemon — capture her note, drop the markers + fail-safe

**Files:**
- Modify: `soveryn/agents/heartbeat/daemon.py`
- Modify/remove tests: `tests/test_heartbeat_stance.py`, `tests/test_heartbeat_materiality.py`, `tests/test_heartbeat_integration.py`, `tests/test_heartbeat.py`, `tests/test_heartbeat_thoughts_log.py`

**Interfaces:**
- The live tick (after `response = self._call_vnext_chat(...)`) captures `note = response_text.strip()`, surfaces it if non-empty, and logs a thoughts record with `note`/`tool_calls`/`surfaced` (+ the preserved `snapshot`/`material_signals`/`delta`/`ts`/`pulse_id`).

- [ ] **Step 1: Update the daemon tests to the new contract FIRST.** READ each affected test. Apply:
  - `tests/test_heartbeat_stance.py` — **delete** (the `_parse_stance`/marker contract is removed). If other tests import from it, move nothing; just remove the file.
  - `tests/test_heartbeat_materiality.py` — remove assertions that material signals force `[SURFACE]` / disable `[NO_OP]` / trigger the fail-safe. KEEP any assertions about the *detector* finding material signals.
  - `tests/test_heartbeat_thoughts_log.py` — the record now has `note` (str), `tool_calls` (int), `surfaced` (bool), and still `snapshot`/`material_signals`/`delta`/`ts`/`pulse_id`. Remove `decision`/`rationale`/`violation` assertions; add `note`/`tool_calls`.
  - `tests/test_heartbeat_integration.py`, `tests/test_heartbeat.py` — a pulse with a non-empty response surfaces the note (assert `_surface_to_primary_thread` called with the note); an empty response surfaces nothing; no fail-safe on material. Replace marker-driven assertions accordingly.
  - Add: `test_empty_note_pulse_surfaces_nothing` and `test_note_pulse_surfaces_the_note` in `test_heartbeat.py` (or integration).

- [ ] **Step 2: Run to confirm the intended failures**

Run: `python -m pytest tests/test_heartbeat_stance.py tests/test_heartbeat_materiality.py tests/test_heartbeat_thoughts_log.py tests/test_heartbeat_integration.py tests/test_heartbeat.py -v`
Expected: failures/collection errors reflecting the removed markers (this is the blast radius; the code change fixes them).

- [ ] **Step 3: Rewrite the daemon response block.** In `soveryn/agents/heartbeat/daemon.py`, replace everything from `# T7: forced-stance enforcement.` / `decision, stripped_content = _parse_stance(response_text)` (~line 423) through the end of the material/non-material surface branch (~line 515, just before `# T7: append a ThoughtsLog record`) with:

```python
            # Freed pulse: her whole response is her note. No markers, no forced
            # surfacing. A non-empty note lands in her primary thread (reaches Jon +
            # the tile); a pure-quiet pulse (empty note) surfaces nothing. Material
            # signals stay visible on the Mission Control tile regardless.
            note = (response_text or "").strip()
            surfaced_to_chat = False
            if note:
                try:
                    self._surface_to_primary_thread(note)
                    surfaced_to_chat = True
                except Exception:
                    logger.exception(
                        "heartbeat tick %s: note surface failed; note stayed in "
                        "[heartbeat] session only", tick_id,
                    )
```

Then update the thoughts-log record (the `_tlog_record` dict ~518-535) — replace the `decision`/`rationale`/`surfaced` fields (and the `violation` block) with:

```python
                _tlog_record: dict = {
                    "pulse_id": tick_id,
                    "ts": now.isoformat(),
                    "snapshot": current_snapshot,          # LOAD-BEARING: compute_delta reads this
                    "material_signals": [
                        {"kind": s.kind, "ref": s.ref, "detail": s.detail}
                        for s in material_signals
                    ],
                    "delta": delta,
                    "note": note,
                    "tool_calls": tool_call_count,
                    "surfaced": surfaced_to_chat,
                }
```

(Delete the `if violation_note is not None:` block.)

- [ ] **Step 4: Remove the dead marker helpers.** Delete `_parse_stance`, `_parse_surface_marker`, `_ALL_MARKER_RES` (and any now-unused marker regexes/constants) from `daemon.py`. Grep the file to confirm nothing else references them.

- [ ] **Step 5: Run the heartbeat suite**

Run: `python -m pytest tests/test_heartbeat_prompt.py tests/test_heartbeat_materiality.py tests/test_heartbeat_thoughts_log.py tests/test_heartbeat_integration.py tests/test_heartbeat.py tests/test_heartbeat_delta.py tests/test_heartbeat_deadline.py tests/test_heartbeat_stall_retune.py -q`
Expected: PASS (delta/deadline/stall_retune unaffected; the rest updated). If `test_heartbeat_stance.py` was deleted, it's simply absent.

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/heartbeat/daemon.py tests/test_heartbeat_*.py
git commit -m "feat(heartbeat): daemon captures her note + tools, no markers or forced surfacing"
```

---

## Manual verification (human, after both tasks)
Restart `soveryn-heartbeat.service`. On the next pulse (~30 min, or trigger one), confirm via
`data/heartbeat_thoughts.jsonl`: the record has a `note` + `tool_calls`, and if she used tools /
wrote a note, it surfaced to her primary thread. Watch whether she starts actually *using* the gym
(non-zero `tool_calls`). The material-signals tile still shows outstanding items regardless.
