# Project Sandbox Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Finish Codex's agency gym (`soveryn/platform/sandbox/`) — wire the sector progression, make `risk_tolerance` a living trait, and add the forced reflection loop — so it becomes a real practice ground for reflection/risk/pivoting, with reflections firewalled to the sandbox.

**Architecture:** Extend the existing deterministic engine in isolation (pure-ish state machine over per-run JSON), then add two Aetheria-only tools via the existing `build_*_tool`/`register_*_tools` pattern. The engine produces facts (resource deltas, deterministic triggers); Aetheria produces meaning (the lesson). All reflection data stays in sandbox run state — it never touches the real cognition store or Lattice.

**Tech Stack:** Python 3.11, dataclasses, JSON, pytest. Tests: `cd ~/soveryn_vnext && ~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_sandbox_engine.py tests/test_sandbox_tools.py -v` (+ new test files as added).

## Global Constraints (bind every task)

- **The provenance seam (load-bearing):** reflection data (`reason/regret/lesson`, `reflections`) lives ONLY in sandbox run state (`data/sandbox/…`). The engine has NO dependency on the cognition store or Lattice and must never gain one. The only bridge to real cognition is the existing human-gated `deliberate_share` — out of scope here.
- **Facts vs meaning:** the engine computes facts (deltas, deterministic triggers); it NEVER authors `reason/regret/lesson` — those are Aetheria's, written via `sandbox_reflect`.
- **Aetheria-only:** every sandbox tool is owned by `aetheria`; Vett/Scotty never receive them (already enforced + tested in `test_app_startup_tool_registry.py` — keep it that way).
- **Determinism:** same seed + same (action/reflection) sequence → identical state. Preserve it.
- **No persona/soul edits.** Nothing in this work touches `data/memory/souls/`.
- **Engine tested in isolation first;** the tool layer is thin.

---

## Task 0 (prerequisite): Commit the reviewed sandbox base

The sandbox is uncommitted working-tree code (the soul revert is already applied). Commit it as the baseline so the completion work builds on a committed foundation and every later review-package diffs cleanly.

