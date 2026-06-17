from __future__ import annotations
from dataclasses import dataclass

DEFAULT_TICK_SECONDS = 900
DEFAULT_TURNS_PER_BRIEFING = 20

def _b(raw, default=True):
    if raw is None or raw == "": return default
    return raw.strip().lower() in {"true","1","yes","on"}
def _i(raw, default):
    return int(raw) if raw not in (None, "") else default

@dataclass(frozen=True)
class RepresentationConfig:
    enabled: bool = True
    tick_interval_seconds: int = DEFAULT_TICK_SECONDS
    turns_per_briefing: int = DEFAULT_TURNS_PER_BRIEFING
    dry_run: bool = True
    subject: str = "jon"
    cognition_url: str = "http://127.0.0.1:8089"
    owner_agent: str = "aetheria"

    @classmethod
    def from_env(cls, env: dict) -> "RepresentationConfig":
        return cls(
            enabled=_b(env.get("SOVERYN_REPR_ENABLED"), True),
            tick_interval_seconds=_i(env.get("SOVERYN_REPR_TICK_SECONDS"), DEFAULT_TICK_SECONDS),
            turns_per_briefing=_i(env.get("SOVERYN_REPR_TURNS"), DEFAULT_TURNS_PER_BRIEFING),
            dry_run=_b(env.get("SOVERYN_REPR_DRY_RUN"), True),
            subject=env.get("SOVERYN_REPR_SUBJECT", "jon"),
            cognition_url=env.get("SOVERYN_REPR_COGNITION_URL", "http://127.0.0.1:8089"),
            owner_agent=env.get("SOVERYN_REPR_OWNER", "aetheria"),
        )
