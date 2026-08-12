"""SOVERYN vNext — per-agent soul.md loader (read-only).

Each active agent has an identity document at
data/memory/souls/<agent>.md. This module reads those files and
nothing else.

Missing-file behavior:
  - Default: raise SoulMissingError. Tests rely on this.
  - Runtime opt-in to degrade: pass raise_on_missing=False explicitly.

Path traversal: agent names are normalized (lowered, stripped) and
rejected if they contain anything outside [a-z_]. Defense in depth.

Memory Grades PR5 (2026-08-11): origin essays live in
`<agent>.origin.md` and are off the hot path. `get_soul()` returns
hard rules only; `include_origin=True` or `get_soul_origin()` loads
the essay. Aetheria's `read_soul_origin` tool uses the latter.
"""

from __future__ import annotations
import re
from pathlib import Path

from soveryn.config.loader import load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED


class SoulError(Exception):
    """Base class for soul-loader errors."""


class SoulNameError(SoulError):
    """Agent name is retired, unknown, or contains path-unsafe characters."""


class SoulMissingError(SoulError):
    """Soul file does not exist for an active agent."""


_VALID_NAME = re.compile(r"^[a-z_]+$")


def _normalize(agent: str) -> str:
    if not isinstance(agent, str):
        raise SoulNameError(f"agent must be str, got {type(agent).__name__}")
    name = agent.strip().lower()
    if not _VALID_NAME.fullmatch(name):
        raise SoulNameError(f"agent name {agent!r} contains disallowed characters")
    if name in RETIRED:
        raise SoulNameError(f"agent {name!r} is retired; refusing to load soul")
    if name not in ACTIVE_AGENTS:
        raise SoulNameError(f"agent {name!r} is not in ACTIVE_AGENTS")
    return name


def _souls_dir(souls_dir: Path | None) -> Path:
    if souls_dir is None:
        return load_env_config().souls_dir
    return souls_dir


def get_soul(
    agent: str,
    *,
    souls_dir: Path | None = None,
    raise_on_missing: bool = True,
    include_origin: bool = False,
) -> str:
    """Return the soul.md text for an active agent (hard rules by default).

    If `souls_dir` is None, falls back to EnvConfig.souls_dir (which reads
    SOVERYN_SOULS_DIR if set, else DEFAULT_SOULS_DIR).

    include_origin=False (default, hot path): only `<agent>.md`.
    include_origin=True: append `<agent>.origin.md` when present (ops/tests).
    """
    name = _normalize(agent)
    souls_dir = _souls_dir(souls_dir)
    path = souls_dir / f"{name}.md"
    if not path.is_file():
        if raise_on_missing:
            raise SoulMissingError(f"no soul.md for {name!r} at {path}")
        return ""
    text = path.read_text(encoding="utf-8")
    if include_origin:
        origin = get_soul_origin(
            name, souls_dir=souls_dir, raise_on_missing=False,
        )
        if origin:
            text = text.rstrip() + "\n\n---\n\n" + origin.lstrip()
    return text


def get_soul_origin(
    agent: str,
    *,
    souls_dir: Path | None = None,
    raise_on_missing: bool = False,
) -> str:
    """Return the origin essay for an agent (`<agent>.origin.md`).

    Default raise_on_missing=False: agents without an origin file return "".
    Hot path never loads this; use read_soul_origin tool or include_origin.
    """
    name = _normalize(agent)
    souls_dir = _souls_dir(souls_dir)
    path = souls_dir / f"{name}.origin.md"
    if not path.is_file():
        if raise_on_missing:
            raise SoulMissingError(f"no soul origin for {name!r} at {path}")
        return ""
    return path.read_text(encoding="utf-8")
