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
    primary = _skills_dir(skills_dir)
    path = primary / name / "_index.md"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    extras: list[str] = []
    try:
        from soveryn.plugins.loader import plugin_skills_dirs

        extra_map = plugin_skills_dirs()
    except Exception:
        extra_map = {}
    extra = extra_map.get(name)
    if extra is not None:
        extra_path = Path(extra)
        if extra_path.name != name:
            extra_path = extra_path / name if extra_path.is_dir() else extra_path
        index = extra_path / "_index.md" if extra_path.is_dir() else extra_path
        if index.is_file() and index.resolve() != path.resolve():
            extras.append(index.read_text(encoding="utf-8"))
    if extras:
        extra_blob = "\n".join(extras)
        if extra_blob and extra_blob not in text:
            text = (text.rstrip() + "\n" + extra_blob) if text else extra_blob
    return text


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
    primary = _skills_dir(skills_dir)
    path = primary / name / f"{skill_name}.md"
    if path.is_file():
        return path.read_text(encoding="utf-8")
    try:
        from soveryn.plugins.loader import plugin_skills_dirs

        extra = plugin_skills_dirs().get(name)
    except Exception:
        extra = None
    if extra is None:
        return ""
    extra_dir = Path(extra)
    if extra_dir.name != name and extra_dir.is_dir():
        extra_dir = extra_dir / name
    alt = extra_dir / f"{skill_name}.md"
    if alt.is_file():
        return alt.read_text(encoding="utf-8")
    return ""
