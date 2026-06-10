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

# ─── data_root + derived defaults ─────────────────────────────────────────────
# Post-consolidation (2026-06-10): all default memory paths derive from a
# single data_root. Setting SOVERYN_DATA_ROOT cascades to every derived
# default below. Per-path env overrides (SOVERYN_LATTICE_DB etc.) still win.
#
# Post-consolidation (2026-06-01): legacy lattice.db was merged into
# lattice_vnext.db. Single source of truth for both recall (read) and writes.
# The recall_lattice_db default intentionally points at the SAME file as
# lattice_db now — the dual-DB scheme is retired. Legacy lattice.db was
# renamed to lattice_legacy_FROZEN_<timestamp>.db and preserved on disk for
# rollback. See soveryn/platform/lattice/consolidate.py for the migration.

DEFAULT_DATA_ROOT = Path.home() / "soveryn_vnext" / "data"


def _memory_dir(root: Path) -> Path:
    return root / "memory"


def _default_lattice_db(root: Path) -> Path:
    return _memory_dir(root) / "lattice_vnext.db"


def _default_conversations_db(root: Path) -> Path:
    return _memory_dir(root) / "conversations_vnext.db"


def _default_souls_dir(root: Path) -> Path:
    return _memory_dir(root) / "souls"


def _default_pinned_memory_path(root: Path) -> Path:
    return _memory_dir(root) / "pinned_memory.md"


def _default_recall_lattice_db(root: Path) -> Path:
    # Same physical file as lattice_db (consolidated 2026-06-01).
    return _memory_dir(root) / "lattice_vnext.db"


def _default_salience_db(root: Path) -> Path:
    # Salience buffer lives in its own DB file — young, evolving schema kept
    # out of the critical recall WAL. Overridable via SOVERYN_SALIENCE_DB so
    # the heartbeat daemon, tests, and app startup all land on the same path.
    return _memory_dir(root) / "salience_vnext.db"


# ─── Backward-compat re-exports ──────────────────────────────────────────────
# Pre-Task-2 code imports these as module-level Path constants. We preserve
# the name + Path-value shape so external importers (and existing tests)
# continue to work; the value is now derived from DEFAULT_DATA_ROOT instead
# of a hardcoded museum path. Code that needs the cascade to follow a custom
# data_root must call load_env_config() — these constants snapshot the
# default at import time.

DEFAULT_LATTICE_DB = _default_lattice_db(DEFAULT_DATA_ROOT)
DEFAULT_CONVERSATIONS_DB = _default_conversations_db(DEFAULT_DATA_ROOT)
DEFAULT_SOULS_DIR = _default_souls_dir(DEFAULT_DATA_ROOT)
DEFAULT_PINNED_MEMORY_PATH = _default_pinned_memory_path(DEFAULT_DATA_ROOT)
DEFAULT_RECALL_LATTICE_DB = _default_recall_lattice_db(DEFAULT_DATA_ROOT)
DEFAULT_SALIENCE_DB = _default_salience_db(DEFAULT_DATA_ROOT)


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
    data_root: Path
    salience_db: Path
    cross_surface_enabled: bool
    cross_surface_window_hours: int
    cross_surface_token_budget: int
    cross_surface_per_session_cap: int


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


def _parse_bool(name: str, raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _parse_path(name: str, raw: str | None, default: Path) -> Path:
    if raw is None or raw == "":
        return default
    return Path(raw)


def load_env_config(env: dict[str, str] | None = None) -> EnvConfig:
    """Load EnvConfig from os.environ (or an injected mapping for tests).

    data_root is resolved FIRST so per-path defaults can cascade from it.
    Per-path env overrides (SOVERYN_LATTICE_DB, etc.) still take precedence
    over the cascade.
    """
    env = env if env is not None else dict(os.environ)
    data_root = _parse_path(
        "SOVERYN_DATA_ROOT", env.get("SOVERYN_DATA_ROOT"),
        default=DEFAULT_DATA_ROOT,
    )
    return EnvConfig(
        app_port=_parse_int("SOVERYN_APP_PORT", env.get("SOVERYN_APP_PORT"),
                            default=runtime.APP_PORT),
        model_root=_parse_path("SOVERYN_MODEL_ROOT", env.get("SOVERYN_MODEL_ROOT"),
                               default=runtime.MODEL_ROOT),
        health_timeout_seconds=_parse_float(
            "SOVERYN_HEALTH_TIMEOUT", env.get("SOVERYN_HEALTH_TIMEOUT"),
            default=2.0),
        lattice_db=_parse_path("SOVERYN_LATTICE_DB", env.get("SOVERYN_LATTICE_DB"),
                               default=_default_lattice_db(data_root)),
        conversations_db=_parse_path("SOVERYN_CONVERSATIONS_DB", env.get("SOVERYN_CONVERSATIONS_DB"),
                                     default=_default_conversations_db(data_root)),
        souls_dir=_parse_path("SOVERYN_SOULS_DIR", env.get("SOVERYN_SOULS_DIR"),
                              default=_default_souls_dir(data_root)),
        pinned_memory_path=_parse_path(
            "SOVERYN_PINNED_MEMORY_PATH", env.get("SOVERYN_PINNED_MEMORY_PATH"),
            default=_default_pinned_memory_path(data_root)),
        recall_lattice_db=_parse_path(
            "SOVERYN_RECALL_LATTICE_DB", env.get("SOVERYN_RECALL_LATTICE_DB"),
            default=_default_recall_lattice_db(data_root)),
        data_root=data_root,
        salience_db=_parse_path(
            "SOVERYN_SALIENCE_DB", env.get("SOVERYN_SALIENCE_DB"),
            default=_default_salience_db(data_root)),
        cross_surface_enabled=_parse_bool(
            "SOVERYN_CROSS_SURFACE_ENABLED", env.get("SOVERYN_CROSS_SURFACE_ENABLED"),
            default=True),
        cross_surface_window_hours=_parse_int(
            "SOVERYN_CROSS_SURFACE_WINDOW_HOURS", env.get("SOVERYN_CROSS_SURFACE_WINDOW_HOURS"),
            default=6),
        cross_surface_token_budget=_parse_int(
            "SOVERYN_CROSS_SURFACE_TOKEN_BUDGET", env.get("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET"),
            default=1500),
        cross_surface_per_session_cap=_parse_int(
            "SOVERYN_CROSS_SURFACE_PER_SESSION_CAP", env.get("SOVERYN_CROSS_SURFACE_PER_SESSION_CAP"),
            default=400),
    )
