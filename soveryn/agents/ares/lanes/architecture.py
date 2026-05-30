"""Architecture invariant collectors for Ares host sentinel."""

from __future__ import annotations

import ast
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


def check_no_raw_io_in_agents(sources: dict[Path, str]) -> list[AresFinding]:
    """Flag direct raw I/O imports under `soveryn/agents/`.

    Agents route SQLite and HTTP access through platform boundaries. This pure
    checker consumes an explicit {path: contents} mapping so tests do not scan
    the live filesystem.
    """

    findings: list[AresFinding] = []
    for path, text in sources.items():
        posix = path.as_posix()
        if "soveryn/agents/" not in posix:
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
