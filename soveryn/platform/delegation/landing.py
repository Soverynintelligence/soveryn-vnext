"""Landed/done only when code proves the commit, the test, and the reload.

Forge fix 90e6ee41 was reported done but never reached main. The
delegation ledger shows 1 landed vs 62 failed. This module is the
structural gate: a Forge/Kernel task may be marked ``landed`` / ``done``
only when

* its commit is reachable from ``main``
* its named test (the task's required repro/test) passes on that commit
* the affected service has been reloaded since that commit — unit start
  time after commit time, or an explicit ReloadRecord

Otherwise the status stays ``pending-verify`` (stale service) or
``failed`` with the reason. Model text is not a substitute.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from soveryn.paths import SoverynPaths
from soveryn.platform.delegation.store import DelegationStore, LedgerWriteError

logger = logging.getLogger(__name__)

LANDED = "landed"
PENDING_VERIFY = "pending-verify"
FAILED = "failed"
PROBE_NAME = "landing_proof"
_PROBES_ENV = "SOVERYN_LANDING_PROBES"

GitRun = Callable[..., str]
SysRun = Callable[..., Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp. Naive values are treated as UTC."""
    if not ts:
        return None
    raw = str(ts).strip()
    if not raw or raw.lower() in {"n/a", "none"}:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class ReloadRecord:
    """An explicit service reload after a commit. Model text is not a substitute."""

    service: str
    reloaded_at: str
    commit: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {"service": self.service, "reloaded_at": self.reloaded_at}
        if self.commit:
            out["commit"] = self.commit
        return out


@dataclass(frozen=True)
class LandingVerdict:
    """What may be written after the landing-proof gate."""

    status: str
    reason: str
    commit: str = ""
    test_name: str = ""
    service: str = ""

    @property
    def landed(self) -> bool:
        return self.status == LANDED

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "commit": self.commit,
            "test_name": self.test_name,
            "service": self.service,
            "landed": self.landed,
        }

    def probe(self) -> dict[str, Any]:
        """ProbeRecord-shaped row so a pulse can treat this as verified (PR 1)."""
        if self.status == LANDED:
            result = "ok"
        elif self.status == PENDING_VERIFY:
            result = "deferred"
        else:
            result = "fail"
        return {
            "target": self.commit or "landing",
            "timestamp": _utc_now(),
            "result": result,
            "name": PROBE_NAME,
            "detail": self.reason,
        }

    def as_probe_record(self) -> Any:
        raw = self.probe()
        try:
            from soveryn.platform.inference.outage import ProbeRecord

            return ProbeRecord(
                target=raw["target"],
                timestamp=raw["timestamp"],
                result=raw["result"],
                name=raw["name"],
                detail=raw["detail"],
            )
        except Exception:
            return raw


def commit_reachable_from_main(
    commit: str,
    *,
    repo: str | Path,
    git_run: GitRun | None = None,
    main_ref: str = "main",
) -> bool:
    """True when *commit* is an ancestor of *main_ref* (reachable from main)."""
    sha = (commit or "").strip()
    if not sha:
        return False
    runner = git_run or _default_git
    try:
        runner(repo, "merge-base", "--is-ancestor", sha, main_ref)
        return True
    except Exception:
        return False


def commit_time_iso(
    commit: str,
    *,
    repo: str | Path,
    git_run: GitRun | None = None,
) -> str | None:
    """Committer date of *commit* as ISO-8601, or None if unknown."""
    sha = (commit or "").strip()
    if not sha:
        return None
    runner = git_run or _default_git
    try:
        out = runner(repo, "log", "-1", "--format=%cI", sha).strip()
    except Exception:
        return None
    return out or None


