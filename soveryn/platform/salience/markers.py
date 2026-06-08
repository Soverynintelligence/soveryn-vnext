"""Marker tables for the Salience Engine.

Weights and category membership locked by Aetheria 2026-06-08. Speaker
mapping is part of the spec — markers are pre-filtered by role so the
detection cost is one regex pass per (category x content), not a
post-hoc filter.

Hard Lock + Salience Signal are Jon's-voice anchors (user only).
Synthesis is Aetheria's-voice landing (assistant only) — keeps her from
"locking" her own opinions via the user-voice markers. Pivot fires on
either side because mid-stream course correction is real for both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkerHit:
    category: str
    marker: str
    weight: int


@dataclass(frozen=True)
class MarkerCategory:
    name: str
    weight: int
    roles: frozenset[str]
    phrases: tuple[str, ...]
    words: tuple[str, ...]


HARD_LOCK = MarkerCategory(
    name="hard_lock",
    weight=4,
    roles=frozenset({"user"}),
    phrases=("the call is", "this is the way"),
    words=("locked", "shipped", "approved", "committed", "decided"),
)

SYNTHESIS = MarkerCategory(
    name="synthesis",
    weight=3,
    roles=frozenset({"assistant"}),
    phrases=(
        "the realization is",
        "the structural insight is",
        "the core of this is",
        "i've landed on",
        "the paradox is",
    ),
    words=(),
)

PIVOT = MarkerCategory(
    name="pivot",
    weight=2,
    roles=frozenset({"user", "assistant"}),
    phrases=(
        "actually no",
        "changed my mind",
        "wait, look at it this way",
        "on second thought",
        "wrong turn",
    ),
    words=(),
)

SALIENCE_SIGNAL = MarkerCategory(
    name="salience_signal",
    weight=3,
    roles=frozenset({"user"}),
    phrases=("this is the part", "pay attention to", "remember that", "good catch"),
    words=("interesting",),
)

MARKER_CATEGORIES: tuple[MarkerCategory, ...] = (
    HARD_LOCK,
    SYNTHESIS,
    PIVOT,
    SALIENCE_SIGNAL,
)


def detect_markers(content: str, *, role: str) -> tuple[MarkerHit, ...]:
    """Return one MarkerHit per (category, marker) that fires in `content`
    given the speaker `role`.

    Iteration order is stable: MARKER_CATEGORIES order, then phrases-then-words
    within each category, in declared order. Same marker text in the same
    category dedupes (locked appearing 3x → one MarkerHit).
    """
    if not content or not content.strip():
        return ()
    haystack = content.lower()
    hits: list[MarkerHit] = []
    seen: set[tuple[str, str]] = set()
    for cat in MARKER_CATEGORIES:
        if role not in cat.roles:
            continue
        for phrase in cat.phrases:
            if phrase in haystack:
                key = (cat.name, phrase)
                if key not in seen:
                    hits.append(MarkerHit(category=cat.name, marker=phrase, weight=cat.weight))
                    seen.add(key)
        for word in cat.words:
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            if pattern.search(content):
                key = (cat.name, word)
                if key not in seen:
                    hits.append(MarkerHit(category=cat.name, marker=word, weight=cat.weight))
                    seen.add(key)
    return tuple(hits)
