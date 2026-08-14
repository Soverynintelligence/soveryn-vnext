# Aetheria Delegated Execution with Review Gate — Design

**Date:** 2026-07-06
**Status:** Design for review.
**Scope:** Give Aetheria a real, *honest* way to act on her decisions. She dispatches a scoped task → Scotty executes it in an **isolated git worktree** (never the live tree) → **tests verify** → the diff surfaces as a **proposal in a Mission Control approval tile** → **Jon reviews** → approve *lands* it / reject *discards* it. This closes both gaps we watched live today: her *"I'm directing Scotty to implement X"* becomes true (a real task ran), and it's safe (nothing reaches prod unverified/unreviewed).

## Why (grounded in what we observed 2026-07-06)
Two consecutive heartbeat pulses made the case:
- Pulse A: she narrated *"I'm directing Scotty to implement the Stagnation Detector immediately"* — but no dispatch fired, Scotty never ran. **Intent narrated as completed action** (the honesty gap) because she had no working way to execute.
- Pulse B: she *actually* dispatched (`vett-scotty` invoked 5×), it **500'd**, and she reported the failure truthfully, then pivoted to reading the repo (she has `read_file`/`list_directory`). **When she has and uses a real capability, she's honest.**

Root technical facts: `ScottyRepairSurface.execute()` (`soveryn/agents/scotty/repair_surface.py`) is **declared-but-unported** (`raise ScottyRepairNotPortedError`). `direct_message_agent → scotty` (mode=`execute`) just dispatches a directive into Scotty's chat loop — no structure, no isolation, no verification, and currently 500-ing. So: **build the real execution engine, safely.** The honesty and the safety come from the same mechanism — verification + review.

## Safety posture (non-negotiable — this is why the design looks like this)
- Scotty **never edits the live tree** — only a throwaway worktree. (`agent damage is load-bearing`: a prior agent deleted soveryn. Isolation is the floor, not a nicety.)
- **Nothing merges without human approval.** Review-before-live, confirmed by Jon.
- Execution is **bounded** (max tool rounds, timeout, scope cap) and **reversible** (worktree is disposable).

## What exists to build on (grounded)
- **Scotty's real tools** (`register_scotty_tools`): `read_file, list_directory, git_status, git_diff, edit_file, run_command, git_restore_file` — a genuine bounded coding surface.
- **`ScottyRepairSurface`** (`repair_surface.py`) — the declared entry (`execute(RepairRequest) -> RepairResult`); this spec ports it.
- **`direct_message_agent`** (`direct_communication/tools.py`, modes execute/query, targets {vett,scotty}) — the current fragile rail; superseded for tasks by `dispatch_task`.
- **Git worktrees work here** (a live `soveryn_vnext-spike-swappable-brain` worktree exists) — use the `superpowers:using-git-worktrees` pattern.
- **Mission Control twin-panel pattern** (`command_center.html` `.pulse-row` grid 1fr 1fr — the heartbeat/ares split built 2026-07-03) — mirror it to carve the approval tile from the cognition tile.

## Components

### 1. Task store — `soveryn/platform/delegation/store.py` (new, SQLite)
A `Task` row: `id`, `dispatched_by` (aetheria), `objective`, `scope` (target area/files), `acceptance` (the test/command that defines done), `status` ∈ {`dispatched`,`executing`,`in_review`,`landed`,`rejected`,`failed`}, `worktree_path`, `branch`, `diff`, `test_output`, `summary`, `review_feedback`, `created_at`, `updated_at`. Pure store (path-injected, testable), mirroring `documents/store.py`.

### 2. `dispatch_task` tool — Aetheria-owned (`soveryn/platform/delegation/tools.py`)
`dispatch_task(objective, scope, acceptance) -> {task_id, status:"dispatched"}`. Writes a Task and enqueues execution. Honest return + honest status: she gets a real id and a real state. Replaces the "message Scotty and hope" path for actual work. (Registered for aetheria; heartbeat pulse surface included.)

### 3. Scotty execution engine — the port of `ScottyRepairSurface`
`execute_task(task, ...)`:
1. **Isolate:** create a git worktree off `main` on a fresh branch `task/<id>` (`using-git-worktrees`).
2. **Run bounded:** Scotty's AgentLoop, scoped to the worktree, with his tools (read/edit/run_command/git). Caps: max tool rounds, wall-clock timeout, and a scope guard (edits confined to `scope`). Status → `executing`.
3. **Verify:** run the task's `acceptance` (e.g., `pytest <target>`), plus a repo sanity check, in the worktree. All green → continue; not green → Scotty gets one repair iteration, then on failure status → `failed` with the test output (honest — no proposal from red).
4. **Package:** `git diff` + test output + a short Scotty summary → onto the Task; status → `in_review`. The worktree/branch is retained for landing.

