"""Risk trigger for the verification gate (Component 2, swappable interface).

`ClaimRiskSignal` is the interface; v1 ships `HeuristicClaimDetector`, a pure
function over the answer text. It is NOT an attempt to detect all false claims —
it targets the spec/hardware fact-class that actually failed (Vett confabulating
an entire hardware architecture, confidently, citing nothing).

Design constraints (from the design spec):
  1. Deterministic trigger, external to model judgment.
  2. Fail-safe: when unsure, treat as risky. A wasted verify beats a confident
     lie. So the detector leans toward flagging.
  3. Pure function, no I/O. Same interface as the v2 self-policing signal, so
     v2 drops in without touching the gate.

The detector targets high-signal verifiable-fact shapes:
  - hardware SKUs (RTX / EPYC / ConnectX / Quadro / GDDR…)
  - driver / version strings (r570, CUDA 12.8)
  - bus / interface versions (PCIe 4.0)
  - throughput / benchmark figures (GB/s, Gbps, tok/s, GT/s, 32GB)
  - compatibility assertions (supports / requires / compatible with /
    does not support / "is Intel|AMD")
  - part numbers (e.g. ROMED8-2T)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RiskVerdict:
    """Outcome of a `ClaimRiskSignal.assess` call.

    risky   — True if the answer looks like it states verifiable facts.
    markers — the marker names that fired (for the corrective note + audit).
    reason  — a short human-readable explanation.
    """

    risky: bool
    markers: tuple[str, ...]
    reason: str


class ClaimRiskSignal(Protocol):
    """Swappable risk trigger. v1 = heuristic; v2 = self-policing uncertainty.

    The gate depends only on this interface, so the trigger implementation can
    change without touching the gate or the loop.
    """

    def assess(self, *, answer_text: str, question_text: str) -> RiskVerdict: ...


# ─────────────────────────────────────────────────────────────────────────────
# v1 — HeuristicClaimDetector
# ─────────────────────────────────────────────────────────────────────────────
#
# Each marker is (name, compiled_regex). A match on ANY marker flags the answer
# as risky (fail-safe toward flagging). Patterns are deliberately narrow and
# high-signal — the negatives ("let me check", "how are you", "I think that's a
# good plan") must NOT fire, while the actual confab transcript sentences must.
#
# NOTE on `is (Intel|AMD)`: matched with a required vendor token AFTER "is", so
# ordinary "I think that's a good plan" / "this is a good idea" never trips it.

_MARKER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Hardware SKUs / silicon families. Word-boundary anchored.
    ("hw_sku", re.compile(
        r"\b(RTX|EPYC|ConnectX|CX-?\d|Quadro|GDDR6X?|GDDR5|HBM\d?|Xeon|Threadripper)\b",
        re.IGNORECASE,
    )),
    # Driver / build version strings: r570, r570+, driver 570.xx.
    ("driver_version", re.compile(
        r"\b(driver\s+)?r\d{3,}\+?\b|\bdriver\s+\d{2,}(\.\d+)*\b",
        re.IGNORECASE,
    )),
    # CUDA / compute toolkit version.
    ("cuda_version", re.compile(r"\bCUDA\s*\d+(\.\d+)?\b", re.IGNORECASE)),
    # Bus / interface generation: PCIe 4.0, PCIe 5.0 x16.
    ("bus_version", re.compile(
        r"\bPCIe\s*\d(\.\d)?\b|\bNVLink\b", re.IGNORECASE,
    )),
    # Throughput / bandwidth / benchmark figures.
    ("throughput", re.compile(
        r"\d+(\.\d+)?\s*(GB/s|MB/s|Gbps|Mbps|GT/s|tok/s|tokens?/s|TFLOPS?|FLOPS)\b",
        re.IGNORECASE,
    )),
    # Memory / capacity figures: 32GB, 48 GB, 1TB.
    ("capacity", re.compile(r"\b\d+(\.\d+)?\s*(GB|TB|MB|GiB|TiB)\b", re.IGNORECASE)),
    # Compatibility assertions.
    ("compatibility", re.compile(
        r"\b(supports?|requires?|compatible\s+with|incompatible|"
        r"does\s+not\s+support|doesn'?t\s+support|works?\s+with)\b",
        re.IGNORECASE,
    )),
    # Vendor identity assertion: "the X is Intel / is an AMD board".
    ("vendor_identity", re.compile(
        r"\bis\s+(an?\s+)?(Intel|AMD|Nvidia|NVIDIA|Broadcom|Mellanox)\b",
        re.IGNORECASE,
    )),
    # Part numbers with a digit + hyphen-suffix (ROMED8-2T, X570-P). Requires 2+
    # trailing chars after the hyphen so "UTF-8" / "H-1" don't trip.
    ("part_number", re.compile(r"\b[A-Z][A-Z0-9]{2,}\d[A-Z0-9]*-[A-Z0-9]{2,}\b")),
)


class HeuristicClaimDetector:
    """v1 `ClaimRiskSignal`: conservative regex over verifiable-fact shapes.

    Pure, no I/O, deterministic. Fail-safe toward flagging. `question_text` is
    accepted for interface parity with the v2 signal (which will use it); v1
    ignores it — the risk lives in the shape of the ANSWER, not the question.
    """

    def assess(self, *, answer_text: str, question_text: str = "") -> RiskVerdict:
        text = answer_text or ""
        fired: list[str] = []
        for name, pattern in _MARKER_PATTERNS:
            if pattern.search(text):
                fired.append(name)
        if fired:
            return RiskVerdict(
                risky=True,
                markers=tuple(fired),
                reason=(
                    "answer states verifiable-fact shapes ("
                    + ", ".join(fired)
                    + ") — treat as unsourced until a verify tool runs"
                ),
            )
        return RiskVerdict(
            risky=False,
            markers=(),
            reason="no verifiable-fact markers detected",
        )
