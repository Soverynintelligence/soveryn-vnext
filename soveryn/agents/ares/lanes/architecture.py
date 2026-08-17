"""Architecture invariant collectors for Ares host sentinel."""

from __future__ import annotations

import ast
import os
from pathlib import Path

from soveryn.agents.ares.findings import AresFinding, Severity


FORBIDDEN_IN_AGENTS: frozenset[str] = frozenset({
    "sqlite3",
    "requests",
    "urllib",
    "http.client",
})

RETIRED_AGENTS: frozenset[str] = frozenset({
    "scout",
    "vision",
    "tinker",
    "aetheria_public",
})

# Infrastructure that lives under soveryn/agents/ but is not "agent cognition
# that should only talk through platform." Flagging these forever made Mission
# Control show ~40 permanent WARNING rows (dream writeback, Ares lanes,
# presence stores, daemons) — noise that trained Jon to ignore the bus.
#
# Still flag: persona/loop/tools modules that import sqlite3/requests directly.
# Exempt: daemons, *store*, writeback, Ares itself, known HTTP clients.
_RAW_IO_EXEMPT_PATH_SUBSTRINGS: tuple[str, ...] = (
    "/agents/ares/",           # host sentinel — I/O is the job
    "/agents/presence/",       # X client + staged/candidate stores
    "/agents/signal_bridge/",  # bridge process
    "/agents/heartbeat/",      # daemon
    "/agents/cognition/",      # store
    "/agents/representation/", # writeback path
    "/agents/dream/",          # dream writeback + archive
    "/agents/vett/patrol/",    # patrol daemon
    "/agents/specialists/",    # concurrency + tools that shell out
    "/agents/direct_communication/",
    "/agents/aetheria/tools/", # tool implementations may use HTTP
    "/agents/aetheria/reflection/",
    "/agents/vett/harness/",   # vendor harness
)

_RAW_IO_EXEMPT_FILENAMES: frozenset[str] = frozenset({
    "daemon.py",
    "writeback.py",
    "x_client.py",
    "store.py",
})

DEFAULT_VNEXT_SOVERYN_ROOT = Path.home() / "soveryn_vnext" / "soveryn"


def check_no_raw_io_in_agents(sources: dict[Path, str]) -> list[AresFinding]:
    """Flag direct raw I/O imports under `soveryn/agents/`.

    Agents route SQLite and HTTP access through platform boundaries. This pure
    checker consumes an explicit {path: contents} mapping so tests do not scan
    the live filesystem.

    Infrastructure packages (Ares, daemons, stores) are exempt — they are not
    the cognition path this invariant was written for.
    """

    findings: list[AresFinding] = []
    for path, text in sources.items():
        posix = path.as_posix()
        if "soveryn/agents/" not in posix:
            continue
        if _is_raw_io_exempt(posix):
            continue
        try:
            tree = ast.parse(text, filename=posix)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            for module in _imported_modules(node):
                if _is_forbidden(module):
                    findings.append(AresFinding(
                        "architecture.raw_io_in_agents",
                        Severity.WARNING,
                        {"path": posix, "line": node.lineno, "module": module},
                        key=f"{posix}:{node.lineno}:{module}",
                    ))
    return findings


def _is_raw_io_exempt(posix: str) -> bool:
    """True for agent-tree infrastructure that is allowed raw I/O."""
    name = Path(posix).name
    if name in _RAW_IO_EXEMPT_FILENAMES:
        return True
    if name.endswith("_store.py") or name.endswith("_client.py"):
        return True
    return any(part in posix for part in _RAW_IO_EXEMPT_PATH_SUBSTRINGS)


def check_no_retired_agent_packages(
    *,
    present_packages: frozenset[str],
) -> list[AresFinding]:
    findings: list[AresFinding] = []
    for agent in sorted(present_packages & RETIRED_AGENTS):
        findings.append(AresFinding(
            "architecture.retired_agent_present",
            Severity.WARNING,
            {"agent": agent},
            key=agent,
        ))
    return findings


def check_tool_ownership_intact(
    *,
    tool_owners: dict[str, str],
    active_agents: frozenset[str],
) -> list[AresFinding]:
    findings: list[AresFinding] = []
    for tool, owner in sorted(tool_owners.items()):
        if owner not in active_agents:
            findings.append(AresFinding(
                "architecture.tool_owned_by_inactive_agent",
                Severity.WARNING,
                {"tool": tool, "owner": owner},
                key=f"{tool}:{owner}",
            ))
    return findings


def collect_architecture_live() -> list[AresFinding]:
    """Run the architecture invariants that can be checked from this process.

    Tool-ownership monitoring is intentionally excluded here: the daemon runs in a
    separate process from the Flask app that owns ToolRegistry state, so a direct
    live snapshot would always be empty unless we add explicit shared-state plumbing.
    """

    root = _vnext_root()
    findings: list[AresFinding] = []
    findings.extend(check_no_raw_io_in_agents(_read_agent_sources(root)))
    findings.extend(check_no_retired_agent_packages(
        present_packages=_present_agent_packages(root),
    ))
    return findings


def _vnext_root() -> Path:
    override = os.environ.get("SOVERYN_VNEXT_ROOT")
    return Path(override) / "soveryn" if override else DEFAULT_VNEXT_SOVERYN_ROOT


def _read_agent_sources(root: Path) -> dict[Path, str]:
    sources: dict[Path, str] = {}
    agents_root = root / "agents"
    if not agents_root.is_dir():
        return sources
    for py_file in agents_root.rglob("*.py"):
        try:
            sources[py_file.relative_to(root.parent)] = py_file.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue
    return sources


def _present_agent_packages(root: Path) -> frozenset[str]:
    agents_root = root / "agents"
    if not agents_root.is_dir():
        return frozenset()
    return frozenset(
        path.name
        for path in agents_root.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )



def _imported_modules(node: ast.AST) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        if node.module is None:
            return ()
        return (node.module,)
    return ()


def _is_forbidden(module: str) -> bool:
    return any(module == forbidden or module.startswith(f"{forbidden}.") for forbidden in FORBIDDEN_IN_AGENTS)
