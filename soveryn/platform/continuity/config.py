"""Cross-Surface Continuity — config + autonomous-session prefix table.

Locked by Aetheria 2026-06-09. Signal is NOT in the autonomous prefix set
because Signal IS a real conversation rail with Jon — it's exactly what
the engine exists to surface. The autonomous prefixes are sessions where
Aetheria is talking to herself or to automation.
"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_WINDOW_HOURS = 6
DEFAULT_TOKEN_BUDGET = 1500
DEFAULT_PER_SESSION_CAP = 400

AUTONOMOUS_SESSION_PREFIXES: tuple[str, ...] = (
    "[heartbeat]",
    "[patrol]",
    "[webhook]",
    "[dream]",
    "[salience-smoke]",
)


def _parse_bool(raw: str | None, default: bool = True) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"true", "1", "yes", "on"}


def _parse_int(raw: str | None, default: int) -> int:
    if raw is None or raw == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class ContinuityConfig:
    enabled: bool = True
    window_hours: int = DEFAULT_WINDOW_HOURS
    token_budget: int = DEFAULT_TOKEN_BUDGET
    per_session_cap: int = DEFAULT_PER_SESSION_CAP

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "ContinuityConfig":
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_CROSS_SURFACE_ENABLED"), True),
            window_hours=_parse_int(
                env.get("SOVERYN_CROSS_SURFACE_WINDOW_HOURS"), DEFAULT_WINDOW_HOURS
            ),
            token_budget=_parse_int(
                env.get("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET"), DEFAULT_TOKEN_BUDGET
            ),
            per_session_cap=_parse_int(
                env.get("SOVERYN_CROSS_SURFACE_PER_SESSION_CAP"), DEFAULT_PER_SESSION_CAP
            ),
        )

    def session_is_autonomous(self, title: str | None) -> bool:
        if not title:
            return False
        return any(title.startswith(p) for p in AUTONOMOUS_SESSION_PREFIXES)
