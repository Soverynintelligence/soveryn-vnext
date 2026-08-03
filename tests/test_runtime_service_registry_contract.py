"""Every declared runtime service must correspond to something that exists.

`RUNTIME_SERVICES` in soveryn/config/runtime.py is the registry vNext preflight
and Mission Control read to answer "is this running?". It is a *declaration* —
prose in a dataclass — and nothing has ever checked it against the code.

On 2026-07-31 both of its `launch="app_startup"` entries turned out to be false:

  cognition   declared as a thread started at app startup.
              No such thread exists anywhere in soveryn/app/. The deep cognition
              cycle has never run — 12 test files, a tested decision core, a
              wired CognitionStore that Mission Control reads correctly, and no
              caller. The UI said "the cognition engine hasn't run" and was right.

  heartbeat   declared as a thread started at app startup.
              It runs, but as a separate process: `python -m soveryn.agents.heartbeat`.
              The declaration is wrong about both `kind` and `launch`.

Nobody noticed for weeks because a registry that lies reads exactly like one that
tells the truth. This is the same defect the whole 2026-07-31 sequence turned on:
absence of evidence presented as evidence of presence, one layer up.

Sibling guard to `test_shared_context_wiring_contract.py`, which walks every
`AgentLoop(` call site. That one catches wiring never done; this one catches
wiring *declared* and never done.

Scope: only `kind="thread"` + `launch="app_startup"` is statically checkable —
a thread launched at import time in a known package. Processes and scheduled
jobs live outside this repo's control flow and are covered by preflight at
runtime, not here.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from soveryn.config.runtime import RUNTIME_SERVICES

APP_DIR = Path(__file__).resolve().parent.parent / "soveryn" / "app"


def _normalise(text: str) -> str:
    """Fold naming conventions: 'delegation-worker' ~ 'delegation_worker'."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def _threads_started_in_app() -> list[tuple[str, int, str]]:
    """Every threading.Thread(...) constructed under soveryn/app/.

    Returns (identifier, lineno, path) where identifier is the thread's `name=`
    if present, else its `target=` expression — whichever the code offers.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if fname != "Thread":
                continue
            ident = ""
            for kw in node.keywords:
                if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                    ident = str(kw.value.value)
                elif kw.arg == "target" and not ident:
                    ident = ast.unparse(kw.value)
            found.append((ident, node.lineno, str(path)))
    return found


APP_STARTUP_THREADS = [
    s for s in RUNTIME_SERVICES
    if s.launch == "app_startup" and s.kind == "thread"
]


def test_registry_declares_at_least_one_app_startup_thread():
    """Guard the guard: if the registry empties, this file must not silently pass."""
    assert APP_STARTUP_THREADS, (
        "No app_startup threads declared in RUNTIME_SERVICES. Either the registry "
        "was emptied or its shape changed — this contract is now vacuous and must "
        "be updated rather than left green."
    )


@pytest.mark.parametrize("service", APP_STARTUP_THREADS, ids=lambda s: s.name)
def test_declared_app_startup_thread_is_actually_started(service):
    """A service declared as an app-startup thread must have a Thread that starts it.

    Failing here means the registry claims something the code does not do. The fix
    is one of two things, and which one is a real decision:

      - the service should be a thread and is not  → wire it in startup.py
      - the service runs some other way            → correct `kind`/`launch`

    Do not "fix" this by deleting the declaration unless the service is genuinely
    gone. A registry that omits a running service is as wrong as one that invents
    a stopped one.
    """
    threads = _threads_started_in_app()
    want = _normalise(service.name)
    matches = [t for t in threads if want in _normalise(t[0])]

    assert matches, (
        f"RUNTIME_SERVICES declares {service.name!r} as kind={service.kind!r} "
        f"launch={service.launch!r}, but no threading.Thread under soveryn/app/ "
        f"names or targets it.\n"
        f"  declared role: {service.role}\n"
        f"  threads found: "
        + (", ".join(f"{ident or '<unnamed>'} ({Path(p).name}:{ln})"
                     for ident, ln, p in threads) or "<none>")
        + "\n\nEither start it, or correct the declaration to match how it really runs."
    )


# ─── systemd-launched services ───────────────────────────────────────────────
#
# The thread contract above covers 2 of 6 entries. It found both were false.
# On 2026-07-31 the remaining four were checked by hand and two of those were
# false too — ares_daemon declared user_launched when it runs under
# soveryn-ares.service, and dream_aetheria declared "scheduled" when it is a
# continuously-running Type=simple service with no timer.
#
# Four of six pre-existing declarations were wrong. The two that were right had
# been derived from the code rather than written by hand. That is the whole
# argument for deriving rather than declaring.
#
# These checks need a live systemd, so they skip where there isn't one (CI)
# rather than failing. A skip is honest; a false green is not.

SYSTEMD_SERVICES = [
    s for s in RUNTIME_SERVICES if s.launch == "systemd"
]


def _systemctl(*args: str) -> tuple[int, str]:
    import subprocess
    try:
        r = subprocess.run(["systemctl", "--user", *args],
                           capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip()
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return 127, ""


@pytest.mark.parametrize("service", SYSTEMD_SERVICES, ids=lambda s: s.name)
def test_declared_systemd_service_has_a_unit(service):
    """A service declared launch="systemd" must have a unit systemd knows about.

    Checks existence, not liveness — a stopped service is an operational matter,
    but a *nonexistent* unit means the registry is describing something that
    cannot run at all.
    """
    rc, _ = _systemctl("--version")
    if rc != 0:
        pytest.skip("no user systemd available")

    # Unit names are inferred, which is itself a weak link — the registry has no
    # field naming its unit, so this guesses. If it ever guesses wrong the right
    # fix is to add an explicit `unit:` field to RuntimeService rather than to
    # widen this list again. Guessing is the failure mode this file exists to
    # catch, and it should not be load-bearing here forever.
    base = service.name
    stems = {base, base.replace("_", "-")}
    for suffix in ("_daemon", "_aetheria", "_cycle"):
        if base.endswith(suffix):
            trimmed = base[: -len(suffix)]
            stems |= {trimmed, trimmed.replace("_", "-")}
    candidates = [f"soveryn-{s}.service" for s in sorted(stems)]
    candidates += [f"{s}.service" for s in sorted(stems)]
    for unit in candidates:
        rc, out = _systemctl("show", unit, "-p", "LoadState", "--no-pager")
        if rc == 0 and "LoadState=loaded" in out:
            return
    pytest.fail(
        f"RUNTIME_SERVICES declares {service.name!r} as launch='systemd', but no "
        f"loaded unit matches any of {candidates}.\n"
        f"  declared role: {service.role}\n"
        "Either the unit is missing, or the declaration names it wrongly."
    )
