# Aetheria Delegated Execution with Review Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aetheria dispatches a scoped task → Scotty executes it in an isolated git worktree → tests verify → the diff surfaces as a proposal in a Mission Control approval tile → Jon approves → it merges to the live tree. Never the live tree until reviewed.

**Architecture:** A delegation subsystem (`soveryn/platform/delegation/`) with a SQLite task store, an Aetheria-owned `dispatch_task` tool, a background worker that runs a worktree-isolated Scotty execution engine (porting the stubbed `ScottyRepairSurface`), Flask approve/reject/land routes, a Mission Control approval tile (carved from the cognition tile), and a `task_status` reader so her language tracks real state.

**Tech Stack:** Python 3.11 (`~/miniconda3/envs/soveryn/bin/python`), SQLite (stdlib, connection-per-call pattern from `documents/store.py`), Flask (existing app factory `create_app`), the `ToolSpec`/`ToolRegistry` pattern (`soveryn/platform/tools/registry.py`), git worktrees via `subprocess`, pytest.

## Global Constraints
- **Scotty edits ONLY inside a throwaway worktree. Never the live tree.** Enforce via cwd + a scope guard; abort/flag any edit outside the task's worktree.
- **Nothing merges to `main` without an explicit human approve action.** No auto-land in this plan.
- Execution is **bounded** (max tool rounds, wall-clock timeout) and **reversible** (worktree is disposable; `git worktree prune` on cleanup).
- All units path/seam-injected and **offline-testable** (fake git, fake Scotty loop, fake test-runner). Rig/live tests behind markers.
- Task status is the **single source of truth**; a task is never reported `landed` until it actually merged. Legal transitions only.
- Follow existing patterns exactly: store mirrors `documents/store.py`; tools mirror `documents/tools.py`; tile mirrors the `.pulse-row` heartbeat/ares twin split; worker mirrors the messenger delivery worker (`startup.py:726`).

---

### Task 1: Delegation task store

**Files:**
- Create: `soveryn/platform/delegation/__init__.py`
- Create: `soveryn/platform/delegation/store.py`
- Test: `tests/test_delegation_store.py`

**Interfaces — Produces:**
- `@dataclass(frozen=True) Task`: `id, dispatched_by, objective, scope, acceptance, status, worktree_path|None, branch|None, diff|None, test_output|None, summary|None, review_feedback|None, created_at, updated_at`
- `class DelegationStore(db_path)`:
  - `create_task(*, dispatched_by, objective, scope, acceptance) -> str` (uuid; status `"dispatched"`)
  - `get_task(task_id) -> Task | None`
  - `list_tasks(*, status: str | None = None) -> tuple[Task, ...]` (newest-first)
  - `set_status(task_id, status) -> bool` (raises `IllegalTransition` on an illegal move)
  - `set_execution(task_id, *, worktree_path, branch) -> bool`
  - `set_result(task_id, *, diff, test_output, summary) -> bool`
  - `set_review(task_id, *, review_feedback) -> bool`
- Legal transitions: `dispatched→executing→{in_review→{landed,rejected}, failed}`; `dispatched→failed`.

