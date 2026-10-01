"""Dream daemon config — env-loaded, frozen.

Loaded once at daemon startup. Mirrors the heartbeat / patrol config pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DreamConfig:
    enabled: bool
    dry_run: bool
    quiet_hours: str                  # "HH:MM-HH:MM", wrap-around supported
    activity_backoff_seconds: int     # defer if Aetheria active recently
    nodes_per_run: int                # cap on context-gathering
    max_internal_iterations: int      # cognition pass limit
    cognition_url: str                # OpenAI-compat chat completions URL
    cognition_timeout_seconds: int    # per-pass HTTP timeout

    @classmethod
    def from_env(cls, env: dict | None = None) -> "DreamConfig":
        env = env if env is not None else os.environ
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_DREAM_ENABLED", "true")),
            # Dry-run defaults TRUE at deploy (spec lock). Flip only after bake.
            dry_run=_parse_bool(env.get("SOVERYN_DREAM_DRY_RUN", "true")),
            quiet_hours=env.get("SOVERYN_DREAM_QUIET_HOURS", "23:00-07:00"),
            activity_backoff_seconds=int(
                env.get("SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS", "1800")
            ),
            nodes_per_run=int(env.get("SOVERYN_DREAM_NODES_PER_RUN", "300")),
            max_internal_iterations=int(
                env.get("SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS", "3")
            ),
            cognition_url=env.get(
                "SOVERYN_DREAM_COGNITION_URL", "http://127.0.0.1:8091"
            ),
            cognition_timeout_seconds=int(
                env.get("SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS", "120")
            ),
        )


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
