from __future__ import annotations
import re
from dataclasses import dataclass

_VALID_MODES = {"deductive", "inductive", "abductive"}
_NODE_RE = re.compile(r"\[node:([^\]]+)\]")

_CONFIDENCE_RANK = {
    "confident": 3,
    "fairly confident": 2,
    "tentative": 1,
    "low confidence": 1,
}


def confidence_rank(phrase: str) -> int:
    return _CONFIDENCE_RANK.get((phrase or "").strip().lower(), 1)

@dataclass(frozen=True)
class Conclusion:
    mode: str
    confidence: str
    content: str
    premises: tuple[str, ...]

def parse_conclusions(raw: str) -> list[Conclusion]:
    out: list[Conclusion] = []
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            continue
        mode, confidence, content, prem_field = parts
        mode = mode.lower()
        premises = tuple(_NODE_RE.findall(prem_field))
        if mode not in _VALID_MODES or not content or not premises:
            continue  # premise-less or malformed → dropped
        # Induction generalizes from REPEATED evidence — a one-instance
        # "pattern" is the over-extraction bug (gate 2026-06-18: a single
        # "watching the news" turn → "Jon is interested in current events").
        # Require >=2 distinct premises for an inductive conclusion. Deductive
        # / abductive single-premise reads are logically valid and kept.
        if mode == "inductive" and len(premises) < 2:
            continue
        out.append(Conclusion(mode=mode, confidence=confidence,
                              content=content, premises=premises))
    return out
