"""Compose a plain-English greeting from session counts + lattice writes.

No LLM call — pure templating over typed input. Used by the command center
greeting block. Inputs are passed by the route layer; this module knows
nothing about Flask or SQLite.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class GreetingInputs:
    now: datetime
    recent_writes_by_agent: dict[str, int] = field(default_factory=dict)
    recent_session_count: int = 0


@dataclass(frozen=True)
class Greeting:
    heading: str
    body: str


def _time_of_day(hour: int) -> str:
    if hour < 5:  return "Late, Jon."
    if hour < 12: return "Morning, Jon."
    if hour < 17: return "Afternoon, Jon."
    if hour < 22: return "Evening, Jon."
    return "Late, Jon."


def _writes_phrase(writes_by_agent: dict[str, int]) -> str:
    """e.g. 'Aetheria wrote 3 notes. Vett wrote 1 note.' or '' if empty."""
    parts: list[str] = []
    for agent, n in writes_by_agent.items():
        if n <= 0:
            continue
        noun = "note" if n == 1 else "notes"
        parts.append(f"{agent.capitalize()} wrote {n} {noun}.")
    return " ".join(parts)


def _sessions_phrase(n: int) -> str:
    if n <= 0:
        return ""
    return f"{n} session{'s' if n != 1 else ''} active in the last day."


def compose_greeting(inputs: GreetingInputs) -> Greeting:
    heading = _time_of_day(inputs.now.hour)

    writes = _writes_phrase(inputs.recent_writes_by_agent)
    sessions = _sessions_phrase(inputs.recent_session_count)

    parts = [p for p in (writes, sessions) if p]
    if not parts:
        body = "It's been quiet since you were last here."
    else:
        body = " ".join(parts)

    return Greeting(heading=heading, body=body)
