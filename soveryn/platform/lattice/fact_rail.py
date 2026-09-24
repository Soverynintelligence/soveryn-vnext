"""Locked fact rail — cosine cannot bury phones, dates, names, negations."""

from __future__ import annotations

import re

from soveryn.platform.lattice.legacy import Node

CANONICAL_FACT_TAG = "canonical_fact"
FACT_RAIL_LIMIT = 3

_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_DIGITS = re.compile(r"\b\d{3,}\b")
_NEGATION = re.compile(
    r"\b(?:not|never|isn't|is not|don't|do not|doesn't|won't|cannot|can't)\s+([A-Za-z][A-Za-z0-9_-]{2,})\b",
    re.IGNORECASE,
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_+.-]{3,}")


def fact_query_tokens(text: str) -> tuple[str, ...]:
    """Tokens cosine is likely to lose: numbers, contacts, explicit not-X."""
    raw = text or ""
    found: list[str] = []
    seen: set[str] = set()

    def add(piece: str) -> None:
        key = piece.strip().lower()
        if len(key) < 3 or key in seen:
            return
        seen.add(key)
        found.append(key)

    for rx in (_PHONE, _EMAIL, _YEAR, _DIGITS):
        for m in rx.finditer(raw):
            add(re.sub(r"\D+", "", m.group(0)) or m.group(0))
            add(m.group(0))
    for m in _NEGATION.finditer(raw):
        add(m.group(1))
        add("not " + m.group(1))
    # Keep a few content words so "Jon prefers Signal" still hits a fact row.
    for m in _TOKEN.finditer(raw):
        word = m.group(0)
        if word.lower() in _STOP:
            continue
        add(word)
        if len(found) >= 12:
            break
    return tuple(found)


_STOP = frozenset({
    "this", "that", "with", "from", "have", "what", "when", "where",
    "your", "about", "just", "like", "them", "they", "will", "would",
    "could", "should", "there", "their", "been", "were", "then", "than",
})


def merge_fact_rail(
    ranked: tuple[tuple[Node, float], ...],
    facts: tuple[Node, ...],
) -> tuple[tuple[Node, ...], tuple[tuple[Node, float], ...]]:
    """Facts first; drop duplicate ids from the cosine list."""
    fact_ids = {n.id for n in facts}
    rest = tuple((n, s) for n, s in ranked if n.id not in fact_ids)
    return facts, rest
