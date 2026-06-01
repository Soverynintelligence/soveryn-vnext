"""SOVERYN vNext — typed env-var config loader.

Reads SOVERYN_-prefixed environment variables into a frozen dataclass.
Unknown env vars in the shell are IGNORED (per Jon's adjustment 6).
Only validates the keys we explicitly know about.

Defaults come from soveryn.config.runtime — this loader exists to allow
per-deployment overrides without editing the source constants.
"""

from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

from soveryn.config import runtime

# ─── Default DB paths ─────────────────────────────────────────────────────────
# Post-consolidation (2026-06-01): legacy lattice.db was merged into
# lattice_vnext.db. Single source of truth for both recall (read) and writes.
# DEFAULT_RECALL_LATTICE_DB intentionally points at the SAME file as
# DEFAULT_LATTICE_DB now — the dual-DB scheme is retired. Legacy lattice.db
# was renamed to lattice_legacy_FROZEN_<timestamp>.db and preserved on disk
# for rollback. See soveryn/platform/lattice/consolidate.py for the migration.

DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")
DEFAULT_CONVERSATIONS_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/conversations_vnext.db")
DEFAULT_SOULS_DIR = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/souls")
DEFAULT_PINNED_MEMORY_PATH = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/pinned_memory.md")
DEFAULT_RECALL_LATTICE_DB = DEFAULT_LATTICE_DB


@dataclass(frozen=True)
class EnvConfig:
    """Runtime overrides loaded from SOVERYN_* environment variables.

    Each field corresponds to exactly one env var. Unknown env vars
    (anything not in this dataclass) are ignored — `os.environ` has lots
    of unrelated keys and we don't own that namespace.
    """
    app_port: int
    model_root: Path
    health_timeout_seconds: float
    lattice_db: Path
    conversations_db: Path
    souls_dir: Path
    pinned_memory_path: Path
    recall_lattice_db: Path


class EnvConfigError(ValueError):
    """Raised when a known SOVERYN_* env var fails to parse."""


def _parse_int(name: str, raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise EnvConfigError(f"{name}={raw!r}: not an integer") from e


def _parse_float(name: str, raw: str | None, default: float) -> float:
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise EnvConfigError(f"{name}={raw!r}: not a float") from e


def _parse_path(name: str, raw: str | None, default: Path) -> Path:
    if raw is None or raw == "":
        return default
    return Path(raw)


def load_env_config(env: dict[str, str] | None = None) -> EnvConfig:
    """Load EnvConfig from os.environ (or an injected mapping for tests)."""
    env = env if env is not None else dict(os.environ)
    return EnvConfig(
        app_port=_parse_int("SOVERYN_APP_PORT", env.get("SOVERYN_APP_PORT"),
                            default=runtime.APP_PORT),
        model_root=_parse_path("SOVERYN_MODEL_ROOT", env.get("SOVERYN_MODEL_ROOT"),
                               default=runtime.MODEL_ROOT),
        health_timeout_seconds=_parse_float(
            "SOVERYN_HEALTH_TIMEOUT", env.get("SOVERYN_HEALTH_TIMEOUT"),
            default=2.0),
        lattice_db=_parse_path("SOVERYN_LATTICE_DB", env.get("SOVERYN_LATTICE_DB"),
                               default=DEFAULT_LATTICE_DB),
        conversations_db=_parse_path("SOVERYN_CONVERSATIONS_DB", env.get("SOVERYN_CONVERSATIONS_DB"),
                                     default=DEFAULT_CONVERSATIONS_DB),
        souls_dir=_parse_path("SOVERYN_SOULS_DIR", env.get("SOVERYN_SOULS_DIR"),
                              default=DEFAULT_SOULS_DIR),
        pinned_memory_path=_parse_path(
            "SOVERYN_PINNED_MEMORY_PATH", env.get("SOVERYN_PINNED_MEMORY_PATH"),
            default=DEFAULT_PINNED_MEMORY_PATH),
        recall_lattice_db=_parse_path(
            "SOVERYN_RECALL_LATTICE_DB", env.get("SOVERYN_RECALL_LATTICE_DB"),
            default=DEFAULT_RECALL_LATTICE_DB),
    )
