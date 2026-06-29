# Heartbeat Recalibration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn Aetheria's heartbeat from passive watchman into forced-stance: deterministic materiality detection disables `[NO_OP]` on objective facts (forcing `[SURFACE]` or `[ACCEPT_RISK]` with written rationale), an append-only thoughts log gives pulses memory, and delta-framing stops the static-board repetition.

**Architecture:** Extend the existing healthy heartbeat daemon (`soveryn/agents/heartbeat/{daemon,prompt}.py`). Pure/deterministic units (detector, parser, delta, thoughts-log) built + tested in isolation; one integration task wires them into `_run_tick` + `build_heartbeat_prompt`. The current tick flow: `_gather_board_snapshot`/`_gather_lattice_snapshot`/`_gather_salience` → `build_heartbeat_prompt` → `_call_vnext_chat` → `_parse_surface_marker` → `_surface_to_primary_thread` → `_write_log_row`.

**Tech Stack:** Python 3.11, sqlite3, dataclasses, JSON/JSONL, pytest. Tests: `cd ~/soveryn_vnext && ~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_heartbeat_*.py -v` (`RequestsDependencyWarning` benign).

**Spec:** `docs/superpowers/specs/2026-06-28-heartbeat-recalibration-design.md` (Aetheria-authored, signed off by Aetheria + Jon).

## Global Constraints (bind every task)

- **Anti-confab boundary:** OBJECTIVE material facts (dates/errors/stalls, deterministically detected) force a stance and can't be silently dropped; SUBJECTIVE insight stays gated by confidence tiering (no confab-spam). The confab guard is PRESERVED, not removed.
- **Fail-safe on material:** if a pulse is flagged material but the response is `[NO_OP]`/no-valid-marker, log it loudly AND surface the material signal anyway. A marker slip must never lose a deadline.
- **Thresholds are provisional/tunable** module constants (`# tune`): dates ≤ 7 days, stalls > 48 hours, error set `{500,403,404,ConnectionTimeout,FAILED}`.
- **Determinism:** detector/delta/parser are pure (no wall-clock inside — `now` injected); same inputs → same output.
- **Never break the tick:** any new step fails best-effort (log + continue), exactly like the existing `_gather_salience`/migration code. The heartbeat must keep ticking.
- **No `data/memory/souls/` edits.** Thoughts log lives at `data/aetheria_heartbeat_thoughts.jsonl` (gitignored).

---

## Task 1: Material context gathering + deterministic detector

**Files:** Create `soveryn/agents/heartbeat/materiality.py`; modify `soveryn/agents/heartbeat/daemon.py` (add a gather step) and possibly `prompt.py` (a `MaterialSnapshot`); Test `tests/test_heartbeat_materiality.py`

