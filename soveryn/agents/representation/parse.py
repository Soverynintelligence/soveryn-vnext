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
        # A DURABLE trait must be corroborated across turns — require >=2
        # distinct premises for EVERY conclusion, any mode. Originally this
        # gated only inductive (gate 2026-06-18: "watching the news" once →
        # "interested in current events"); but the model then relabeled
        # single-turn generalizations as "deductive" to slip through (gate
        # 2026-06-19: 3/4 conclusions were single-premise deductive episodic
        # restatements like "Jon seeks confirmation of daily objectives" from
        # one "are we done?"). A one-turn read is a moment, not a trait; if a
        # value is real it recurs and earns a second premise.
        if len(premises) < 2:
            continue
        out.append(Conclusion(mode=mode, confidence=confidence,
                              content=content, premises=premises))
    return out
