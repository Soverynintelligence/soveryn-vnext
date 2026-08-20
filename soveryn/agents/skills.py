"""SOVERYN vNext — per-agent skill loader (disk-first, read-only).

Skills are reusable "how-to" procedures an agent has learned and can
self-correct. They live on disk at:

    data/memory/skills/<agent>/_index.md   (tiny, always in prelude)
    data/memory/skills/<agent>/<name>.md   (full body, on-demand)

The two-tier design keeps the prelude cheap: `_index.md` is injected
every turn; `<name>.md` is loaded on demand via the `recall_skill`
tool.

Missing-file behavior:
  - `get_skill_index`: returns "" if no _index.md (agent has no skills yet).
  - `load_skill`: returns "" if no <name>.md (skill not captured yet).

Path traversal: skill names are normalized (lowered, stripped) and
rejected if they contain anything outside [a-z_0-9-]. Defense in depth.
"""

from __future__ import annotations

import re
from pathlib import Path

from soveryn.config.loader import load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS, RETIRED


class SkillError(Exception):
    """Base class for skill-loader errors."""


class SkillNameError(SkillError):
    """Agent name or skill name is retired, unknown, or path-unsafe."""


_VALID_AGENT = re.compile(r"^[a-z_]+$")
_VALID_SKILL = re.compile(r"^[a-z0-9_-]+$")


def _normalize_agent(agent: str) -> str:
    if not isinstance(agent, str):
        raise SkillNameError(f"agent must be str, got {type(agent).__name__}")
    name = agent.strip().lower()
    if not _VALID_AGENT.fullmatch(name):
        raise SkillNameError(f"agent name {agent!r} contains disallowed characters")
    if name in RETIRED:
        raise SkillNameError(f"agent {name!r} is retired; refusing to load skills")
    if name not in ACTIVE_AGENTS:
        raise SkillNameError(f"agent {name!r} is not in ACTIVE_AGENTS")
    return name


def _normalize_skill(name: str) -> str:
    if not isinstance(name, str):
        raise SkillNameError(f"skill name must be str, got {type(name).__name__}")
    normalized = name.strip().lower()
    if not _VALID_SKILL.fullmatch(normalized):
        raise SkillNameError(f"skill name {name!r} contains disallowed characters")
    return normalized


def _skills_dir(skills_dir: Path | None) -> Path:
    if skills_dir is None:
        return load_env_config().skills_dir
    return skills_dir


def get_skill_index(
    agent: str,
    *,
    skills_dir: Path | None = None,
) -> str:
    """Return the _index.md text for an agent's skills (prelude injection).

    Returns "" if the agent has no skills yet (no directory or no _index.md).
    The index is the tiny always-on layer: one line per skill with a short
    description so the model knows what exists without loading full bodies.
    """
    name = _normalize_agent(agent)
    skills_dir = _skills_dir(skills_dir)
    path = skills_dir / name / "_index.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_skill(
    agent: str,
    skill: str,
    *,
    skills_dir: Path | None = None,
) -> str:
    """Return the full body of a single skill (<name>.md).

    Returns "" if the skill file does not exist yet. The body is the
    detailed "how-to" the model follows when executing the skill.
    """
    name = _normalize_agent(agent)
    skill_name = _normalize_skill(skill)
    skills_dir = _skills_dir(skills_dir)
    path = skills_dir / name / f"{skill_name}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
