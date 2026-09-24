"""ActTruth honest stats + shareable proof blurbs.

Lean into receipts: numbers from the ledger only — no invented uplift.
Built for X/posts: short, concrete, falsifiable.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# get_acttruth: late-imported from acttruth.audit
from acttruth.lessons import lessons_from_events
from acttruth.unprompted import CREW_AGENTS

def _at():
    """Resolve ActTruth handle (late import so hosts can patch acttruth.audit.get_acttruth)."""
    from acttruth.audit import get_acttruth
    return get_acttruth()



@dataclass
class AgentProofStats:
    agent_id: str
    events: int = 0
    ok: int = 0
    fail: int = 0
    timeouts: int = 0
    lessons_armed: int = 0
    budget_used: int = 0
    budget_limit: int = 0
    budget_remaining: int = 0
    top_fail_tools: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class ActTruthProof:
    window_hours: float
    generated_at: str
    root: str
    total_events: int
    total_ok: int
    total_fail: int
    total_timeouts: int
    lessons_armed: int
    agents: list[AgentProofStats]
    pytest_passed: int | None = None
    pytest_failed: int | None = None
    pytest_note: str = ""
    site: str = "https://acttruth.com"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    def fail_rate(self) -> float | None:
        n = self.total_ok + self.total_fail
        if n <= 0:
            return None
        return round(100.0 * self.total_fail / n, 1)


def collect_proof(
    *,
    window_hours: float = 24.0,
    include_pytest: bool = True,
    agents: tuple[str, ...] | None = None,
) -> ActTruthProof:
    """Aggregate ledger stats. Optional live pytest count for the proof suite."""
    at = _at()
    since = datetime.now() - timedelta(hours=window_hours)
    events = at.ledger.since(since=since, limit=10000)
    agent_ids = agents or CREW_AGENTS

    by_agent: dict[str, list] = {a: [] for a in agent_ids}
    for ev in events:
        by_agent.setdefault(ev.agent_id, []).append(ev)

    agent_stats: list[AgentProofStats] = []
    total_ok = total_fail = total_timeouts = lessons = 0

    for aid in agent_ids:
        evs = by_agent.get(aid, [])
        ok = sum(1 for e in evs if e.ok)
        fail = sum(1 for e in evs if not e.ok)
        timeouts = sum(1 for e in evs if e.kind == "timeout" or (
            not e.ok and "timeout" in (e.summary or "").lower()
        ))
        Ls = lessons_from_events(evs, streak=2)
        fail_tools = Counter(
            (e.tool or "unknown") for e in evs if not e.ok and e.tool
        )
        b = at.budget.check(aid)
        agent_stats.append(
            AgentProofStats(
                agent_id=aid,
                events=len(evs),
                ok=ok,
                fail=fail,
                timeouts=timeouts,
                lessons_armed=len(Ls),
                budget_used=b.used,
                budget_limit=b.limit,
                budget_remaining=b.remaining,
                top_fail_tools=fail_tools.most_common(3),
            )
        )
        total_ok += ok
        total_fail += fail
        total_timeouts += timeouts
        lessons += len(Ls)

    # Also count any agents that appeared in the window but aren't in CREW list
    for aid, evs in by_agent.items():
        if aid in agent_ids:
            continue
        ok = sum(1 for e in evs if e.ok)
        fail = sum(1 for e in evs if not e.ok)
        total_ok += ok
        total_fail += fail

    pytest_passed = pytest_failed = None
    pytest_note = ""
    if include_pytest:
        pytest_passed, pytest_failed, pytest_note = _run_proof_pytest()

    return ActTruthProof(
        window_hours=window_hours,
        generated_at=datetime.now().isoformat(timespec="seconds"),
        root=str(at.root),
        total_events=len(events),
        total_ok=total_ok,
        total_fail=total_fail,
        total_timeouts=total_timeouts,
        lessons_armed=lessons,
        agents=agent_stats,
        pytest_passed=pytest_passed,
        pytest_failed=pytest_failed,
        pytest_note=pytest_note,
    )


def _run_proof_pytest() -> tuple[int | None, int | None, str]:
    """Run the ActTruth proof suite; return (passed, failed, note)."""
    import os
    # Prefer explicit path; else monorepo checkout; else package-bundled tests.
    candidates: list[Path] = []
    env = os.environ.get("ACTTRUTH_PROOF_TEST", "").strip()
    if env:
        candidates.append(Path(env))
    # soveryn_vnext/tests when editable-installed from monorepo
    here = Path(__file__).resolve()
    for parent in here.parents:
        cand = parent / "tests" / "test_acttruth.py"
        if cand.is_file():
            candidates.append(cand)
            break
    pkg_tests = here.parents[2] / "tests" / "test_acttruth.py"
    candidates.append(pkg_tests)
    test = next((c for c in candidates if c.is_file()), None)
    if test is None:
        return None, None, "proof suite not found"
    repo = test.parent.parent
    try:
        proc = subprocess.run(
            [
                "python", "-m", "pytest", str(test), "-q", "--tb=no",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # pytest -q: "10 passed" or "8 passed, 2 failed"
        import re
        m = re.search(r"(\d+)\s+passed", out)
        passed = int(m.group(1)) if m else None
        m2 = re.search(r"(\d+)\s+failed", out)
        failed = int(m2.group(1)) if m2 else 0
        if passed is None and proc.returncode != 0:
            return None, None, out.strip()[-200:] or f"exit {proc.returncode}"
        return passed, failed if failed else 0, "tests/test_acttruth.py"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}"


def format_proof_post(proof: ActTruthProof, *, style: str = "x") -> str:
    """Shareable receipt. style=x → short for posts; markdown → longer."""
    rate = proof.fail_rate()
    rate_s = f"{rate}%" if rate is not None else "n/a"
    lines: list[str] = []
    if style == "markdown":
        lines.append("# ActTruth proof receipt")
        lines.append("")
        lines.append(f"Window: last **{proof.window_hours:g}h** · {proof.generated_at}")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("|--------|------:|")
        lines.append(f"| events | {proof.total_events} |")
        lines.append(f"| ok | {proof.total_ok} |")
        lines.append(f"| FAIL | {proof.total_fail} |")
        lines.append(f"| timeouts | {proof.total_timeouts} |")
        lines.append(f"| fail rate | {rate_s} |")
        lines.append(f"| lessons armed | {proof.lessons_armed} |")
        if proof.pytest_passed is not None:
            lines.append(
                f"| proof suite | {proof.pytest_passed} passed"
                f"{f', {proof.pytest_failed} failed' if proof.pytest_failed else ''} |"
            )
        lines.append("")
        lines.append("Per agent:")
        for a in proof.agents:
            lines.append(
                f"- **{a.agent_id}**: {a.events} events · {a.fail} FAIL · "
                f"{a.timeouts} timeouts · lessons {a.lessons_armed} · "
                f"budget {a.budget_used}/{a.budget_limit}"
            )
        lines.append("")
        lines.append(
            "_Numbers from the ActTruth ledger only. "
            "No invented uplift. Failures are the product._"
        )
        lines.append(f"\n{proof.site}")
        return "\n".join(lines)

    # X / short
    lines.append("ActTruth proof (ledger receipts, not vibes)")
    lines.append("")
    lines.append(f"last {proof.window_hours:g}h · {proof.total_events} events")
    lines.append(
        f"{proof.total_ok} ok · {proof.total_fail} FAIL · "
        f"{proof.total_timeouts} timeouts · fail rate {rate_s}"
    )
    lines.append(f"lessons armed (anti-loop): {proof.lessons_armed}")
    if proof.pytest_passed is not None:
        fail_bit = f", {proof.pytest_failed} failed" if proof.pytest_failed else ""
        lines.append(f"proof suite: {proof.pytest_passed} passed{fail_bit}")
    lines.append("")
    for a in proof.agents:
        if a.events == 0 and a.fail == 0:
            continue
        top = ""
        if a.top_fail_tools:
            top = " · top fail: " + ", ".join(f"{t}×{n}" for t, n in a.top_fail_tools)
        lines.append(
            f"{a.agent_id}: {a.fail} FAIL / {a.events} · "
            f"budget {a.budget_used}/{a.budget_limit}{top}"
        )
    lines.append("")
    lines.append("Quiet failures become rows. Repeat FAILs become lessons.")
    lines.append(proof.site)
    return "\n".join(lines)
