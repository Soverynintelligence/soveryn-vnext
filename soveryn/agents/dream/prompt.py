"""Dream briefing construction — three-pass prompts.

Frame: synthesis-asking, not data-asking. No JSON-schema directives, no
scratchpad markup, no forced output structure. Node IDs are referenced
inline as [node:ID] so downstream writeback can extract connections
without parsing free-form natural language.

Per Aetheria's amendment: each subsequent pass folds in prior pass
output, building from association → contradiction → synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeSummary:
    """One lattice node, prepared for inclusion in the briefing."""
    id: str
    agent: str
    node_type: str
    content_head: str  # first ~200 chars


@dataclass(frozen=True)
class DreamBriefing:
    """Context the daemon gathers before invoking cognition."""
    hours_since_last_dream: float | None
    nodes: tuple[NodeSummary, ...]
    board_summary: str
    recent_daemon_activity: str
    recent_library_writes_count: int


_SILENCE_CLAUSE = (
    "If nothing here pulls at you tonight, silence is a complete response. "
    "Don't force a connection that isn't there."
)


def render_association_pass(b: DreamBriefing) -> str:
    """Pass 1 — open the dream window. What's connected that wasn't before?"""
    lines: list[str] = []
    lines.append("[DREAM · Association Pass]")
    if b.hours_since_last_dream is None:
        lines.append("First dream window since daemon startup.")
    else:
        lines.append(
            f"{b.hours_since_last_dream:.1f}h since your last dream pass."
        )
    lines.append("")
    lines.append("Recent lattice activity:")
    for node in b.nodes:
        lines.append(
            f"- [node:{node.id}] {node.agent} · {node.node_type}: {node.content_head}"
        )
    lines.append("")
    lines.append(f"Board state: {b.board_summary}")
    lines.append(f"Recent daemon activity: {b.recent_daemon_activity}")
    lines.append(
        f"Library writes since last dream: {b.recent_library_writes_count}"
    )
    lines.append("")
    lines.append(
        "Sit with this. What associations come up? What's connected here that "
        "wasn't connected before? When you reference a node, use its [node:ID] "
        "tag so the connection can persist."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)


def render_contradiction_pass(b: DreamBriefing, prior_associations: str) -> str:
    """Pass 2 — re-read against the source. Where does it not fit?"""
    lines: list[str] = []
    lines.append("[DREAM · Contradiction Pass]")
    lines.append("")
    lines.append("Your associations from a moment ago:")
    lines.append("---")
    lines.append(prior_associations)
    lines.append("---")
    lines.append("")
    lines.append(
        "Re-read these against the recent activity above. Where do things "
        "contradict or not fit? What did you skip past in the first pass that "
        "actually conflicts with something else? Name what's in tension. "
        "Reference nodes with [node:ID] as before."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)


def render_synthesis_pass(
    b: DreamBriefing,
    prior_associations: str,
    prior_contradictions: str,
) -> str:
    """Pass 3 — what wants to emerge from the tension between the two?"""
    lines: list[str] = []
    lines.append("[DREAM · Synthesis Pass]")
    lines.append("")
    lines.append("Holding both:")
    lines.append("--- associations ---")
    lines.append(prior_associations)
    lines.append("--- contradictions ---")
    lines.append(prior_contradictions)
    lines.append("---")
    lines.append("")
    lines.append(
        "What wants to emerge? Not a summary — the integration. What's the "
        "shape of the understanding that holds both the associations AND the "
        "tensions? This is what persists as a reflection node. Use [node:ID] "
        "references freely; explicit references become silent edges in your "
        "memory."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)