def unit_start_iso(
    unit: str,
    *,
    runner: SysRun | None = None,
) -> str | None:
    """``ActiveEnterTimestampUSec`` of a user unit, as UTC ISO-8601."""
    name = (unit or "").strip()
    if not name:
        return None
    run = runner or subprocess.run
    try:
        done = run(
            ["systemctl", "--user", "show", name, "-p", "ActiveEnterTimestampUSec", "--value"],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return None
    raw = (getattr(done, "stdout", None) or "").strip()
    if not raw.isdigit() or raw == "0":
        return None
    try:
        usec = int(raw)
    except ValueError:
        return None
    dt = datetime.fromtimestamp(usec / 1_000_000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def reload_covers_commit(
    *,
    commit_at: datetime | None,
    unit_started_at: str | None,
    reload: ReloadRecord | None,
    commit: str = "",
    service: str = "",
) -> bool:
    """True when the unit started after the commit, or a reload was recorded."""
    if reload is not None:
        service_ok = not service or not reload.service or reload.service == service
        commit_ok = not commit or not reload.commit or reload.commit == commit
        rel = parse_iso(reload.reloaded_at)
        if service_ok and commit_ok and rel is not None:
            if commit_at is None or rel > commit_at:
                return True
    started = parse_iso(unit_started_at)
    if started is None or commit_at is None:
        return False
    return started > commit_at


def evaluate_landing(
    *,
    commit: str,
    test_name: str,
    service: str,
    on_main: bool | None = None,
    test_passed: bool | None = None,
    test_output: str = "",
    commit_at: str | None = None,
    unit_started_at: str | None = None,
    reload: ReloadRecord | None = None,
    repo: str | Path | None = None,
    git_run: GitRun | None = None,
    run_test: Callable[[str, str], tuple[bool, str]] | None = None,
    systemd_run: SysRun | None = None,
) -> LandingVerdict:
    """Decide landed / pending-verify / failed from code-gathered facts.

    Missing proof fails closed: a commit not shown on main, or a test
    not shown passing, cannot land. A proven commit+test with a stale
    (or unproven) service stays ``pending-verify``.
    """
    sha = (commit or "").strip()
    named = (test_name or "").strip()
    unit = (service or "").strip()

    if on_main is None:
        on_main = bool(repo) and commit_reachable_from_main(
            sha, repo=repo, git_run=git_run
        )
    if not on_main:
        return LandingVerdict(
            status=FAILED,
            reason=f"commit {sha or '(missing)'} is not reachable from main",
            commit=sha,
            test_name=named,
            service=unit,
        )

    if test_passed is None:
        if run_test is None or not named:
            test_passed = False
            test_output = test_output or "required test was not run"
        else:
            test_passed, produced = run_test(named, sha)
            test_output = produced or test_output
    if not test_passed:
        detail = (test_output or "").strip() or "no output"
        return LandingVerdict(
            status=FAILED,
            reason=f"required test {named or '(missing)'} failed on {sha}: {detail}",
            commit=sha,
            test_name=named,
            service=unit,
        )

    if unit_started_at is None and unit and systemd_run is not None:
        unit_started_at = unit_start_iso(unit, runner=systemd_run)
    if commit_at is None and repo is not None and sha:
        commit_at = commit_time_iso(sha, repo=repo, git_run=git_run)

    if not reload_covers_commit(
        commit_at=parse_iso(commit_at),
        unit_started_at=unit_started_at,
        reload=reload,
        commit=sha,
        service=unit,
    ):
        return LandingVerdict(
            status=PENDING_VERIFY,
            reason=(
                f"service {unit or '(unspecified)'} has not been reloaded "
                f"since commit {sha}"
            ),
            commit=sha,
            test_name=named,
            service=unit,
        )

    return LandingVerdict(
        status=LANDED,
        reason=(
            f"commit {sha} reachable from main; {named} passed; "
            f"{unit} reloaded since the commit"
        ),
        commit=sha,
        test_name=named,
        service=unit,
    )


def apply_landing(
    store: DelegationStore,
    task_id: str,
    verdict: LandingVerdict,
) -> LandingVerdict:
    """Write the verdict through the committed-dispatch store. Re-read after.

    ``landed`` is recorded only when the verdict is landed *and* the row
    still reads that way. A persist miss is a fail probe, never a claim.
    """
    task = store.get_task(task_id)
    if task is None:
        _record_probe(verdict.probe(), store=store)
        return verdict
    try:
        if verdict.status == LANDED:
            if task.status in {"in_review", PENDING_VERIFY}:
                store.set_status(task_id, LANDED)
        elif verdict.status == PENDING_VERIFY:
            if task.status == "in_review":
                store.set_status(task_id, PENDING_VERIFY)
            store.set_review(task_id, review_feedback=verdict.reason)
        else:
            if task.status in {"in_review", PENDING_VERIFY}:
                store.set_status(task_id, FAILED)
            store.set_review(task_id, review_feedback=verdict.reason)
    except LedgerWriteError as exc:
        missed = LandingVerdict(
            status=FAILED,
            reason=f"landing ledger write failed for {task_id}; not landed: {exc}",
            commit=verdict.commit,
            test_name=verdict.test_name,
            service=verdict.service,
        )
        _record_probe(missed.probe(), store=store)
        return missed
    except Exception:
        logger.exception("landing: could not apply %s to task %s", verdict.status, task_id)

    again = store.get_task(task_id)
    if verdict.status == LANDED and (again is None or again.status != LANDED):
        missed = LandingVerdict(
            status=FAILED,
            reason=f"landing ledger write did not persist {task_id}; not landed",
            commit=verdict.commit,
            test_name=verdict.test_name,
            service=verdict.service,
        )
        _record_probe(missed.probe(), store=store)
        return missed
    _record_probe(verdict.probe(), store=store)
    return verdict


def mark_landed(
    store: DelegationStore,
    task_id: str,
    **evidence: Any,
) -> LandingVerdict:
    """The only honest write path to landed/done. Unproven work stays unlanded."""
    verdict = evaluate_landing(**evidence)
    return apply_landing(store, task_id, verdict)


def recent_landing_probes(
    *,
    limit: int = 8,
    path: Path | None = None,
) -> tuple[dict[str, Any], ...]:
    """Recent landing-proof fail probes for the pulse / outage gate."""
    probe_path = path or _probe_path()
    if not probe_path.is_file():
        return ()
    try:
        lines = probe_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) * 4 :]:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("result") == "fail":
            rows.append(row)
    return tuple(rows[-limit:])


