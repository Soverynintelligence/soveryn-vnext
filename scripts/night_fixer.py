"""Night fixer — known-failing tests become dispatched tasks overnight.

Jon's goal (2026-09-24): wake up to "hey we fixed this." The delegation engine
proves the loop works; what was missing was a source that feeds it without a
human middleman. This is the first automated source, and it's the most
deterministic one available:

  a test that fails in the nightly run IS a real hole (deterministic signal),
  its acceptance command writes itself (the failing test — red-before-green
  is structural), and the engine's guardrails (worktree isolation, vacuous
  acceptance baseline, human approve gate) bound the blast radius.

Flow (03:30 timer, after the librarian):
  1. run the suite, collect failing test node ids
  2. skip anything on the denylist; skip tests already covered by an OPEN task
  3. dispatch up to MAX_PER_NIGHT tasks (objective/scope/acceptance templated)
  4. append one CC-inbox note: what was dispatched, what was skipped, why

The worker drains every 5s; acceptance judges the work; NOTHING merges
without Jon's approve at /api/delegation/pending. A wrong overnight fix
costs a failed worktree, not the house.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
MAX_PER_NIGHT = 2
OPEN_STATUSES = ("dispatched", "executing", "in_review")

#: Tests that are allowed to fail without a dispatch (documented reasons only).
#: Keep this list SHORT — a denylist entry is a decision that a hole is fine.
DENYLIST: frozenset[str] = frozenset({
    # (empty today — the 2026-09-22 known-red test passes as of 2026-09-24)
})

_FAIL_RE = re.compile(r"^FAILED (tests/[^\s:]+(?:::[^\s:]+)+)")


@dataclass
class NightFixer:
    store: Any  # DelegationStore — duck-typed for tests
    run_pytest: Callable[[], str]  # returns combined stdout/stderr
    dispatch: Callable[..., str]  # store.create_task
    append_note: Callable[..., None]  # automations append_inbox
    repo_root: Path = REPO
    max_per_night: int = MAX_PER_NIGHT
    denylist: frozenset[str] = field(default_factory=lambda: DENYLIST)
    log: Callable[[str], None] = print

    # ── parsing ─────────────────────────────────────────────────────────────
    @staticmethod
    def failing_tests(output: str) -> list[str]:
        """FAILED node ids from pytest output, deduped by test FILE.

        One dispatch per file, not per test: a broken module usually breaks
        several cases, and the fixer should see the whole file's verdict.
        """
        seen: dict[str, str] = {}
        for line in output.splitlines():
            m = _FAIL_RE.match(line.strip())
            if not m:
                continue
            node = m.group(1)
            file_id = node.split("::", 1)[0]
            seen.setdefault(file_id, node)
        return sorted(seen)  # files, sorted for determinism

    # ── dedupe ──────────────────────────────────────────────────────────────
    def _open_task_covers(self, test_file: str) -> bool:
        try:
            open_tasks = self.store.list_tasks()
        except Exception:
            return True  # store unreadable: do not double-dispatch
        for task in open_tasks:
            if getattr(task, "status", "") not in OPEN_STATUSES:
                continue
            if test_file in (getattr(task, "objective", "") or ""):
                return True
        return False

    # ── templates ───────────────────────────────────────────────────────────
    @staticmethod
    def _objective(test_file: str) -> str:
        return (
            f"Make {test_file} pass. It failed in the nightly run — root-cause "
            f"the failure and fix the production code the test exercises, or "
            f"fix the test if the test itself is wrong. Do NOT weaken or delete "
            f"assertions to force a pass; if you conclude the test must change, "
            f"change it minimally and explain why in your report. If the failure "
            f"reveals a requirement that cannot be met, say so plainly instead "
            f"of shipping a workaround."
        )

    @staticmethod
    def _scope(test_file: str) -> str:
        return (
            f"{test_file} plus the production module(s) needed to make it pass "
            f"(follow the imports). No other files."
        )

    @staticmethod
    def _acceptance(test_file: str) -> str:
        return f"python -m pytest {test_file} -q"

    # ── main ────────────────────────────────────────────────────────────────
    def run(self) -> dict[str, list[str]]:
        output = self.run_pytest()
        failing_files = [
            f for f in self.failing_tests(output) if f not in self.denylist
        ]
        dispatched: list[str] = []
        skipped_open: list[str] = []
        for test_file in failing_files:
            if len(dispatched) >= self.max_per_night:
                break
            if self._open_task_covers(test_file):
                skipped_open.append(test_file)
                continue
            task_id = self.dispatch(
                dispatched_by="night-fixer",
                objective=self._objective(test_file),
                scope=self._scope(test_file),
                acceptance=self._acceptance(test_file),
            )
            dispatched.append(f"{test_file} ({task_id[:8]})")

        lines = []
        if dispatched:
            lines.append("**Night fixer dispatched** (worker + acceptance gate + your approve):")
            lines += [f"- {d}" for d in dispatched]
        if skipped_open:
            lines.append(f"- already covered by an open task: {', '.join(skipped_open)}")
        if not lines:
            lines.append("Night fixer: suite green, nothing to fix.")
        try:
            self.append_note(
                automation_id="night_fixer",
                title="Night Fixer",
                agent="kernel",
                channels=["command_center"],
                status="ok",
                content="\n".join(lines),
            )
        except Exception:
            self.log("inbox note failed — dispatches still stand")
        self.log(f"dispatched={len(dispatched)} skipped_open={len(skipped_open)}")
        return {"dispatched": dispatched, "skipped_open": skipped_open}


def _default_run_pytest() -> str:
    proc = subprocess.run(
        ["python3", "-m", "pytest", "-q", "--tb=no"],
        capture_output=True, text=True, timeout=900, cwd=str(REPO),
    )
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def main() -> int:
    from pathlib import Path as _P

    from soveryn.automations.inbox import append_inbox
    from soveryn.platform.delegation.store import DelegationStore

    store = DelegationStore(_P.home() / "soveryn_vnext" / "data" / "delegation.db")
    fixer = NightFixer(
        store=store,
        run_pytest=_default_run_pytest,
        dispatch=lambda **kw: store.create_task(**kw),
        append_note=append_inbox,
    )
    fixer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
