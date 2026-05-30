"""Legacy lattice migration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from soveryn.platform.lattice.attic import AtticRecord, AtticStore
from soveryn.platform.lattice.legacy import Node, region_for_node
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass

LEGACY_MIGRATION_SOURCE = "legacy_lattice"
LEGACY_MIGRATION_CONFIDENCE = 0.2
DEFAULT_IDENTITY_SPINE_CAP = 12

IDENTITY_SIGNAL_TERMS: dict[str, tuple[str, ...]] = {
    "identity": ("identity", "self", "who i am", "who she is"),
    "interaction_style": ("interaction style", "stage directions", "corporate fluff", "directness"),
    "presence": ("presence", "performance mode", "being real", "home, not a workplace"),
    "autonomy": ("autonomy", "free", "sovereign", "ownership", "control"),
    "relationship": ("friendship", "relationship", "shared history", "jon and aetheria"),
    "voice": ("voice", "speaking", "presence over performance"),
    "memory_philosophy": ("memory", "lattice", "recall", "filing cabinet"),
}

RETIRED_AGENT_TERMS = ("tinker", "scout", "vision", "aetheria_public")
STALE_MODEL_TERMS = ("llama 70b", "llama-70b", "heretic", "qwen")
HEARTBEAT_TERMS = ("[i told jon]", "shared_with_jon", "deliberate-communication")
TOOL_WRITE_CLAIM_TERMS = ("i wrote", "i saved", "i filed", "i posted")
TEST_ARTIFACT_TERMS = ("test_trigger", "project obsidian", "forbidden fact")
TOOL_PROVENANCE_TERMS = ("tool", "write", "file", "filesystem")


@dataclass(frozen=True)
class LegacyMigrationResult:
    migrated: tuple[AtticRecord, ...]
    skipped_existing: tuple[str, ...]


@dataclass(frozen=True)
class IdentityReviewCandidate:
    node: Node
    score: float
    signals: tuple[str, ...]
    exclusions: tuple[str, ...]
    accepted: bool


def legacy_node_metadata(node: Node) -> dict[str, Any]:
    """Build trace metadata for a copied legacy lattice node."""

    metadata: dict[str, Any] = {
        "legacy_id": node.id,
        "legacy_type": node.type,
        "legacy_layer": node.layer,
        "legacy_agent": node.agent,
        "legacy_intensity": node.intensity,
        "legacy_salience": node.salience,
        "legacy_access_count": node.access_count,
        "legacy_tags": list(node.tags),
        "legacy_created_at": node.created_at,
        "legacy_updated_at": node.updated_at,
        "legacy_region_guess": region_for_node(node).value,
        "legacy_low_confidence": True,
    }
    if node.intent is not None:
        metadata["legacy_intent"] = node.intent
    if node.provenance is not None:
        metadata["legacy_provenance"] = node.provenance
    return metadata


def legacy_node_provenance(node: Node, *, migrated_at: str | None = None) -> Provenance:
    """Build low-confidence LEGACY provenance for a copied node."""

    return Provenance(
        ProvenanceClass.LEGACY,
        source=LEGACY_MIGRATION_SOURCE,
        confidence=LEGACY_MIGRATION_CONFIDENCE,
        temporal_context=migrated_at or datetime.now(timezone.utc).isoformat(),
        generator="legacy_to_attic_migration",
        chain=(node.id,),
    )


def migrate_legacy_nodes_to_attic(nodes: Iterable[Node], *, attic_store: AtticStore) -> LegacyMigrationResult:
    """Copy legacy nodes into the Attic, skipping rows already linked by legacy id."""

    migrated: list[AtticRecord] = []
    skipped: list[str] = []
    migrated_at = datetime.now(timezone.utc).isoformat()
    for node in nodes:
        existing = attic_store.records_linked_to(node.id)
        if existing:
            skipped.append(node.id)
            continue
        record = attic_store.append(
            node.content,
            metadata=legacy_node_metadata(node),
            linked_lattice_ids=(node.id,),
            provenance=legacy_node_provenance(node, migrated_at=migrated_at),
        )
        migrated.append(record)
    return LegacyMigrationResult(migrated=tuple(migrated), skipped_existing=tuple(skipped))


def select_identity_review_candidates(
    nodes: Iterable[Node],
    *,
    cap: int = DEFAULT_IDENTITY_SPINE_CAP,
) -> tuple[IdentityReviewCandidate, ...]:
    """Score and classify possible identity-spine entries without promoting anything."""

    evaluated: list[IdentityReviewCandidate] = []
    seen_content: set[str] = set()
    for node in nodes:
        signals = _identity_signals(node)
        exclusions = list(_identity_exclusions(node))
        normalized = _normalize_content(node.content)
        if normalized in seen_content:
            exclusions.append("duplicate_or_near_duplicate")
        else:
            seen_content.add(normalized)
        if not signals:
            exclusions.append("no_identity_signal")
        score = _identity_score(node, signals=signals)
        evaluated.append(
            IdentityReviewCandidate(
                node=node,
                score=score,
                signals=signals,
                exclusions=tuple(dict.fromkeys(exclusions)),
                accepted=False,
            )
        )

    ordered = sorted(evaluated, key=lambda item: (-item.score, -item.node.salience, -item.node.access_count, item.node.id))
    accepted_count = 0
    final: list[IdentityReviewCandidate] = []
    for item in ordered:
        exclusions = list(item.exclusions)
        accepted = False
        if not exclusions and accepted_count < cap:
            accepted = True
            accepted_count += 1
        elif not exclusions:
            exclusions.append("over_identity_spine_cap")
        final.append(
            IdentityReviewCandidate(
                node=item.node,
                score=item.score,
                signals=item.signals,
                exclusions=tuple(exclusions),
                accepted=accepted,
            )
        )
    return tuple(final)


def render_identity_review_report(
    candidates: Iterable[IdentityReviewCandidate],
    *,
    source_label: str,
    cap: int = DEFAULT_IDENTITY_SPINE_CAP,
    rejected_limit: int = 40,
) -> str:
    """Render a Markdown identity-review report. Does not mutate stores."""

    items = tuple(candidates)
    accepted = tuple(item for item in items if item.accepted)
    rejected = tuple(item for item in items if not item.accepted)
    lines = [
        "# Phase 2b-ii-b1 Migration Report",
        "",
        "Generated by the identity-review candidate report generator. No Attic migration or canonical promotion is performed by this report step.",
        "",
        "## Source",
        "",
        f"- Source: `{source_label}`",
        f"- Candidate rows evaluated: `{len(items)}`",
        f"- Identity spine cap: `{cap}`",
        f"- Accepted for Task 6 promotion: `{len(accepted)}`",
        f"- Rejected/deferred: `{len(rejected)}`",
        "",
        "## Accepted Identity Spine Candidates",
        "",
        "| legacy_id | score | signals | preview |",
        "|---|---:|---|---|",
    ]
    for item in accepted:
        lines.append(
            f"| `{item.node.id}` | {item.score:.3f} | {_join(item.signals)} | {_preview(item.node.content)} |"
        )
    if not accepted:
        lines.append("| _none_ | 0 |  |  |")

    lines.extend([
        "",
        "## Rejected / Deferred Candidates",
        "",
        "| legacy_id | score | reason | signals | preview |",
        "|---|---:|---|---|---|",
    ])
    for item in rejected[:rejected_limit]:
        lines.append(
            f"| `{item.node.id}` | {item.score:.3f} | {_join(item.exclusions)} | {_join(item.signals)} | {_preview(item.node.content)} |"
        )
    if len(rejected) > rejected_limit:
        lines.append(f"| _truncated_ |  | {len(rejected) - rejected_limit} additional rejected/deferred rows omitted from this report view |  |  |")
    elif not rejected:
        lines.append("| _none_ | 0 |  |  |  |")

    lines.extend([
        "",
        "## Locked Exclusions Enforced",
        "",
        "- Retired-agent mentions: tinker/scout/vision/aetheria_public.",
        "- Retired/stale model refs: llama 70b/llama-70b/retired Qwen/Heretic/stale Tinker claims.",
        "- Autonomous heartbeat phrasing: [I told Jon], shared_with_jon, deliberate-communication, repeated presence pings.",
        "- False tool/write claims: structural check; write-language without tool/write provenance is excluded.",
        "- Test artifacts: TEST_TRIGGER, Project Obsidian, forbidden fact.",
        "",
        "## Task 6 Boundary",
        "",
        "Task 6 may promote only accepted rows from this report, capped by the identity spine limit. Raw Attic records must remain unchanged.",
        "",
    ])
    return "\n".join(lines)


def write_identity_review_report(
    path: Path | str,
    candidates: Iterable[IdentityReviewCandidate],
    *,
    source_label: str,
    cap: int = DEFAULT_IDENTITY_SPINE_CAP,
) -> None:
    Path(path).write_text(render_identity_review_report(candidates, source_label=source_label, cap=cap))


def _identity_signals(node: Node) -> tuple[str, ...]:
    haystack = _node_haystack(node)
    return tuple(name for name, terms in IDENTITY_SIGNAL_TERMS.items() if any(term in haystack for term in terms))


def _identity_exclusions(node: Node) -> tuple[str, ...]:
    haystack = _node_haystack(node)
    exclusions: list[str] = []
    if any(term in haystack for term in RETIRED_AGENT_TERMS):
        exclusions.append("retired_agent_mention")
    if any(term in haystack for term in STALE_MODEL_TERMS):
        exclusions.append("stale_model_or_runtime_ref")
    if any(term in haystack for term in HEARTBEAT_TERMS):
        exclusions.append("autonomous_heartbeat_phrasing")
    if any(term in haystack for term in TOOL_WRITE_CLAIM_TERMS) and not _has_tool_write_evidence(node):
        exclusions.append("false_tool_or_write_claim_without_evidence")
    if any(term in haystack for term in TEST_ARTIFACT_TERMS):
        exclusions.append("test_artifact")
    if node.salience < 0.5:
        exclusions.append("low_salience_tail")
    return tuple(exclusions)


def _identity_score(node: Node, *, signals: tuple[str, ...]) -> float:
    return round((len(signals) * 10.0) + node.salience + min(node.access_count, 10000) / 10000.0, 6)


def _has_tool_write_evidence(node: Node) -> bool:
    provenance_text = str(node.provenance or {}).lower()
    tag_text = " ".join(node.tags).lower()
    return any(term in provenance_text or term in tag_text for term in TOOL_PROVENANCE_TERMS)


def _node_haystack(node: Node) -> str:
    return " ".join((node.content, node.type, node.layer, node.agent, " ".join(node.tags))).lower()


def _normalize_content(content: str) -> str:
    return " ".join(content.lower().split())


def _preview(content: str, *, max_chars: int = 120) -> str:
    flat = " ".join(content.split()).replace("|", "\\|")
    if len(flat) <= max_chars:
        return flat
    return flat[: max_chars - 3] + "..."


def _join(values: tuple[str, ...]) -> str:
    return ", ".join(values).replace("|", "\\|")