- [ ] **Step 1: Failing tests** — `tests/test_delegation_store.py`:
```python
import pytest
from soveryn.platform.delegation.store import DelegationStore, IllegalTransition

def _s(tmp_path): return DelegationStore(tmp_path / "deleg.db")

def test_create_defaults_to_dispatched(tmp_path):
    s = _s(tmp_path)
    tid = s.create_task(dispatched_by="aetheria", objective="add docstring",
                        scope="soveryn/x.py", acceptance="pytest tests/test_x.py")
    t = s.get_task(tid)
    assert t.status == "dispatched" and t.dispatched_by == "aetheria"
    assert t.objective == "add docstring" and t.acceptance == "pytest tests/test_x.py"

def test_status_transitions_legal_and_illegal(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    assert s.set_status(tid, "executing") is True
    assert s.set_status(tid, "in_review") is True
    assert s.set_status(tid, "landed") is True
    with pytest.raises(IllegalTransition):
        s.set_status(tid, "executing")  # can't go backwards from landed

def test_dispatched_can_fail(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    assert s.set_status(tid, "failed") is True

def test_set_execution_and_result_and_review(tmp_path):
    s = _s(tmp_path); tid = s.create_task(dispatched_by="aetheria", objective="o", scope="s", acceptance="a")
    s.set_status(tid, "executing")
    s.set_execution(tid, worktree_path="/tmp/wt", branch="task/abc")
    s.set_result(tid, diff="--- a\n+++ b", test_output="1 passed", summary="did the thing")
    s.set_status(tid, "in_review")
    s.set_status(tid, "rejected"); s.set_review(tid, review_feedback="wrong file")
    t = s.get_task(tid)
    assert t.branch == "task/abc" and t.diff.startswith("---") and t.review_feedback == "wrong file"

def test_list_by_status(tmp_path):
    s = _s(tmp_path)
    a = s.create_task(dispatched_by="aetheria", objective="a", scope="s", acceptance="x")
    b = s.create_task(dispatched_by="aetheria", objective="b", scope="s", acceptance="x")
    s.set_status(b, "executing"); s.set_status(b, "in_review")
    ids = [t.id for t in s.list_tasks(status="in_review")]
    assert ids == [b] and a not in ids
```
- [ ] **Step 2:** Run → FAIL (module missing). `pytest tests/test_delegation_store.py -q`
- [ ] **Step 3:** Implement `store.py` mirroring `documents/store.py` (connection-per-call, `_init_schema`, `_row_to_task`). Encode `_LEGAL` transition map; `set_status` raises `IllegalTransition` if `(current,new)` not allowed.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(delegation): task store with guarded status transitions`.

---

### Task 2: `dispatch_task` tool (Aetheria-owned)

**Files:**
- Create: `soveryn/platform/delegation/tools.py`
- Test: `tests/test_dispatch_task_tool.py`

**Interfaces — Consumes:** `DelegationStore` (Task 1). **Produces:** `build_dispatch_task_tool(*, store, owner_agent="aetheria") -> ToolSpec` (name `dispatch_task`); `register_delegation_tools(registry, *, store, owner_agent)`.

- [ ] **Step 1: Failing tests** — schema requires `objective, scope, acceptance`; handler creates a Task and returns `{"task_id":..., "status":"dispatched"}`; empty acceptance → `ToolArgError`; acceptance must look like a test/check command (starts with `pytest`/`python -m`/`./` — validated). Assert `tool.name=="dispatch_task"`, `tool.owner=="aetheria"`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement mirroring `documents/tools.py` `build_*` shape. Description makes the honest contract explicit: *"Dispatch a scoped implementation task to Scotty. It runs in an isolated worktree, is tested, and comes back as a proposal for Jon to review — nothing goes live until approved. Returns a task_id; check task_status for progress. This ACTUALLY runs; do not say a task is done until its status is 'landed'."*
- [ ] **Step 4:** Run → PASS. **Step 5:** Commit.

---

### Task 3: Worktree manager

**Files:**
- Create: `soveryn/platform/delegation/worktree.py`
- Test: `tests/test_delegation_worktree.py` (marked `@pytest.mark.rig`? NO — use a real temp git repo created in the test; it's hermetic, no fleet needed)

**Interfaces — Produces:**
- `create_worktree(repo_root, task_id) -> (worktree_path, branch)` — `git worktree add <path> -b task/<id> main` under a `.worktrees/` dir.
- `worktree_diff(worktree_path) -> str` — `git -C <wt> add -A && git -C <wt> diff --cached` (staged diff of the change).
- `merge_worktree(repo_root, branch) -> (ok: bool, message)` — merge `task/<id>` into main (no-ff); returns False+message on conflict.
- `remove_worktree(repo_root, worktree_path, branch, *, delete_branch=True)` — `git worktree remove --force` + optional branch delete + `git worktree prune`.

- [ ] **Step 1: Failing tests** — build a temp git repo (init, commit a file), create worktree → path exists + branch `task/<id>` + is a real worktree; edit a file in the worktree → `worktree_diff` shows it; `merge_worktree` lands it on main; `remove_worktree` cleans up (no orphan in `git worktree list`). Conflict case → merge returns `(False, ...)`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement via `subprocess.run(["git", ...])` with `check=True` and captured output; each fn hermetic. **Step 4:** PASS. **Step 5:** Commit.

---

### Task 4: Scotty worktree-isolated execution engine (ports `ScottyRepairSurface`)

**Files:**
- Create: `soveryn/platform/delegation/engine.py`
- Modify: `soveryn/agents/scotty/repair_surface.py` (route the real port through the engine, or leave the stub and add engine as the live path — engine is authoritative)
- Test: `tests/test_delegation_engine.py`

**Interfaces — Consumes:** `DelegationStore`, worktree fns (injected), a `scotty_run(worktree_path, objective, scope) -> summary:str` callable (Scotty's bounded AgentLoop, injected/faked in tests), a `run_acceptance(worktree_path, acceptance) -> (passed:bool, output:str)` callable (injected). **Produces:** `execute_task(task_id, *, store, repo_root, scotty_run, run_acceptance, make_worktree=create_worktree, diff_fn=worktree_diff, max_seconds=600) -> None` (drives status).

Flow: `set_status(executing)` → `make_worktree` → `set_execution(worktree,branch)` → `scotty_run(...)` (bounded; edits confined to the worktree by cwd) → `run_acceptance(...)`; if passed: `diff = diff_fn(...)`, `set_result(diff, output, summary)`, `set_status(in_review)`; if failed: `set_result(diff, output, summary="tests failed")`, `set_status(failed)`. Any exception → `set_status(failed)` + best-effort worktree cleanup.

- [ ] **Step 1: Failing tests** (inject fakes): green acceptance → task ends `in_review` with diff+summary+output; red acceptance → `failed`, still records the (rejected) diff+output, no `in_review`; `scotty_run` raising → `failed`; worktree is created via the injected maker and its path stored. Assert the status sequence via a recording store.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

*(Scotty's real `scotty_run` — wrapping his AgentLoop with `cwd=worktree`, his 7 tools, and round/time caps — is wired in Task 8; the engine is agnostic to it via the seam.)*

---

### Task 5: Delegation API routes (pending / approve / reject / land)

**Files:**
- Create: `soveryn/app/routes/delegation.py` (Flask blueprint)
- Modify: `soveryn/app/startup.py` (register blueprint)
- Test: `tests/test_delegation_routes.py`

**Interfaces:** `GET /api/delegation/pending` → `[{id, objective, summary, diff, test_output, status}]` for `in_review` tasks. `POST /api/delegation/<id>/approve` → merge branch (via injected `merge_fn`), on ok `set_status(landed)` + remove worktree, return `{ok, status, restart_hint:"restart soveryn-vnext to apply"}`; on conflict → 409 `{ok:false, message}`. `POST /api/delegation/<id>/reject` (body `{feedback}`) → `set_review` + `set_status(rejected)` + remove worktree, return `{ok, status}`.

- [ ] **Step 1: Failing tests** (Flask client + fake store + fake merge/remove): pending returns only `in_review` shaped rows; approve on a green task → merge called, status `landed`, restart_hint present; approve with conflicting merge → 409 + status stays `in_review`; reject → status `rejected`, feedback stored, worktree removed. Never 500 (best-effort).
- [ ] **Step 2:** FAIL. **Step 3:** Implement blueprint; inject store + git fns via `current_app.extensions`. **Step 4:** PASS. **Step 5:** Commit.

---

### Task 6: Mission Control approval tile (carve the cognition tile)

**Files:**
- Modify: `soveryn/app/templates/command_center.html`
- Test: `tests/test_command_center_delegation.py` (template render presence, reuse the `client` conftest fixture)

**Interfaces — Consumes:** `GET /api/delegation/pending`. Locate the cognition tile in the template; wrap it and a new `.scotty-approvals` panel in a twin `grid-template-columns:1fr 1fr` row (mirror `.pulse-row`). Render one card per pending task: objective, Scotty summary, the diff in a `<pre>`, green test line, **Approve**/**Reject** buttons (reject opens a small feedback prompt). `renderScottyApprovals()` fetches `/api/delegation/pending` on the existing refresh cycle; approve/reject POST then refresh.

- [ ] **Step 1: Failing test** — rendered `command_center` contains `scotty-approvals` + a `renderScottyApprovals` hook + the cognition tile now inside a twin row. **Step 2:** FAIL. **Step 3:** Implement (CSS + markup + JS, mirroring the ares tile built 2026-07-03). **Step 4:** PASS. **Step 5:** Commit.

---

### Task 7: Honest-status reader for Aetheria

**Files:**
- Modify: `soveryn/platform/delegation/tools.py` (add `build_task_status_tool`)
- Test: extend `tests/test_dispatch_task_tool.py`

**Interfaces:** `build_task_status_tool(*, store, owner_agent="aetheria")` (name `task_status`): args `{task_id?}` → one task's status/summary, or (no id) her open tasks (`dispatched/executing/in_review` newest-first). `register_delegation_tools` also registers this. Enables her language to track real state.

- [ ] **Step 1: Failing tests** — `task_status` with an id returns that task's status; without an id lists her non-terminal tasks; a `landed` task reports `landed` (the honesty invariant — status is data). **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit.

---

### Task 8: Wiring — tools, background worker, Scotty runner, blueprint

**Files:**
- Modify: `soveryn/app/startup.py`
- Create: `soveryn/platform/delegation/worker.py` (background worker) + `soveryn/platform/delegation/scotty_runner.py` (the real `scotty_run` wrapping Scotty's AgentLoop with `cwd=worktree`, his tools, round/time caps)
- Test: `tests/test_delegation_worker.py`

**Interfaces:** `run_forever(store, engine_deps, poll_seconds=5)` — drains `dispatched` tasks, calls `execute_task` for each (serialized — one at a time; git worktrees + a live repo want no concurrent writers). `scotty_runner.scotty_run(worktree_path, objective, scope)` builds/uses a Scotty AgentLoop pinned to the worktree, capped (`max_tool_rounds`, timeout), returns his summary.

- [ ] **Step 1: Failing test** (`test_delegation_worker.py`, injected engine) — a `dispatched` task gets picked up and `execute_task` invoked exactly once; two dispatched tasks run serially; a task in a terminal state is not re-run.
- [ ] **Step 2:** FAIL. **Step 3:** Implement worker (mirror messenger delivery worker daemon-thread at `startup.py:726`); implement `scotty_runner`. In `startup.py`: construct `DelegationStore`, `register_delegation_tools(tool_registry, store=..., owner_agent="aetheria")`, register the delegation blueprint, and start the worker thread (gated on a `SOVERYN_START_DELEGATION_WORKER` config default True).
- [ ] **Step 4:** PASS + full suite green. **Step 5:** Commit.

---

## First-slice acceptance (manual, after Task 8)
With the fleet up: from an Aetheria chat, `dispatch_task(objective="add a module docstring to soveryn/platform/delegation/__init__.py", scope="soveryn/platform/delegation/__init__.py", acceptance="pytest tests/test_delegation_store.py")` → watch the task go `dispatched→executing→in_review` → the proposal (diff + green tests) appears in the Mission Control approval tile → click **Approve** → branch merges to main, status `landed`, "restart vnext to apply" shown → restart → confirm the docstring is live. Prove the whole loop before pointing it at the Stagnation Detector.

## Self-review notes
- Every task ends at an independently testable deliverable with injected seams; no live-fleet dependency in unit tests.
- Safety constraints (worktree-only, human-approve-to-land, bounded/reversible) are enforced in Tasks 3/4/5 and asserted in their tests.
- Honesty invariant (status is data, never "landed" before merge) is enforced by Task 1's transition guard and asserted in Task 7.
- Signatures are consistent across tasks (DelegationStore methods, engine seams, route shapes).
