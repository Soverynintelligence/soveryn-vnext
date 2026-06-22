# Continuous Cognition Instance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Aetheria a dedicated full-model cognition instance that runs her background thinking off the chat slot, and lets her evolve *how she communicates with Jon* under hard architectural safety rails.

**Architecture:** A second llama-server (`:8091`, her full Gemma 4 31B) on a freed Quadro hosts a two-tier cognition loop (real-time notice / quiet-time integrate). A manner-reflection pipeline turns conversations into evidence-backed reflection memories, distilled into a small "sense-of-us" note injected into foreground context as ambient observation. Three hard guards (Jon-originated evidence, write-isolation, priority-trigger split) keep autonomous self-application tethered and non-drifting. A Mission Control view + temporary propose-mode bake-in keep it observable and earnable.

**Tech Stack:** Python 3.11 (`~/miniconda3/envs/soveryn`), llama.cpp router (HEAD build, `:8090` foreground / new `:8091` cognition), SQLite lattice (`data/memory/lattice_vnext.db`), Flask (`:5001` app + `/api/cognition/*`), systemd `--user` units, pytest.

**Source spec:** `docs/superpowers/specs/2026-06-22-continuous-cognition-design.md` (read it first).

## Global Constraints

- **Scope fence:** the pipeline adapts MANNER only (tone, pacing, when-to-ask, check-in cadence, openings/closings). Values, identity, beliefs, and peer-treatment are anchored and OUT of scope.
- **Write-isolation (hard):** the cognition pipeline writes ONLY to its own manner/reflection lattice region (`provenance.region = "cognition"`). It is barred — at the store boundary, asserted in code — from souls / persona / pinned / values. Never relax this to "the classifier handles it."
- **Jon-originated evidence:** a manner-note line may cite only Jon's signals (his turns/reactions), never Aetheria's own outputs. Enforced in the gate.
- **Ambient not instruction:** the sense-of-us note is injected as observation ("Jon reads hedging as noise"), never as directive ("be direct"). Per feedback_ambient_context_not_instruction.
- **Cache discipline:** the note lives in the cache-stable prelude (changes per cognition cycle, not per turn). Do not splice volatile per-turn data into the prelude.
- **Decoupling:** foreground (`:8090`) must be unaffected by `:8091` being down or busy. No code path makes a foreground response depend on the cognition instance.
- **Test env:** run tests with `~/miniconda3/envs/soveryn/bin/python -m pytest` (NOT bare python — base env inflates failures). Per reference_soveryn_test_env.
- **Hardware gate:** `:8091` needs a genuinely free Quadro (post-Spark, when Vett/Scotty/Ares vacate to the DGX Sparks). Phase 1 tasks that require the physical GPU are marked [HW]; everything else is buildable/testable now against tmp dbs + fakes.

---

## Phase 1 — Infrastructure: the `:8091` cognition instance (execution-ready)

**Outcome:** her full model serving on `:8091`, pinned to the freed Quadro, managed by a systemd unit, with foreground decoupling proven.

### File structure
- Create: `~/.config/systemd/user/soveryn-cognition-instance.service` — the `:8091` llama-server unit.
- Modify: `~/soveryn_vnext/runtime/router-presets.ini` — add a `[cognition-aetheria]` section OR a standalone preset (decision in Task 1).
- Modify: `soveryn/config/runtime.py` — add the cognition-instance endpoint (`COGNITION_INSTANCE_URL`, default `http://127.0.0.1:8091`).
- Create: `tests/test_cognition_instance_config.py`.

### Task 1: Cognition-instance serving config

**Files:**
- Create: `~/.config/systemd/user/soveryn-cognition-instance.service`
- Test: `tests/test_cognition_instance_config.py`

**Interfaces:**
- Produces: a reachable `http://127.0.0.1:8091/health` serving alias `aetheria-cognition` (her full Gemma 4 31B), pinned to the freed Quadro via `--device`.

- [ ] **Step 1:** Write a unit modeled on `soveryn-cognition.service` (the existing `:8089` Gemma surface) but: full model (`google_gemma-4-31B-it-Q8_0.gguf` + mmproj), `--port 8091`, `--device <freed-Quadro CUDA id>`, `--alias aetheria-cognition`, `WantedBy=soveryn.target`. Reuse the LD_LIBRARY_PATH cuda-compat line from `soveryn-router.service` (HEAD build needs it).
- [ ] **Step 2 [HW]:** `systemctl --user daemon-reload && systemctl --user start soveryn-cognition-instance`; poll `:8091/health` → 200. (Blocked until a Quadro is free; until then validate unit-file shape via `test_systemd_units_shape.py` pattern.)
- [ ] **Step 3:** Add a unit-shape test (mirror `tests/test_systemd_units_shape.py`): asserts the unit exists, targets `:8091`, sets `--device`, `WantedBy=soveryn.target`, and carries the cuda-compat env line.
- [ ] **Step 4:** Run `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_systemd_units_shape.py -v` → PASS.
- [ ] **Step 5:** Commit (`feat(cognition): :8091 cognition-instance systemd unit`).

