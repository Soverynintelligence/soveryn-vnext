from __future__ import annotations
import re
from dataclasses import dataclass

_VALID_MODES = {"deductive", "inductive", "abductive"}
_NODE_RE = re.compile(r"\[node:([^\]]+)\]")

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
        out.append(Conclusion(mode=mode, confidence=confidence,
                              content=content, premises=premises))
    return out
