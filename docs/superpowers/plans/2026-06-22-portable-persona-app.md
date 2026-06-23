# Portable Persona App — Implementation Plan (Slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship a desktop companion where the user owns a portable `.soul` bundle (persona + Lattice memory) and can flip its brain between a local model and a cloud model (BYO-key), with memory never leaving the disk.

**Architecture:** A new repo. A Python **engine-core package** (lifted from vnext/spike/feat: Lattice, swappable-inference seam, persona/prompt-assembly, cognition gate+store) runs inside a **home-node service** (local API + remote seam) that owns the `.soul` bundle on disk. A lean **desktop shell** (frontend) talks to that local API.

**Tech Stack:** Python 3.11 engine + home-node service (FastAPI/Flask local API). Desktop shell: **Tauri recommended** (lighter, native feel, smaller footprint; Python engine runs as a local sidecar service) — Electron is the safe fallback if Tauri+sidecar packaging proves painful. SQLite (Lattice). OS keychain for the BYO-key.

**Source spec:** `docs/superpowers/specs/2026-06-22-portable-persona-app-design.md` (read first).

## Cross-program sequencing (honest dependencies)

This app rides the engine core. Realistic order across the whole program:
1. Finish enough of the **continuous-cognition** build (pipeline + light growth loop) — currently paused at the safety core on `feat/continuous-cognition`.
2. **Productionize the swappable seam** (spike/swappable-brain → real streaming, error shapes, 429-retry per the spike's flagged gaps).
3. **Extract** those + Lattice + persona/prompt-assembly into the engine-core package (Phase 1 below).
4. Build the app on top (Phases 2–5).
Phases 0–1 can begin in parallel with finishing the engine (the extraction surface is known); Phases 2–5 need the extracted core.

## Global Constraints (copied from the spec — bind every task)

- **Memory never leaves:** no code path transmits the Lattice/persona corpus. Cloud brain receives ONLY the assembled transient slice (persona seed + current sense-of-us note + retrieved snippets for THIS message + the message). Assert it in tests.
- **Credential isolation:** the BYO-key lives in the OS keychain, NEVER in the `.soul` bundle or any file inside it. Export/round-trip tests must assert no key material is in the bundle.
- **Seed anchored, manner-only evolution:** `seed.md` is never auto-rewritten; only `sense_of_us.md` evolves. Enforced by the cognition store's write-isolation (region="cognition").
- **`.soul` is self-describing + versioned:** `manifest.json` carries a format version from v1; loader must handle version mismatch explicitly.
- **Engine-agnostic bundle:** the bundle contains no model/engine — only `manifest.json`, `persona/` (seed.md, sense_of_us.md, history), `memory/lattice.db`, `config.json` (no secrets).
- **Human-readable sovereignty:** seed + sense-of-us are markdown; Lattice is plain SQLite.
- **None of the shipped archetype seeds is Aetheria.** Generic, user-owned seeds only.
- **Test env:** engine-core tests run under the project's Python (3.11); `pytest`.

---

## Phase 0 — Repo + decisions + scaffold

**Outcome:** new repo, stack decisions locked, empty engine-core package + home-node + shell skeletons that build and run a hello-world round-trip (shell → local API → "ok").

### Tasks
- [ ] **T0.1 Repo + layout decision.** New git repo (e.g. `portable-persona`). Lock the package layout: `engine_core/` (Python pkg), `home_node/` (service), `shell/` (Tauri app). Document the Tauri-vs-Electron decision (recommend Tauri; record the fallback trigger). Commit a README stating the architecture + global constraints.
- [ ] **T0.2 Home-node skeleton.** Minimal local API service (FastAPI) with `GET /health` → 200, bound to `127.0.0.1` only. Test: health returns ok; non-localhost refused.
- [ ] **T0.3 Shell skeleton.** Tauri app that calls `GET /health` on the sidecar and renders "connected". (Frontend smoke test; manual verify acceptable, documented.)

---

## Phase 1 — Engine-core extraction (the shared library)

**Outcome:** a clean `engine_core` Python package with the proven internals + their tests, importable with no vnext app dependencies.

### File structure
- `engine_core/lattice/` — lifted Lattice (per-user SQLite store).
- `engine_core/inference/` — the productionized swappable seam (ModelServer with base_url/api_key_env/chat_url, chat/chat_stream, auth headers).
- `engine_core/persona/` — prompt-assembly (seed + sense-of-us note + retrieved slice → messages[]).
- `engine_core/cognition/` — the gate + CognitionStore (write-isolation) + the light growth loop.

### Tasks (each: lift module → strip vnext coupling → port its tests → green → commit)
- [ ] **T1.1 Lattice** — lift; remove vnext-specific schema not needed for the companion; port tests; confirm per-user-path construction.
- [ ] **T1.2 Swappable inference** — lift the spike seam; add the productionization the spike flagged (real-provider SSE streaming, structured error shape, 429 retry); port + extend tests.
- [ ] **T1.3 Persona/prompt-assembly** — lift; the assembler takes (seed, sense_of_us_note, retrieved_snippets, message) → messages[], ambient-not-instruction, cache-stable note placement; test the transient-slice shape + that it carries no more than the intended pieces.
- [ ] **T1.4 Cognition (gate + store + light loop)** — lift the gate + CognitionStore (write-isolation intact); add a *light* growth loop (reflect recent turns → gate → update sense_of_us note); tests incl. the write-isolation negative test.

---

## Phase 2 — The `.soul` bundle (the moat artifact)

**Outcome:** load/save/export/import of the portable bundle, with the integrity + credential guarantees enforced and tested.

### File structure
- `engine_core/soul/manifest.py` — manifest schema v1 + version-mismatch handling.
- `engine_core/soul/bundle.py` — open/create/save a `.soul` dir; wire persona files + lattice path + config.
- `engine_core/soul/portability.py` — export (zip) / import (unzip + validate), key-isolation enforcement.

### Tasks
- [ ] **T2.1 Manifest v1** — schema (format version, persona id, name, seed ref, timestamps); loader raises a clear error on unknown future version. Tests: round-trip; version-mismatch path.
- [ ] **T2.2 Bundle open/create/save** — create a new `.soul` dir from a seed; open an existing one; expose persona files + lattice. Tests: create→open round-trip; structure matches spec.
- [ ] **T2.3 Export/import + credential isolation** — export to a single file; import + validate. Tests (load-bearing): export→fresh-dir→import→content identical; **no key material anywhere in the bundle**; importing a bundle with a missing/extra file fails cleanly.

---

## Phase 3 — Home-node: engine wiring + brain-flip + degradation (structured outline; per-step code at build)

### File structure
- `home_node/api.py` — local API: converse, get/set persona, get/set brain selection, export/import, status. Remote-access seam (auth-gated) for the future phone client.
- `home_node/session.py` — the turn loop wiring (retrieve → assemble slice → selected brain → write back → trigger light cognition).
- `home_node/brain.py` — brain selection (local llama-server vs cloud endpoint+keychain key) + degradation/fallback.

### Tasks (interfaces + test intent; finalize code at build)
- [ ] **T3.1 Turn loop** — `POST /converse` runs retrieve→assemble→brain→writeback. Tests: memory written back; cloud path sends ONLY the slice (assert payload contents); nothing-leaves on local path.
- [ ] **T3.2 Brain-flip** — get/set brain selection (config.json); same slice format both brains. Tests: flip changes endpoint, identical assembled slice.
- [ ] **T3.3 Degradation** — cloud down/no key → local fallback or clean error; never blocks; memory intact. Tests: each degradation path.
- [ ] **T3.4 Remote seam** — the API is reachable by an authenticated remote client (the phone-slice hook), localhost-trusted + token for remote. Test: remote call requires token.

## Phase 4 — Consumer shell: onboarding + converse UX (structured outline)

### File structure
- `shell/` — Tauri frontend: onboarding flow, chat view, persona view/edit, brain toggle + indicator, settings (BYO-key → keychain).

### Tasks (test intent; frontend per-step code at build, once stack fixed)
- [ ] **T4.1 Onboarding** — archetype picker (3–4 seeds) → name your companion → BYO-key (stored to keychain, never to bundle). Creates the `.soul`. 
- [ ] **T4.2 Converse view** — chat UI hitting `/converse`; per-turn 🔒/⚡ indicator.
- [ ] **T4.3 Persona view** — show/edit seed.md + sense_of_us.md (human-readable sovereignty).
- [ ] **T4.4 Brain toggle + settings** — flip local/cloud; manage key (keychain).

## Phase 5 — Light cognition growth + export/import UX (structured outline)

- [ ] **T5.1 Background growth** — idle-triggered light cognition loop grows sense_of_us (manner-only, gated, write-isolated); surfaces nothing intrusive.
- [ ] **T5.2 Export/import UX** — "back up / move your companion" in the shell over the Phase-2 portability; round-trip verified end to end (export → new install → import → continue).

---

## Self-review notes
- Spec coverage: shell-over-core (P0/P4), engine extraction (P1), `.soul` moat + portability + credential isolation (P2), transient-slice data flow + brain-flip + degradation (P3), archetype onboarding (P4.1), light cognition + integrity rails (P1.4/P5), remote seam for phone slice (P3.4). Deferred slices (full phone client, sync, monetization, cross-vendor format) correctly out.
- Phases 0–2 are detailed enough to start; Phases 3–5 carry file structure + interfaces + the load-bearing test intent, with per-step code authored at build time once the stack is fixed (deliberate — greenfield, frontend stack just being locked).
- Hard dependency: Phases 1–5 need the engine core, which needs the cognition build finished + the seam productionized (see Cross-program sequencing). This plan does not execute before that foundation is ready.