### Task 2: Endpoint wiring + decoupling guarantee

**Files:**
- Modify: `soveryn/config/runtime.py` (add `COGNITION_INSTANCE_URL`)
- Test: `tests/test_cognition_instance_config.py`

**Interfaces:**
- Produces: `runtime.COGNITION_INSTANCE_URL` (str, default `http://127.0.0.1:8091`), read by the daemon (Phase 2). Foreground chat path must NOT import or depend on it.

- [ ] **Step 1:** Failing test: `COGNITION_INSTANCE_URL` exists, defaults to `http://127.0.0.1:8091`, env-overridable via `SOVERYN_COGNITION_INSTANCE_URL`.
- [ ] **Step 2:** Failing test: a grep/import guard — the foreground chat module (`soveryn/app/routes` chat path) does not import the cognition daemon module (decoupling regression guard).
- [ ] **Step 3:** Run → FAIL.
- [ ] **Step 4:** Implement the config field (mirror existing `MODEL_SERVERS` / URL config patterns).
- [ ] **Step 5:** Run → PASS. Commit (`feat(cognition): cognition-instance endpoint config + decoupling guard`).

---

## Phase 2 — Pipeline: notice → reflect → integrate

**Outcome:** the agent-parameterized manner-reflection pipeline producing evidence-backed reflection memories and the distilled sense-of-us note. Built against tmp dbs + a fake model — fully testable with no hardware.

