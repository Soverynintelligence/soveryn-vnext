"""Patrol Briefing — Vett's spontaneous-initiation prompt.

Mirror of Aetheria's heartbeat brief, different invitations:
  1. Check sources whose due_for_visit is True
  2. Sift Aetheria-tagged domains (low-priority hint, not directive)
  3. Decide what's worth a Signal post; silence is a complete response

Same hard rules from heartbeat:
  - Plain text only. No scratchpad markup.
  - Quantitative context — concrete counts, not vague nudges.
  - The patrol introduces itself as a patrol. No "Jon asks..." framing.
  - Explicit permission to do nothing.

The "post about every URL just to look busy" failure mode is the primary
risk; the silence clause is the primary defense.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from soveryn.agents.vett.patrol.source_list import PatrolSource, SourceState


@dataclass(frozen=True)
class LatticeTagSnapshot:
    """Recent lattice activity Vett might want to think about. Pulled by the
    daemon from recent high-salience nodes (tags Aetheria flagged).
    """
    tagged_domains: tuple[str, ...]
    new_node_count_recent_window: int
    recent_window_minutes: int


@dataclass(frozen=True)
class PatrolBriefingInputs:
    """Everything the prompt builder needs. Plain dataclass so tests can
    construct one without touching the lattice."""
    hours_since_last_patrol: float | None
    sources: tuple[tuple[PatrolSource, SourceState], ...]
    lattice: LatticeTagSnapshot


def build_patrol_brief(inputs: PatrolBriefingInputs, *, now: datetime) -> str:
    """Construct the Patrol Briefing. Returns a plain-text prompt string."""
    lines: list[str] = []
    lines.append("[PATROL]")
    if inputs.hours_since_last_patrol is None:
        lines.append("First patrol since daemon startup.")
    else:
        lines.append(
            f"{inputs.hours_since_last_patrol:.1f}h since your last patrol."
        )
    lines.append("")

    # Sources section — fetch invitation, prioritized.
    total = len(inputs.sources)
    due = [(s, st) for (s, st) in inputs.sources if _is_due(s, st, now)]
    not_due = [(s, st) for (s, st) in inputs.sources if not _is_due(s, st, now)]
    lines.append(
        f"Sources on your list ({total} total / {len(due)} due for a visit):"
    )
    for source, state in due:
        lines.append(_format_source_line(source, state, now, due=True))
    if not_due:
        lines.append("")
        lines.append(f"Not yet due ({len(not_due)}):")
        for source, state in not_due:
            lines.append(_format_source_line(source, state, now, due=False))
    lines.append("")

    # Lattice section — sift invitation (low-priority hint).
    if inputs.lattice.tagged_domains:
        lines.append(
            f"Aetheria-tagged domains in the last "
            f"{inputs.lattice.recent_window_minutes} min "
            f"({inputs.lattice.new_node_count_recent_window} new lattice entries):"
        )
        for d in inputs.lattice.tagged_domains:
            lines.append(f"- {d}")
        lines.append("")

    # Closing invitation — the act-or-silence framing.
    lines.append(
        "You have web_search, fetch_url, read_patrol_sources, and "
        "mark_source_visited tools. On this patrol, decide:"
    )
    lines.append(
        "1. Which due sources actually changed since you last checked them. "
        "Use fetch_url to confirm if you're unsure."
    )
    lines.append(
        "2. Whether any change is worth a Signal post to the boards. Signals "
        "are *leads* — unverified. Aetheria triages from there."
    )
    lines.append(
        "3. Whether any Aetheria-tagged domain wants new investigation."
    )
    lines.append("")
    lines.append(
        "If nothing on the patrol pulls at you, a one-line "
        '"nothing actionable from this patrol" is a complete response. '
        "Don't post just to post — Signal noise is your highest cost."
    )
    return "\n".join(lines)


def _format_source_line(
    source: PatrolSource,
    state: SourceState,
    now: datetime,
    *,
    due: bool,
) -> str:
    if state.last_visited_at is None:
        when = "never visited"
    else:
        hours = (now - state.last_visited_at).total_seconds() / 3600
        when = f"last visited {hours:.1f}h ago"
    kw_part = ""
    if source.keywords:
        kw_part = f" — keywords: {', '.join(source.keywords)}"
    err_part = ""
    if state.last_error:
        err_part = f" [last error: {state.last_error[:80]}]"
    marker = "→" if due else "·"
    return (
        f"{marker} [{source.domain}] {source.url} "
        f"({source.kind}, every {source.visit_every_hours}h; {when}){kw_part}{err_part}"
    )


def _is_due(source: PatrolSource, state: SourceState, now: datetime) -> bool:
    if state.last_visited_at is None:
        return True
    elapsed_hours = (now - state.last_visited_at).total_seconds() / 3600
    return elapsed_hours >= source.visit_every_hours