def format_landing_error_block(*, limit: int = 8) -> str:
    """Heartbeat prompt block. Empty when nothing probed-failing."""
    downs = recent_landing_probes(limit=limit)
    if not downs:
        return ""
    lines = ["## Verified landing failures (same-store probe records)"]
    for row in downs:
        lines.append(
            f"- {row.get('name') or PROBE_NAME}: result={row.get('result')} "
            f"target={row.get('target')} timestamp={row.get('timestamp')}"
            + (f" ({row.get('detail')})" if row.get("detail") else "")
        )
    lines.append(
        "These are code-gathered probe records. Do not claim the matching "
        "task landed or is done."
    )
    return "\n".join(lines) + "\n\n"


def as_probe_records(
    probes: list[dict[str, Any]] | tuple[dict[str, Any], ...],
) -> list[Any]:
    """PR 1 ProbeRecord when that module exists; otherwise the raw dicts."""
    try:
        from soveryn.platform.delegation.dispatch import (
            as_probe_records as _dispatch_as_probe_records,
        )

        return _dispatch_as_probe_records(probes)
    except Exception:
        return list(probes)


def _probe_path() -> Path:
    override = os.environ.get(_PROBES_ENV, "").strip()
    if override:
        return Path(override)
    return SoverynPaths.data() / "landing_probes.jsonl"


def _record_probe(probe: dict[str, Any], *, store: DelegationStore | None) -> None:
    if probe.get("result") != "fail":
        return
    path = _probe_path()
    if store is not None and not os.environ.get(_PROBES_ENV, "").strip():
        path = store.db_path.parent / "landing_probes.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(probe, default=str) + "\n")
    except Exception:
        logger.warning("landing probe persist failed", exc_info=True)


def _default_git(repo: str | Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout
