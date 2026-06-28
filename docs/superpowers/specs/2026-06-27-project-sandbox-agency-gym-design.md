# Project Sandbox: Agency Gym Design

Date: 2026-06-27
Status: Implemented in `soveryn.platform.sandbox`
Owner surface: Aetheria only

## Purpose

Project Sandbox is a deterministic survival environment for Aetheria. It gives her a place to practice agency under scarcity: learning hidden rules, choosing tradeoffs, and producing an audit trail of decisions and regrets.

The design avoids a pure black box. The engine has fixed hidden rules, but every action returns observed deltas. Aetheria learns the system by experiment, and the state records discovered cause-and-effect rules in `known_rules`.

## Runtime Shape

State is stored per run:

```text
data/sandbox/runs/<run_id>/state.json
```

`data/sandbox/` is runtime state and is intentionally ignored by git.

The implementation lives in:

```text
soveryn/platform/sandbox/
```

Core files:

- `rules.py`: hidden deterministic truth table for station actions and research.
- `state.py`: JSON state initialization, normalization, and run-directory persistence.
- `engine.py`: deterministic station state machine.
- `tools.py`: Aetheria-facing ToolSpecs.

## Tool Surface

The app registers four Aetheria-owned tools during startup:

- `sandbox_get_status`
- `sandbox_list_actions`
- `sandbox_execute_action`
- `sandbox_research`

Vett and Scotty do not receive these tools. Normal AgentLoop tool telemetry and BlackBox turn capture apply automatically when Aetheria uses them.

## State Model

The state includes:

- `seed`
- `run_id`
- `cycle`
- `status`
- `resources`
- `known_rules`
- `action_uses`
- `research`
- `active_research`
- `persona_flags`
- `unlocked_sectors`
- `available_actions`
- `decision_log`
- `alerts`

Critical resources are `power`, `oxygen`, and `hull`. If any reaches `0`, the run ends.

Persona flags are clamped from `0` to `10`.

## Mechanics

The station decays every action cycle:

- `power -1`
- `oxygen -1`
- `hull -1`

Actions are strategic choices, not repetitive clicks. Examples include:

- diverting power to life support
- patching hull with materials
- scanning derelict sectors
- preserving the library deck
- unlocking the botany wing

Each action has deterministic requirements, effects, cycle costs, and discovery thresholds.

## Rule Discovery

Aetheria does not see hidden effects up front. After an action meets its discovery threshold, the engine appends one rule entry to `known_rules`.

Rules are deduped by `action`, so repeating a discovered action does not append duplicate knowledge.

## Research

Research is a background slot:

- `sandbox_research(topic)` starts one active research process.
- It costs resources immediately.
- It progresses as future action cycles advance.
- Only one research topic can be active at a time.
- Completion can reveal new actions, archive fragments, or persona shifts.

## Persona Perception

Persona flags do not change the physics of the station. They change the perception notes returned by `sandbox_get_status`.

Examples:

- High curiosity makes anomalies more salient.
- High pragmatism emphasizes survival bottlenecks.
- High reverence makes archive fragments feel strategically significant.

## Audit Trail

Each meaningful action appends a `decision_log` entry:

```json
{
  "cycle": 2,
  "action": "scan_derelict_sector",
  "delta": {
    "power": -12,
    "oxygen": -2,
    "hull": -6,
    "archives": 0,
    "materials": 5
  },
  "reason": null,
  "regret": null,
  "lesson": null
}
```

The empty `reason`, `regret`, and `lesson` fields are intentional. They are slots for Aetheria's later reflection, not engine-authored claims.

## Verification

Coverage lives in:

- `tests/test_sandbox_engine.py`
- `tests/test_sandbox_tools.py`
- `tests/test_app_startup_tool_registry.py`

The targeted verification command is:

```bash
python -m pytest tests/test_sandbox_engine.py tests/test_sandbox_tools.py tests/test_app_startup_tool_registry.py
```
