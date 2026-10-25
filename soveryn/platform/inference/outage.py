"""Same-run probe gate for outage and dispatch-block claims.

A pulse once reported "build brain on 127.0.0.1:8080 is down" and blocked
Forge. That sentence was invented — the live brain is the resolved DeepSeek
profile, and no code had probed :8080. This module is the structural fix:

* a down / blocked claim is only allowed when a ProbeRecord (target,
  timestamp, result) was gathered by code in this same run
* unprobed claims are dropped (or labeled unverified) and never block
* a failing probe is reported with its evidence
* a passing probe clears the outage
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

ProbeResult = str  # "ok" | "fail" | "unknown" | "deferred"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ProbeRecord:
    """One code-gathered probe. Model text is not a substitute."""

    target: str
    timestamp: str
    result: ProbeResult
    name: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_down(self) -> bool:
        return self.result == "fail"


@dataclass(frozen=True)
class OutageVerdict:
    """What may be reported / acted on after the probe gate."""

    reported: tuple[dict[str, Any], ...]
    unverified: tuple[str, ...]
    blocks_dispatch: bool
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "reported": list(self.reported),
            "unverified": list(self.unverified),
            "blocks_dispatch": self.blocks_dispatch,
            "text": self.text,
        }


# Concrete endpoints the model likes to invent (host:port or URL).
_ENDPOINT_RE = re.compile(
    r"(?:https?://)?(?:\d{1,3}(?:\.\d{1,3}){3}|localhost|[\w.-]+):(\d{2,5})",
    re.IGNORECASE,
)
_OUTAGE_WORD_RE = re.compile(
    r"(?i)\b(?:down|offline|unreachable|outage|not responding|"
    r"blocked(?:\s+(?:forge|dispatch|kernel))?)\b"
)
_SERVICE_HINT_RE = re.compile(
    r"(?i)(brain|kernel|forge|service|endpoint|router|llama|"
    r"127\.0\.0\.1|localhost|https?://|:\d{2,5})"
)
_KERNEL_NAME_RE = re.compile(r"(?i)(build\s+brain|\bkernel\b)")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?|\n+")


def probe_from_health(report: Mapping[str, Any], *, now: str | None = None) -> ProbeRecord:
    """Build a ProbeRecord from kernel_brain_health_report() (or a like dict)."""
    probe = report.get("probe") if isinstance(report.get("probe"), dict) else {}
    target = str(
        probe.get("target")
        or report.get("target")
        or report.get("base_url")
        or ""
    ).strip()
    timestamp = str(
        probe.get("timestamp")
        or report.get("probed_at")
        or now
        or _utc_now()
    ).strip()
    result = str(probe.get("result") or report.get("status") or "unknown").strip() or "unknown"
    if result not in {"ok", "fail", "unknown", "deferred"}:
        result = "unknown"
    return ProbeRecord(
        target=target,
        timestamp=timestamp,
        result=result,
        name=str(probe.get("name") or report.get("name") or "kernel_build"),
        detail=str(probe.get("detail") or report.get("detail") or ""),
    )


def official_outages(probes: Sequence[ProbeRecord]) -> tuple[dict[str, Any], ...]:
    """Outage lines gathered from probes — never from model prose."""
    return tuple(p.as_dict() for p in probes if p.is_down)


def should_block_dispatch(probes: Sequence[ProbeRecord]) -> bool:
    """Dispatch is blocked only by a same-run failing probe.

    Unverified outage claims (model prose with no matching probe) are not
    probes and must never set this to True.
    """
    return any(p.is_down for p in probes)


def merge_tick_probes(*groups: Sequence[ProbeRecord] | None) -> tuple[ProbeRecord, ...]:
    """Kernel health + dispatch-ledger failures for one outage-gate call.

    Only these records may report an outage or set ``blocks_dispatch``.
    """
    merged: list[ProbeRecord] = []
    for group in groups:
        if group:
            merged.extend(group)
    return tuple(merged)


def format_outage_report(probes: Sequence[ProbeRecord]) -> str:
    """Human report. Empty when nothing probed-failing this run."""
    downs = official_outages(probes)
    if not downs:
        return ""
    lines = ["## Verified outages (same-run probe records)"]
    for row in downs:
        lines.append(
            f"- {row.get('name') or row['target']}: result={row['result']} "
            f"target={row['target']} timestamp={row['timestamp']}"
            + (f" ({row['detail']})" if row.get("detail") else "")
        )
    return "\n".join(lines) + "\n"


def evaluate_outage_claims(
    text: str,
    probes: Sequence[ProbeRecord] | None = None,
) -> OutageVerdict:
    """Filter model text and decide what may be reported or may block.

    * Invented down/blocked claim, no matching probe → dropped, not blocking
    * Matching fail probe → reported with that probe's evidence, may block
    * Matching ok probe → cleared (not reported as down, not blocking)
    """
    probes = tuple(probes or ())
    reported = official_outages(probes)
    unverified: list[str] = []
    kept: list[str] = []

    for sentence in _sentences(text):
        raw = sentence.strip()
        if not raw:
            kept.append(sentence)
            continue
        if not _looks_like_outage_claim(raw):
            kept.append(sentence)
            continue
        match = _matching_probe(raw, probes)
        if match is None:
            unverified.append(raw)
            continue
        if match.is_down:
            # Keep the sentence; evidence lives on `reported` from the probe.
            kept.append(sentence)
            continue
        # Passing probe clears the invented-or-stale down claim.
        continue

    filtered = _join_kept(kept, text).strip()
    return OutageVerdict(
        reported=reported,
        unverified=tuple(unverified),
        blocks_dispatch=should_block_dispatch(probes),
        text=filtered,
    )


def apply_outage_gate(
    text: str,
    probes: Sequence[ProbeRecord] | None = None,
) -> OutageVerdict:
    """Public alias used by heartbeat / automations."""
    return evaluate_outage_claims(text, probes)


def _looks_like_outage_claim(sentence: str) -> bool:
    if not _OUTAGE_WORD_RE.search(sentence):
        return False
    return bool(_SERVICE_HINT_RE.search(sentence))


def _sentences(text: str) -> list[str]:
    if not text:
        return []
    parts = _SENTENCE_RE.findall(text)
    return parts or [text]


def _join_kept(kept: Iterable[str], original: str) -> str:
    pieces = list(kept)
    if not pieces:
        return ""
    # Preserve simple single-block notes; collapse leftover whitespace.
    joined = "".join(pieces)
    if "\n" in original:
        return re.sub(r"\n{3,}", "\n\n", joined)
    return re.sub(r" {2,}", " ", joined)


def _claim_endpoints(text: str) -> list[str]:
    found: list[str] = []
    for match in _ENDPOINT_RE.finditer(text):
        found.append(match.group(0).lower())
    return found


def _endpoint_in(endpoint: str, target: str) -> bool:
    ep = endpoint.lower().removeprefix("http://").removeprefix("https://")
    tgt = (target or "").lower()
    if ep in tgt:
        return True
    # Compare host:port even when one side has a scheme/path.
    ep_hp = ep.split("/")[0]
    return bool(ep_hp) and ep_hp in tgt


def _matching_probe(claim: str, probes: Sequence[ProbeRecord]) -> ProbeRecord | None:
    endpoints = _claim_endpoints(claim)
    if endpoints:
        for probe in probes:
            if any(_endpoint_in(ep, probe.target) for ep in endpoints):
                return probe
        return None
    if _KERNEL_NAME_RE.search(claim):
        for probe in probes:
            name = (probe.name or "").lower()
            if name in {"kernel_build", "kernel"} or "kernel" in (probe.target or "").lower():
                return probe
    return None