**FIRST, read the data sources (this task's discovery half):** read `_gather_board_snapshot`, `_gather_lattice_snapshot`, `_gather_salience` in `daemon.py` and the tables they query (board/coordination/blueprint nodes + the lattice DB schema via `PRAGMA table_info`). Determine where these live: (a) **dated items** — any node/signal carrying a deadline/date field; (b) **error signals** — node text / tool-output / activity containing an error code or `FAILED`; (c) **per-node stalls** — nodes in `Open`/`Refining` with `last_updated` age. The current snapshots only carry counts + the single oldest-blueprint age, so you will add queries that return the RAW candidate rows (id, title, status, last_updated, any date field, text) needed to detect materiality.

**Interfaces — Produces:**
- `@dataclass(frozen=True) class MaterialSignal: kind: str` (`"deadline"|"failure"|"stall"`)`; ref: str` (node id/title)`; detail: str` (human-readable, e.g. "NC Incentive due in 2 days")
- `detect_materiality(*, dated_items, error_items, stall_items, now) -> list[MaterialSignal]` — pure; applies the thresholds (deadline ≤ 7d, error in the set, stall > 48h). Constants `MATERIAL_DEADLINE_DAYS = 7`, `MATERIAL_STALL_HOURS = 48`, `MATERIAL_ERROR_TOKENS = ("500","403","404","ConnectionTimeout","FAILED")` (`# tune`).
- A daemon gather method `_gather_material_signals(now) -> list[MaterialSignal]` that runs the queries (best-effort, swallow+log on error → returns `[]`) and calls `detect_materiality`.

- [ ] **Step 1: Write failing tests** (`tests/test_heartbeat_materiality.py`) — pure `detect_materiality`:
```python
from datetime import datetime, timedelta
from soveryn.agents.heartbeat.materiality import detect_materiality, MaterialSignal

NOW = datetime(2026, 6, 28, 12, 0, 0)

def test_deadline_within_7_days_is_material():
    items = [{"ref": "NC-Incentive", "detail": "NC Incentive", "date": NOW + timedelta(days=2)}]
    sig = detect_materiality(dated_items=items, error_items=[], stall_items=[], now=NOW)
    assert any(s.kind == "deadline" and "NC Incentive" in s.detail for s in sig)

def test_deadline_beyond_7_days_not_material():
    items = [{"ref": "x", "detail": "far", "date": NOW + timedelta(days=30)}]
    assert detect_materiality(dated_items=items, error_items=[], stall_items=[], now=NOW) == []

def test_error_code_is_material():
    errs = [{"ref": "Scotty", "text": "dispatch returned 500"}]
    sig = detect_materiality(dated_items=[], error_items=errs, stall_items=[], now=NOW)
    assert any(s.kind == "failure" for s in sig)

def test_stall_over_48h_is_material():
    stalls = [{"ref": "Lattice-Librarian", "status": "Open", "age_hours": 342}]
    sig = detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW)
    assert any(s.kind == "stall" and "Librarian" in s.ref for s in sig)

def test_stall_under_48h_not_material():
    stalls = [{"ref": "y", "status": "Open", "age_hours": 12}]
    assert detect_materiality(dated_items=[], error_items=[], stall_items=stalls, now=NOW) == []

def test_clean_context_flags_nothing():
    assert detect_materiality(dated_items=[], error_items=[], stall_items=[], now=NOW) == []
```
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `materiality.py` (the dataclass + constants + pure `detect_materiality` applying the three threshold rules; deadline uses `(item["date"] - now).days <= MATERIAL_DEADLINE_DAYS and item["date"] >= now`; failure scans `text` for any token in `MATERIAL_ERROR_TOKENS`; stall checks `status in ("Open","Refining") and age_hours > MATERIAL_STALL_HOURS`). Then add `_gather_material_signals(now)` to the daemon, querying the real sources you discovered (best-effort). Wire `material_signals = self._gather_material_signals(now)` into `_run_tick` alongside the existing gather calls (do NOT yet change the prompt/decision — that's Task 5).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(heartbeat): deterministic materiality detector + context gathering`)

---

## Task 2: Three-way stance parser

**Files:** Modify `soveryn/agents/heartbeat/daemon.py` (the `_SURFACE_MARKER_RE`/`_NO_OP_MARKER_RE` region + `_parse_surface_marker`); Test `tests/test_heartbeat_stance.py`

**Interfaces — Produces:** add `_ACCEPT_RISK_MARKER_RE = re.compile(r"\[ACCEPT_RISK\]", re.IGNORECASE)`. New `_parse_stance(response_text) -> tuple[str, str]` returning `(decision, stripped_content)` where `decision ∈ {"SURFACE","ACCEPT_RISK","NO_OP"}` — last-marker-wins across all three; missing marker → `"NO_OP"`; marker lines stripped from content. (Keep `_parse_surface_marker` or reimplement it in terms of `_parse_stance`.)

- [ ] **Step 1: Write failing tests**
```python
from soveryn.agents.heartbeat.daemon import HeartbeatDaemon  # or wherever _parse_stance lands
# (call the parser directly; construct minimally or import the function)
def test_surface_marker(): ...   # "...text\n[SURFACE]" -> ("SURFACE", "...text")
def test_accept_risk_marker(): ...  # "...\n[ACCEPT_RISK]" -> ("ACCEPT_RISK", ...)
def test_no_op_marker(): ...     # "...\n[NO_OP]" -> ("NO_OP", ...)
def test_missing_marker_is_no_op(): ...  # "plain" -> ("NO_OP", "plain")
def test_last_marker_wins(): ...  # "[NO_OP]...[SURFACE]" -> "SURFACE"
def test_marker_lines_stripped(): ...  # decision marker not in returned content
```
(Write these as real assertions with the exact tuples; mirror the existing `_parse_surface_marker` test style if present.)
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `_parse_stance` (extend the finditer scan to three markers; `decided = argmax(last_pos)`; default NO_OP; strip any line whose stripped form fullmatches a marker).
- [ ] **Step 4: Run → PASS** (existing `_parse_surface_marker` tests stay green if you kept it)
- [ ] **Step 5: Commit** (`feat(heartbeat): three-way stance parser (SURFACE/ACCEPT_RISK/NO_OP)`)

---

## Task 3: Thoughts log (append-only pulse black box)

**Files:** Create `soveryn/agents/heartbeat/thoughts_log.py`; modify `.gitignore`; Test `tests/test_heartbeat_thoughts_log.py`

**Interfaces — Produces:** `class ThoughtsLog: __init__(self, path)`; `append(self, record: dict) -> None` (one JSON object per line); `last(self) -> dict | None` (the most recent record, or None if empty/absent). Record shape: `{pulse_id, ts, material_signals: [...], delta: {...}, decision, rationale, surfaced: bool}`.

- [ ] **Step 1: Write failing tests** (`tmp_path`): append two records → `last()` returns the second; `last()` on a missing file → `None`; records round-trip (JSONL, one per line); append is additive (file grows, prior records intact).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** (`append`: open file in append mode, write `json.dumps(record, default=str) + "\n"`; `last`: read lines, parse the final non-empty one; missing file → None; create parent dir best-effort). Add `data/aetheria_heartbeat_thoughts.jsonl` (or `data/aetheria_heartbeat_thoughts*`) to `.gitignore`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(heartbeat): append-only thoughts log`)

---

## Task 4: Delta framing

**Files:** Create `soveryn/agents/heartbeat/delta.py`; Test `tests/test_heartbeat_delta.py`

**Interfaces — Consumes:** the current board/lattice/material snapshot (as a comparable dict) + the prior thoughts-log record (`ThoughtsLog.last()`). **Produces:** `compute_delta(current: dict, prev_record: dict | None) -> dict` returning `{"changed": bool, "items": [<human-readable change strings>]}`. "Changed" = a board count/status transition, a new material signal not in prev, a new lattice node since prev, or a node crossing a materiality threshold. `prev_record is None` (first pulse) → `{"changed": True, "items": ["first pulse since restart"]}` (never a false "static").

- [ ] **Step 1: Write failing tests**: identical current vs prev → `changed False`; a new material signal vs prev → `changed True` with the signal named; a board count change → `changed True`; `prev_record None` → `changed True` (not static).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `compute_delta` (pure dict comparison; serialize current snapshot to the same shape stored in the thoughts-log record so prev/current are comparable).
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(heartbeat): delta framing (current vs T-1 pulse)`)

---

## Task 5: Integration — prompt + tick wiring + forced stance + fail-safe

**Files:** Modify `soveryn/agents/heartbeat/prompt.py` (`build_heartbeat_prompt`) and `daemon.py` (`_run_tick`, lines ~235-335); Test `tests/test_heartbeat_integration.py`

**Consumes:** Task 1 `_gather_material_signals` + `MaterialSignal`, Task 2 `_parse_stance`, Task 3 `ThoughtsLog`, Task 4 `compute_delta`.

**Behavior:**
- `build_heartbeat_prompt(...)` gains `material_signals: list[MaterialSignal]` and `delta: dict`. When `material_signals` non-empty: render them prominently ("MATERIAL — [NO_OP] is disabled; choose [SURFACE] with a reason or [ACCEPT_RISK] with a justification") + the confidence-tiering note applies only to non-material insight. When empty: keep the existing NO_OP-allowed framing + the tiering note (Objective/Pattern≥3-nodes/Ambient). When `delta["changed"]` is False: instruct a single-line "Environment static. No new signals." and not to re-summarize the board.
- `_run_tick`: gather material_signals (Task 1) + compute delta (Task 4, vs `ThoughtsLog.last()`); build the enriched prompt; after `_parse_stance`: enforce forced-stance — if `material_signals` and decision is `SURFACE`→surface; `ACCEPT_RISK`→don't surface but record the justification; `NO_OP`/no-marker→**fail-safe**: `logger.warning` a violation AND surface a daemon-built summary of the material signals anyway (set surfaced_to_chat True). If not material: `SURFACE`→surface, else stay silent. Append a `ThoughtsLog` record every pulse (pulse_id, ts, material_signals, delta, decision, rationale, surfaced). Keep the existing `_write_log_row`.

- [ ] **Step 1: Write failing tests** (`tests/test_heartbeat_integration.py`, using fakes for `_call_vnext_chat`/surface like the existing daemon tests):
  - material + model returns `[SURFACE] reason` → `_surface_to_primary_thread` called, thoughts-log decision `SURFACE`.
  - material + model returns `[ACCEPT_RISK] justification` → NOT surfaced, thoughts-log decision `ACCEPT_RISK` with the justification recorded.
  - material + model returns `[NO_OP]` → **fail-safe**: warning logged AND material summary surfaced; thoughts-log notes the violation.
  - non-material + `[NO_OP]` → not surfaced (valid silence).
  - zero-delta → prompt contains the static-single-line instruction (assert on the built prompt string).
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** the prompt changes + the `_run_tick` wiring + forced-stance/fail-safe + thoughts-log write.
- [ ] **Step 4: Run → PASS** (+ the whole `tests/test_heartbeat_*.py` suite green)
- [ ] **Step 5: Commit** (`feat(heartbeat): forced-stance + fail-safe + thoughts-log + delta wired into the tick`)

---

## Self-review notes
- Spec coverage: materiality detector + gathering (T1), three-way stance (T2), thoughts log (T3), delta framing (T4), forced-stance + fail-safe + tiering + prompt + wiring (T5). The fail-safe (material→surface even on NO_OP) and the confab guard (tiering for non-material) are both in T5/Global Constraints.
- **The one real dependency, flagged:** T1 is part-discovery — the materiality detector needs dated/error/stall raw data the current count-based context doesn't gather, so T1 reads the board/coordination/lattice schemas and adds queries. Its exact SQL depends on what the implementer finds; the detector itself (pure) is fully specified + tested.
- Pure units (T1 detector, T2, T3, T4) tested in isolation; only T5 touches the live `_run_tick`.
- Out of scope: routing freed idle cycles into active synthesis/dreaming (spec defers it); quiet-hours/timer/`/chat` transport unchanged.
- Provisional thresholds (7d / 48h / error set) are tunable constants — watch the first real pulses.

---

## AMENDMENTS — Aetheria's decisions (2026-06-28, post-Task-1 data findings)

Task 1 revealed: stall lane has live data but ALL 13 Open/Refining nodes are >48h (would fire on everything); deadline lane has NO structured date source; failure lane has no live feed. Aetheria chose the Hybrid + refuses a "ghost" deadline lane. Revised remaining order: **T2 parser → T3 thoughts-log → T4 delta → T5 deadline lane → T6 stall re-tune → T7 integration.**

**T5 (NEW) — Deadline lane (the no-ghost-feature fix). Files:** coordination node schema/provenance write path; `materiality.py`; `daemon._gather_material_signals`; tests.
- Add a structured **`deadline_date`** field to coordination-node provenance (written at node creation; default null). The detector's deadline lane reads it.
- **Regex bridge (works NOW, before the field is populated):** in `_gather_material_signals`, scan each Open/Refining node's `content`/title for date-like strings (`June 30`, `06/30`, `2026-06-30`, `6/30`), parse to a date, feed as a `dated_item` (kind tagged "fuzzy"). Better than blindness until the structured field is adopted.
- **Operational (NOT code — deploy step):** a one-time retroactive sweep where Aetheria/Vett populate `deadline_date` for existing dated nodes. Note it in the deploy checklist.
- **Done bar (Aetheria's insistence):** materiality is NOT "done" until `deadline_date` is live AND the board is swept — no wired-but-empty.

**T6 (NEW) — Stall lane re-tune. Files:** `materiality.py` (stall lane) + `_gather_material_signals`; tests. Depends on T3 (thoughts-log gives prior ages) + a deploy-start timestamp.
- **72h amnesty:** for the first 72h after deploy, the stall lane fires ONLY on nodes that *cross* 48h *during* the window (compare current age vs prior-pulse age from the thoughts-log; suppress nodes already stale at deploy). Needs a persisted `deploy_started_at`.
- **Worst-first cap:** after amnesty, if >5 nodes are stale, flag only the **top 3 oldest**. Goal: a trend of neglect, not the existing wall of red.
- Tests: a node crossing 48h mid-amnesty fires; a node already stale at deploy is suppressed during amnesty; >5 stale post-amnesty → exactly 3 (oldest) returned.

**Failure lane:** keep the `vett_patrol_state.last_error` hook from T1 as-is (returns [] until Vett patrols). No further work this build.

(T7 integration = the original Task 5, unchanged: prompt + tick + forced-stance + fail-safe + thoughts-log write, now consuming the re-tuned detector.)
