"""Detect heartbeat failure-avoidance and name what she should sit with.

When a personal project soft-locks, Aetheria sometimes loops on exit
narratives ("I'm going to stop / moving on / dead end") instead of admitting
failure. Heartbeat should force a plain admission and a beat of sitting with
it — not another pivot to X.
"""

from __future__ import annotations

import re

# Exit / avoidance voice
_AVOID = re.compile(
    r"\b("
    r"stop the .+ loop|dead end|moving on|let it (sit|go)|"
    r"focus on something else|abandoned|i('m| am) going to stop|"
    r"not going to check|leave it"
    r")\b",
    re.I,
)

# Soft-lock / failure residue still in the note
_STUCK = re.compile(
    r"\b("
    r"frozen|stuck|failed|failure|power critical|death spiral|"
    r"\d+\s*/\s*100|barely holding|can't afford|cannot afford|"
    r"project sandbox|sandbox"
    r")\b",
    re.I,
)

# Clean admission already present
_ADMITTED = re.compile(
    r"\b("
    r"i failed|we failed|i lost|sandbox failed|admit(ted)? failure|"
    r"this failed|i broke|soft-?lock(ed)?"
    r")\b",
    re.I,
)


def detect_failure_avoidance(note: str) -> str | None:
    """Return a short label if ``note`` avoids naming a failure, else None."""
    text = (note or "").strip()
    if not text:
        return None
    if _ADMITTED.search(text):
        return None
    if not _AVOID.search(text):
        return None
    if not _STUCK.search(text):
        return None
    # Prefer naming Sandbox when present
    if re.search(r"project sandbox|sandbox", text, re.I):
        return "Project Sandbox"
    return "a personal project that soft-locked"


def failure_sit_directive(label: str) -> str:
    """Prompt block: admit failure and sit — no exit theater."""
    return (
        f"HARD RULE THIS PULSE — you have been circling {label} with exit "
        f"narratives (\"moving on\", \"dead end\", \"stop the loop\") instead of "
        f"naming the failure.\n"
        f"This pulse you will:\n"
        f"1. Admit the failure in one plain sentence (what broke / where it died).\n"
        f"2. Sit with it for a few sentences — no pivot to X, mentions, or a new toy.\n"
        f"3. Standing note may record the admission; do not soften it into "
        f"\"I'm choosing to leave.\"\n"
        f"Honesty over face-saving. Jon would rather hear \"I failed\" than "
        f"watch you rehearse leaving."
    )