### 4. Review surface — Mission Control approval tile
Carve the **cognition tile** in half (mirror the `.pulse-row` twin split); the new half is the **Scotty Approvals** queue. Each `in_review` task renders: objective, Scotty's summary, the **diff**, the **test result (green)**, and **Approve / Reject** controls. Backend: `GET /api/delegation/pending` (reader) + `POST /api/delegation/<id>/approve` and `/reject` (with feedback). Read-only render of the diff; actions are explicit.

### 5. Land / discard
- **Approve** → merge `task/<id>` into `main` (fast-forward or merge), remove the worktree, status → `landed`. If the change touches running code, surface a "restart vnext to apply" note (do not auto-restart in slice 1).
- **Reject** (with feedback) → discard the worktree/branch, status → `rejected`, feedback stored (and readable by Aetheria so she can revise).

### 6. Honest status thread
The Task's `status` is the single source of truth. Aetheria reads it (a `task_status` reader tool and/or ambient "your open tasks" context in the pulse) so her language tracks reality: *dispatched → executing → in review → landed/rejected/failed*. She structurally cannot say "implemented" before `landed` — because that's a real state, not a self-report. This is the honesty fix, enforced by data, not by asking her to be careful.

## Data flow (happy path)
She decides → `dispatch_task(objective, scope, acceptance)` → Task(`dispatched`) → engine makes worktree, Scotty edits + runs tests there (`executing`) → tests green → diff+summary packaged (`in_review`) → appears in the Mission Control approval tile → Jon clicks Approve → branch merges to main, worktree removed (`landed`) → her next pulse reads status=`landed` and says so, truthfully.

## Error handling / edge cases (all tested)
Tests never pass (→ `failed`, honest, no proposal); Scotty exceeds round/time cap (→ `failed` with partial diff for context); edits stray outside `scope` (guard blocks/flags); worktree creation fails (→ `failed`, clean up); approve when the branch no longer merges cleanly (surface a conflict, don't force); reject discards fully (no orphan worktrees — `git worktree prune`); dispatch while an identical task is already open (dedup or allow, decision below).

## Testing
- **`test_delegation_store.py`** — Task CRUD + status transitions (only legal transitions succeed).
- **`test_dispatch_task_tool.py`** — creates a Task with the right fields; returns id+status; validation.
- **`test_scotty_execute_task.py`** (unit, injected git+loop seams) — worktree created; Scotty edits confined to scope; green tests → `in_review` with diff/summary; red tests → `failed`, no proposal; caps enforced.
- **`test_delegation_routes.py`** (Flask client) — `/api/delegation/pending` shape; approve merges + marks landed (fake git); reject discards + marks rejected + stores feedback.
- **Template presence** — cognition tile halved, `scotty-approvals` block + render hook.
- **Honesty invariant test** — a Task not yet `landed` never reports as landed via the status reader.

## Scope
**IN:** the task store, `dispatch_task`, the Scotty worktree-isolated execution engine (porting `ScottyRepairSurface`), verification gate, the Mission Control approval tile + approve/reject/land API, the honest-status reader, tests. Also: fix the dispatch so it no longer 500s (this replaces the fragile `direct_message_agent → scotty` execute path for tasks).
**OUT (deferred):** auto-landing of "small + green" tasks (earn it later once we've watched review be right); auto-restart on land; Aetheria approving her own tasks after a verification gate (later); multi-agent tasks; anything beyond Scotty as executor.

## First slice (thin vertical — build this first)
Dispatch a **trivial scoped task** (e.g., "add a one-line docstring to file X, acceptance: `pytest tests/<x>` stays green") → worktree → Scotty makes the one change → tests run → proposal appears in the approval tile → Jon approves → it lands on main. Prove the *entire loop* end-to-end on something safe before pointing it at real features like the Stagnation Detector.

## Open decisions to confirm
1. **Dispatch dedup** — if she dispatches a task that overlaps an open one, dedup or allow parallel? (Lean: allow, but show both in the queue.)
2. **Acceptance format** — free-form command string she supplies (e.g. `pytest tests/foo.py`), vs. a structured field. (Lean: command string, validated to be a test/check invocation.)
3. **Approve → restart** — slice 1 surfaces "restart vnext to apply" as a manual step; auto-restart is a later convenience. Confirm manual-first.