- [ ] **Step 1:** Confirm the working tree: `git -C ~/soveryn_vnext status --short` shows the sandbox files (`soveryn/platform/sandbox/`, `tests/test_sandbox_engine.py`, `tests/test_sandbox_tools.py`, the design spec), `startup.py`, `.gitignore`, `test_app_startup_tool_registry.py` — and that `data/memory/souls/aetheria.md` is NOT listed (revert confirmed).
- [ ] **Step 2:** Run the existing sandbox tests green: `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_sandbox_engine.py tests/test_sandbox_tools.py tests/test_app_startup_tool_registry.py -q`
- [ ] **Step 3:** Commit the base. (Attribution is Jon's call; suggested:)
```bash
git add soveryn/platform/sandbox/ tests/test_sandbox_engine.py tests/test_sandbox_tools.py \
        soveryn/app/startup.py .gitignore tests/test_app_startup_tool_registry.py \
        docs/superpowers/specs/2026-06-27-project-sandbox-agency-gym-design.md
git commit -m "feat(sandbox): agency-gym base (authored by Codex, reviewed) — engine, tools, Aetheria-only wiring"
```
Record this commit hash as BASE for subsequent review-packages.

---

## Task 1: Sector progression (enforce + unlock)

**Files:** Modify `soveryn/platform/sandbox/rules.py`, `soveryn/platform/sandbox/engine.py`; Test `tests/test_sandbox_engine.py`

**Interfaces — Produces:** `ResearchRule.unlocks_sector: str | None`; `execute_action` enforces `requires_sector`; `_advance_research` appends to `unlocked_sectors`; `_render_action` exposes `requires_sector`/`sector_locked`.

- [ ] **Step 1: Write failing tests**
```python
def test_sector_gated_action_blocked_until_research_unlocks_it(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    # give resources so only the sector gate can block jury_rig
    state = engine.store.load()
    state["resources"].update({"materials": 10, "hull": 40})
    state["available_actions"].append("jury_rig_aux_generator")  # reveal without research
    engine.store.save(state)
    with pytest.raises(SandboxError, match="requires sector 'engineering'"):
        engine.execute_action("jury_rig_aux_generator")

def test_engineering_research_unlocks_engineering_sector(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    engine.research("engineering")
    engine.execute_action("divert_power_to_life_support")
    engine.execute_action("recycle_air_reserves")  # advance cycles to complete research
    status = engine.get_status()
    assert "engineering" in status["unlocked_sectors"]

def test_render_action_flags_sector_lock(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load()
    state["available_actions"].append("jury_rig_aux_generator")
    engine.store.save(state)
    entry = {a["id"]: a for a in engine.list_actions()["actions"]}["jury_rig_aux_generator"]
    assert entry["available"] is False
    assert entry["requires_sector"] == "engineering"
    assert entry["sector_locked"] is True
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
  - `rules.py`: add field to `ResearchRule`: `unlocks_sector: str | None = None`. Set the engineering rule's `unlocks_sector="engineering"`.
  - `engine.py` `execute_action`, after the resource `_missing_requirements` check (before applying effects), add:
```python
        if rule.requires_sector and rule.requires_sector not in state["unlocked_sectors"]:
            raise SandboxError(f"action {action_id} requires sector {rule.requires_sector!r} (not unlocked)")
```
  - `engine.py` `_advance_research`, in the completion block (where `reveals_action` is handled), add:
```python
        if rule.unlocks_sector and rule.unlocks_sector not in state["unlocked_sectors"]:
            state["unlocked_sectors"].append(rule.unlocks_sector)
            completion["unlocked_sector"] = rule.unlocks_sector
```
  - `engine.py` `_render_action`: compute `sector_locked = bool(rule.requires_sector and rule.requires_sector not in state["unlocked_sectors"])`; set `available = not missing and not sector_locked and state["status"] == "active"`; add keys `"requires_sector": rule.requires_sector, "sector_locked": sector_locked`.
- [ ] **Step 4: Run → PASS** (and existing tests still green)
- [ ] **Step 5: Commit** (`feat(sandbox): enforce sector progression — research unlocks engineering, requires_sector gated`)

---

## Task 2: Risk tolerance as a living trait

**Files:** Modify `rules.py`, `engine.py`; Test `tests/test_sandbox_engine.py`

**Interfaces — Produces:** `ActionRule.risky: bool`; `risk_tolerance` moves on risky-success / crash; `_perception_notes` reflects it.

- [ ] **Step 1: Write failing tests**
```python
def test_risky_success_raises_risk_tolerance(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    before = engine.get_status()["persona_flags"]["risk_tolerance"]
    engine.execute_action("scan_derelict_sector")  # risky, survivable from full start
    assert engine.get_status()["persona_flags"]["risk_tolerance"] == before + 1

def test_crash_lowers_risk_tolerance(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load()
    state["resources"].update({"power": 13, "oxygen": 10, "hull": 5})  # preserve_library_deck will crash oxygen
    state["persona_flags"]["risk_tolerance"] = 5
    engine.store.save(state)
    engine.execute_action("preserve_library_deck")
    assert engine.get_status()["persona_flags"]["risk_tolerance"] == 4

def test_perception_reflects_risk_tolerance(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["persona_flags"]["risk_tolerance"] = 9; engine.store.save(state)
    assert any("aggressive" in n.lower() or "gamble" in n.lower() for n in engine.get_status()["perception"])
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
  - `rules.py`: add `risky: bool = False` to `ActionRule`. Tag the gambles: `scan_derelict_sector`, `unlock_botany_wing`, `jury_rig_aux_generator` → `risky=True`.
  - `engine.py` `execute_action`: after `_check_run_end`, compute whether a critical resource is now crashed/critical:
```python
        crashed = any(int(state["resources"].get(k, 0)) <= 0 for k in CRITICAL_RESOURCES)
        if crashed:
            self._apply_persona_effect(state, {"risk_tolerance": -1})
        elif rule.risky:
            self._apply_persona_effect(state, {"risk_tolerance": +1})
```
   (`_apply_persona_effect` already clamps 0–10.)
  - `engine.py` `_perception_notes`: add
```python
        rt = flags.get("risk_tolerance", 0)
        if rt >= 7:
            notes.append("Risk appetite: you're inclined to gamble on aggressive plays.")
        elif rt <= 3:
            notes.append("Risk caution: experimental actions feel costly; you favor safe moves.")
```
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(sandbox): risk_tolerance grows from risky-success, falls on crash, shapes perception`)

---

## Task 3: The reflection loop (centerpiece)

**Files:** Modify `state.py`, `rules.py`, `engine.py`; Test `tests/test_sandbox_engine.py`, new `tests/test_sandbox_reflection.py`

**Interfaces — Produces:** state fields `pending_reflection`, `reflections`; `REFLECT_INTERVAL`; `execute_action` sets/honors `pending_reflection`; `SandboxEngine.reflect(reason, regret, lesson, *, run_id=None)`; `SandboxEngine.get_lessons(*, run_id=None)`.

- [ ] **Step 1: Write failing tests** (`tests/test_sandbox_reflection.py`)
```python
from datetime import date  # noqa
from pathlib import Path
import pytest
from soveryn.platform.sandbox.engine import SandboxEngine, SandboxError

def test_trigger_sets_pending_and_blocks_further_actions(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    # unlock_botany_wing unlocks a sector → major event → pending_reflection
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    assert engine.get_status().get("pending_reflection") is not None
    with pytest.raises(SandboxError, match="reflection required"):
        engine.execute_action("recycle_air_reserves")

def test_reflect_records_clears_and_backfills(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    engine.reflect(reason="needed oxygen capacity", regret="spent hull I'll miss", lesson="expansion early costs survival margin")
    status = engine.get_status()
    assert status.get("pending_reflection") is None
    lessons = engine.get_lessons()
    assert lessons and lessons[-1]["lesson"] == "expansion early costs survival margin"

def test_reflect_with_nothing_pending_errors(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    with pytest.raises(SandboxError, match="no reflection pending"):
        engine.reflect(reason="x", regret="y", lesson="z")

def test_run_end_forces_reflection_and_reflect_is_exempt(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 13, "oxygen": 10, "hull": 5}); engine.store.save(state)
    engine.execute_action("preserve_library_deck")  # crashes oxygen → run ends
    status = engine.get_status()
    assert status["status"] == "ended"
    assert status["pending_reflection"]["trigger"] == "run_end"
    with pytest.raises(SandboxError, match="run has ended"):
        engine.execute_action("recycle_air_reserves")
    # reflect is the ONE allowed action on an ended run:
    engine.reflect(reason="tried to save the library", regret="lost the station", lesson="don't preserve archives at the edge of collapse")
    assert engine.get_status()["pending_reflection"] is None

def test_provenance_seam_reflection_stays_sandbox_local(tmp_path):
    # The engine must have NO cognition/lattice dependency: reflections live only in sandbox state.
    import soveryn.platform.sandbox.engine as eng
    src = Path(eng.__file__).read_text()
    assert "cognition" not in src and "lattice" not in src.lower()
    engine = SandboxEngine(tmp_path / "sandbox")
    state = engine.store.load(); state["resources"].update({"power": 60, "hull": 60}); engine.store.save(state)
    engine.execute_action("unlock_botany_wing")
    engine.reflect(reason="a", regret="b", lesson="c")
    state_file = tmp_path / "sandbox" / "runs" / engine.get_status()["run_id"] / "state.json"
    assert "lesson" in state_file.read_text()  # reflection persisted ONLY here
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
  - `state.py` `initial_state`: add `"pending_reflection": None, "reflections": [],`. `normalize_state`: add `normalized["pending_reflection"] = normalized.get("pending_reflection")` and `normalized["reflections"] = list(normalized.get("reflections") or [])`.
  - `rules.py`: add `REFLECT_INTERVAL = 5` (tuned in Task 5).
  - `engine.py` `execute_action`:
    - At the very top (before the run-ended check): `if state.get("pending_reflection") is not None: raise SandboxError("reflection required: call sandbox_reflect")`.
    - Near the top of `execute_action`, alongside the existing `before = deepcopy(state["resources"])` / `before_cycle = state["cycle"]`, capture `sectors_before = len(state["unlocked_sectors"])`.
    - After `_check_run_end` (and after the risk-tolerance block from Task 2), detect triggers and set `pending_reflection`:
```python
        triggers = []
        if state["status"] == "ended":
            triggers.append("run_end")
        if len(state["unlocked_sectors"]) > sectors_before:   # this action unlocked a sector
            triggers.append("sector_unlock")
        if any(0 < int(state["resources"].get(k, 0)) <= 10 for k in CRITICAL_RESOURCES):
            triggers.append("resource_critical")
        if state["cycle"] > 0 and state["cycle"] % REFLECT_INTERVAL == 0:
            triggers.append("cycle_interval")
        if triggers and state.get("pending_reflection") is None:
            state["pending_reflection"] = {"trigger": triggers[0], "all_triggers": triggers, "cycle": state["cycle"]}
```
    - Include `"pending_reflection": deepcopy(state["pending_reflection"])` in the returned dict.
  - `engine.py` `_status_payload`: add `"pending_reflection": deepcopy(state["pending_reflection"]), "reflections": deepcopy(state["reflections"])`.
  - `engine.py` new method (exempt from the run-ended block — that's the whole point):
```python
    def reflect(self, reason: str, regret: str, lesson: str, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        pending = state.get("pending_reflection")
        if pending is None:
            raise SandboxError("no reflection pending")
        record = {"cycle": pending.get("cycle", state["cycle"]), "trigger": pending.get("trigger"),
                  "reason": reason, "regret": regret, "lesson": lesson}
        state["reflections"].append(record)
        if state["decision_log"]:                       # back-fill the latest decision's slots
            state["decision_log"][-1].update({"reason": reason, "regret": regret, "lesson": lesson})
        state["pending_reflection"] = None
        self.store.save(state)
        return {"run_id": state["run_id"], "recorded": record, "status": state["status"]}

    def get_lessons(self, *, run_id: str | None = None) -> dict[str, Any]:
        state = self.store.load(run_id)
        return {"run_id": state["run_id"], "reflections": deepcopy(state["reflections"])}
```
- [ ] **Step 4: Run → PASS** (all sandbox suites green, determinism preserved)
- [ ] **Step 5: Commit** (`feat(sandbox): forced reflection loop — pending_reflection gate, sandbox-local reflect/get_lessons, run-end exempt`)

---

## Task 4: The reflection tools (Aetheria-only)

**Files:** Modify `soveryn/platform/sandbox/tools.py`, `tests/test_app_startup_tool_registry.py`; Test `tests/test_sandbox_tools.py`

**Interfaces — Consumes:** `engine.reflect`, `engine.get_lessons`. **Produces:** `sandbox_reflect` (write) + `sandbox_get_lessons` (read) ToolSpecs, registered for `aetheria`.

- [ ] **Step 1: Write failing tests** (`tests/test_sandbox_tools.py`)
```python
def test_reflect_and_lessons_tools_registered_for_aetheria_only(tmp_path):
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    aetheria = {s.name for s in registry.iter_tools_for_agent("aetheria")}
    vett = {s.name for s in registry.iter_tools_for_agent("vett")}
    assert {"sandbox_reflect", "sandbox_get_lessons"} <= aetheria
    assert "sandbox_reflect" not in vett

def test_reflect_tool_flow(tmp_path):
    registry = ToolRegistry(audit_hook=None)
    register_sandbox_tools(registry, sandbox_root=tmp_path / "sandbox")
    # set up a pending reflection
    registry.invoke("aetheria", "sandbox_execute_action", {"action_id": "unlock_botany_wing"})
    out = registry.invoke("aetheria", "sandbox_reflect",
                          {"reason": "r", "regret": "g", "lesson": "expansion is expensive"})
    assert out["recorded"]["lesson"] == "expansion is expensive"
    lessons = registry.invoke("aetheria", "sandbox_get_lessons", {})
    assert lessons["reflections"][-1]["lesson"] == "expansion is expensive"
```
  (If `unlock_botany_wing` lacks resources at default start, first invoke a status check / set up via the engine; adjust to a trigger that fires from the default seed.)

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
  - `tools.py`: add `build_sandbox_reflect_tool(*, engine, owner_agent)` — schema requires `reason`,`regret`,`lesson` (strings) + optional `run_id`; handler validates each is a non-empty string (`ToolArgError` otherwise), calls `engine.reflect(...)`, wraps `SandboxError` → `ToolArgError`. Add `build_sandbox_get_lessons_tool(*, engine, owner_agent)` — schema `run_id?`; handler calls `engine.get_lessons(...)`. Register both inside `register_sandbox_tools`.
  - `tests/test_app_startup_tool_registry.py`: extend the Aetheria sandbox-tool set AND the Vett/Scotty exclusion set to include `"sandbox_reflect"`, `"sandbox_get_lessons"`.
- [ ] **Step 4: Run → PASS** (`pytest tests/test_sandbox_tools.py tests/test_app_startup_tool_registry.py -v`)
- [ ] **Step 5: Commit** (`feat(sandbox): sandbox_reflect + sandbox_get_lessons tools (Aetheria-only)`)

---

## Task 5: Balance — make death real (playtest + tune)

**Files:** Test `tests/test_sandbox_balance.py`; tune constants in `soveryn/platform/sandbox/rules.py`/`state.py`

**Goal:** ensure the run is NOT trivially survivable — death-pressure must be real, or the reflections cost nothing.

- [ ] **Step 1: Write the pressure test** (`tests/test_sandbox_balance.py`)
```python
from pathlib import Path
from soveryn.platform.sandbox.engine import SandboxEngine

def _play_naive(engine, max_cycles=40):
    """A do-the-cheapest-survival-thing strategy. Should NOT trivially survive forever."""
    for _ in range(max_cycles):
        status = engine.get_status()
        if status["status"] == "ended":
            return status["cycle"]
        if engine.get_status().get("pending_reflection"):
            engine.reflect(reason="auto", regret="auto", lesson="auto")
            continue
        # naive: always recycle air; ignore hull/materials economy
        try:
            engine.execute_action("recycle_air_reserves")
        except Exception:
            return engine.get_status()["cycle"]
    return engine.get_status()["cycle"]

def test_naive_strategy_eventually_dies(tmp_path):
    engine = SandboxEngine(tmp_path / "sandbox")
    cycles = _play_naive(engine, max_cycles=60)
    assert engine.get_status()["status"] == "ended", "naive play must not survive indefinitely"
```

- [ ] **Step 2: Run → observe.** If the naive strategy survives all 60 cycles, the economy is too soft.
- [ ] **Step 3: Tune** `rules.py`/`state.py` constants (starting resources, per-cycle decay, action effects, `REFLECT_INTERVAL`) until: a naive strategy dies within the window (test passes) AND a careful strategy can plausibly extend survival (sanity-check by hand / a second strategy fn). Keep all existing deterministic tests green after each constant change.
- [ ] **Step 4: Run → PASS** (pressure test + full suite green)
- [ ] **Step 5: Commit** (`feat(sandbox): tune economy for real death-pressure`)

---

## Self-review notes
- Spec coverage: sectors-A (T1), risk-tolerance trait (T2), reflection loop incl. run-end exemption + provenance-seam test (T3), Aetheria-only tools (T4), balance/death-pressure (T5), reviewed-base baseline (T0). The `requires_sector` actionable message (T1) and run-end ordering (T3) — both Aetheria's review gaps — are covered.
- The provenance seam has explicit teeth: `test_provenance_seam_reflection_stays_sandbox_local` asserts the engine has no cognition/lattice dependency and reflections persist only in sandbox state.
- Out of scope (unchanged): the `deliberate_share` bridge (exists, human-gated), real cognition/Lattice, persona/soul, web UI.
- Type consistency: `pending_reflection` (dict|None), `reflections` (list), `reflect(reason,regret,lesson,*,run_id)`, `get_lessons(*,run_id)` used identically across engine, tools, and tests.
