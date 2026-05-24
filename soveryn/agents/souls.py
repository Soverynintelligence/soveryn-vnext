"""SOVERYN vNext — per-agent soul.md loader (read-only).

Each active agent has an identity document at
soveryn_memory/souls/<agent>.md. This module reads those files and
nothing else. AgentLoop wiring is a separate commit.

Missing-file behavior:
  - Default: raise SoulMissingError. Tests rely on this.
  - Runtime opt-in to degrade: pass raise_on_missing=False explicitly.

Path traversal: agent names are normalized (lowered, stripped) and
rejected if they contain anything outside [a-z_]. Defense in depth.
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


def get_soul(
    agent: str,
    *,
    souls_dir: Path | None = None,
    raise_on_missing: bool = True,
) -> str:
    """Return the soul.md text for an active agent.

    If `souls_dir` is None, falls back to EnvConfig.souls_dir (which reads
    SOVERYN_SOULS_DIR if set, else DEFAULT_SOULS_DIR).
    """
    name = _normalize(agent)
    if souls_dir is None:
        souls_dir = load_env_config().souls_dir
    path = souls_dir / f"{name}.md"
    if not path.is_file():
        if raise_on_missing:
            raise SoulMissingError(f"no soul.md for {name!r} at {path}")
        return ""
    return path.read_text(encoding="utf-8")