### File structure
- Create: `soveryn/agents/cognition/__init__.py`
- Create: `soveryn/agents/cognition/reflect.py` — reflection pass (calls `:8091`, agent-parameterized).
- Create: `soveryn/agents/cognition/note.py` — sense-of-us note store: read / distill (bounded rewrite) / version history, in the lattice `cognition` region.
- Create: `soveryn/agents/cognition/daemon.py` — two-tier loop (real-time tick + quiet-time deep run + priority trigger). Model on `soveryn/agents/dream/daemon.py`.
- Create: `soveryn/agents/cognition/config.py` — cadence, idle threshold, salience threshold, note size cap, decay policy.
- Modify: `soveryn/platform/salience/observer.py` — real-time tier emits manner candidates into the cognition buffer (extend, don't duplicate).
- Modify: foreground prompt assembly (the prelude builder — locate at build time) — inject the note as ambient observation in the cache-stable region.
- Tests: `tests/test_cognition_reflect.py`, `tests/test_cognition_note.py`, `tests/test_cognition_daemon.py`, `tests/test_cognition_injection.py`.

### Interfaces (contracts later tasks rely on — finalize names against live code at build)
- `reflect(agent: str, turns: list[Turn], prior_note: str, model_url: str) -> list[CandidateObservation]`
- `CandidateObservation{ text: str, scope: "manner"|"value"|"unsure", citations: list[turn_id], jon_originated: bool }`
- `NoteStore.distill(agent: str, memories: list[ReflectionMemory]) -> NoteVersion` (bounded rewrite, decay of unreinforced lines)
- `NoteStore.current(agent: str) -> str` (read for foreground injection)

### Tasks (each TDD, fake model + seeded tmp lattice/conv; finalize per-step code at build)
- [ ] **T2.1 Reflection pass** — `reflect()` turns seeded conversation turns into candidate observations. Tests: produces candidates; each carries citations; no-signal input → empty.
- [ ] **T2.2 Reflection memory store** — write candidates that pass the gate (Phase 3) into the lattice `cognition` region with citations as provenance. Tests: persisted with `region="cognition"`, citations round-trip.
- [ ] **T2.3 Note distill (bounded rewrite + decay)** — `distill()` regenerates a size-capped note; unreinforced lines decay; contradictions reconcile (newer supersedes). Tests: stays under cap; decayed line drops; reinforced line persists.
- [ ] **T2.4 Two-tier daemon** — real-time tick marks candidates; quiet-time deep run (idle threshold) reflects + gates + distills. Tests (fake clock): deep run only fires after idle threshold; real-time never rewrites the note.
- [ ] **T2.5 Priority trigger** — high-salience flag forces an immediate deep *pass + surface*, does NOT rewrite the note. Tests: surface emitted immediately; note version unchanged by the trigger alone.
- [ ] **T2.6 Foreground injection** — note spliced into the cache-stable prelude as ambient observation. Tests: note text present in assembled prelude; framed as observation (no imperative); absent/last-good when `:8091`/note missing (decoupling).

---

## Phase 3 — Guards: the hard safety rails

**Outcome:** the three load-bearing guards, enforced in code with negative tests. This phase is woven into Phase 2's gate but is called out separately because it is the safety contract and gets the heaviest, adversarial testing.

### File structure
- Create: `soveryn/agents/cognition/gate.py` — the three-check worth-keeping gate.
- Modify: `soveryn/platform/lattice/legacy.py` (or the lattice write boundary) — enforce region write-isolation.
- Tests: `tests/test_cognition_gate.py`, `tests/test_cognition_write_isolation.py`.

### Interfaces
- `gate(candidate: CandidateObservation, existing_note: str) -> "integrate"|"surface"|"drop"`
- Lattice write boundary: a writer constructed for the cognition pipeline rejects any write whose target is not `region="cognition"`.

### Tasks (TDD — negative tests are the point)
- [ ] **T3.1 Scope classifier + conservative default** — manner → integrate; value-reaching → surface; unsure → surface. Test: each path; ambiguous input defaults to surface, never integrate.
- [ ] **T3.2 Jon-originated evidence** — candidate citing only Aetheria's own outputs → `drop` (or surface), never integrate. Test: own-output-cited rejected; Jon-cited accepted. (Echo-chamber kill-switch.)
- [ ] **T3.3 Write-isolation (hard, store boundary)** — the cognition writer, handed a candidate mislabeled to target souls/persona/values, CANNOT write there — raises/refuses at the store boundary. Test: attempt to write a non-`cognition` region via the cognition writer → rejected; worst case is a `cognition`-region manner line.
- [ ] **T3.4 Relationship-scoping** — the note applies with-Jon only; a manner generalized to a peer context is treated as value-reaching → surface. Test: peer-context application blocked.
- [ ] **T3.5 Gate integration** — full gate runs the three checks in order, fail-any → no integrate. Test: each fails the right way; clean candidate integrates.

---

## Phase 4 — UI: Mission Control cognition view + `/api/cognition/*`

**Outcome:** Jon can see the live note, the change feed (with evidence + scope call), per-cycle diffs, revert a line, purge a window, and receive pushed drift audits. Follows the `/api/coord` + command_center pattern shipped 2026-06-22.

### File structure
- Create: `soveryn/app/routes/api_cognition.py` — read + control endpoints (localhost-only writes, mirror `api_coord.py`).
- Modify: `soveryn/app/templates/command_center.html` — add a "Cognition" panel (mirror the Boards panel + `wireBoardCreate` JS pattern).
- Tests: `tests/test_app_api_cognition_routes.py`.

### Interfaces (mirror api_coord.py shapes)
- `GET /api/cognition/note` — current note + version id.
- `GET /api/cognition/changes?limit=N` — change feed (integrated/surfaced/decayed) each with citations + scope call.
- `GET /api/cognition/diff?cycle=...` — per-cycle add/drop.
- `POST /api/cognition/revert` `{line_id}` — revert a line (localhost-only).
- `POST /api/cognition/purge` `{since}` — window purge (localhost-only).
- `GET /api/cognition/drift-audit` — the pushed "how I've shifted over N cycles" summary.

### Tasks (TDD — mirror `tests/test_app_api_coord_routes.py` fixture)
- [ ] **T4.1** GET note/changes/diff endpoints return cognition-region data. Tests: seeded region → correct shapes.
- [ ] **T4.2** POST revert removes a line (localhost-guarded). Tests: line gone; non-localhost → 403.
- [ ] **T4.3** POST purge drops integrations since T, leaves earlier intact. Tests: window removed, prior state intact.
- [ ] **T4.4** Drift-audit summary endpoint. Test: returns shift summary over N cycles.
- [ ] **T4.5** Mission Control "Cognition" panel renders note + change feed + controls (mirror Boards panel). Verify live (page contains the panel markup), like the board-create verification.

---

## Bake-in rollout (operational, not a code task)
At launch, run in **propose mode** (manner changes surfaced, applied on Jon's nod). Graduate to autonomous self-apply after **N consecutive deep cycles with zero self-applies Jon would have vetoed** — N agreed at launch. The Mission Control view stays on permanently; only the approval requirement is temporary.

## Self-review notes
- Spec coverage: Infra (Ph1), pipeline/cadence/note/injection (Ph2), three guards + negative tests (Ph3), view/API/purge/audit + bake-in (Ph4). Agent-parameterization is in the `reflect(agent, ...)` / `NoteStore(agent)` signatures so Vett reuses it.
- Phase 1 is execution-ready; Phases 2–4 carry file structure, interfaces, task list, and the load-bearing tests, with per-step code finalized against live signatures at build time (deliberate — hardware-gated, codebase will evolve). Flag any phase to fully detail now.
