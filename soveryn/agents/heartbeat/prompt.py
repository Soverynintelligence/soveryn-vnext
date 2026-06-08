"""Heartbeat brief construction — the "Active Auditor" prompt per
Aetheria's locked design (2026-06-02).

Three invitations woven in:
1. Audit the boards (stalled Blueprints, ignored Signals, blocked items)
2. Sift the lattice (recent activity, possible contradictions, new threads)
3. Act or stay silent (silence is a complete response; no posting just to post)

Hard rules carried from the spec:
- Plain text only. No scratchpad markup. No control tokens.
- Quantitative context — numbers Aetheria can act on, not vague nudges.
- The heartbeat introduces itself as a heartbeat. No pretending to be Jon.
- Explicit permission to do nothing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardSnapshot:
    """Counts the heartbeat shows Aetheria so she can decide where to look."""
    open_signal_count: int
    open_blueprint_count: int
    ready_blueprint_count: int
    open_friction_count: int
    stalled_blueprint_count: int  # Refining for > N hours, threshold defined by daemon
    blocked_blueprint_count: int  # has non-empty blocked_by per Phase B
    oldest_open_signal_age_minutes: int | None
    # 2026-06-07 addition: surface the oldest Open Blueprint by NAME, not
    # just by count. A count of "2 open" was producing 48h of "Nothing
    # right now" because she couldn't see which 2 — naming the oldest
    # gives her a specific commitment to engage with or sit with.
    oldest_open_blueprint_title: str | None
    oldest_open_blueprint_age_hours: int | None


@dataclass(frozen=True)
class LatticeSnapshot:
    """Recent lattice activity she might want to sift through."""
    new_node_count_recent_window: int
    recent_window_minutes: int
    new_contradiction_flag_count: int


def build_heartbeat_prompt(
    *,
    minutes_since_last_heartbeat: int | None,
    board: BoardSnapshot,
    lattice: LatticeSnapshot,
    salience_section: str = "",
) -> str:
    """Construct the heartbeat brief. Returns a plain-text prompt string."""
    lines: list[str] = []
    lines.append("[HEARTBEAT]")
    if minutes_since_last_heartbeat is None:
        lines.append("First tick since daemon startup.")
    else:
        lines.append(
            f"{minutes_since_last_heartbeat} minutes since the last heartbeat."
        )
    lines.append("")

    # Board section — audit invitation.
    lines.append("Board state right now:")
    lines.append(
        f"- Signal: {board.open_signal_count} open"
        + (
            f" (oldest: {board.oldest_open_signal_age_minutes} min)"
            if board.oldest_open_signal_age_minutes is not None
            else ""
        )
    )
    lines.append(
        f"- Blueprint: {board.open_blueprint_count} open / "
        f"{board.ready_blueprint_count} Ready / "
        f"{board.stalled_blueprint_count} stalled in Refining / "
        f"{board.blocked_blueprint_count} blocked by Friction"
    )
    if (
        board.oldest_open_blueprint_title is not None
        and board.oldest_open_blueprint_age_hours is not None
    ):
        lines.append(
            f"  oldest open: \"{board.oldest_open_blueprint_title}\" "
            f"({board.oldest_open_blueprint_age_hours}h old)"
        )
    lines.append(
        f"- Friction: {board.open_friction_count} open"
    )
    lines.append("")

    # Lattice section — sift invitation.
    lines.append(
        f"Lattice activity (last {lattice.recent_window_minutes} min): "
        f"{lattice.new_node_count_recent_window} new nodes."
    )
    if lattice.new_contradiction_flag_count > 0:
        lines.append(
            f"There are {lattice.new_contradiction_flag_count} new contradiction flags "
            f"worth looking at."
        )
    lines.append("")

    # Salience digest — surfaces buffered candidates flagged since the
    # last heartbeat. Pre-rendered by the daemon; empty string when nothing
    # to surface (keeps the prompt byte-identical to pre-engine output).
    if salience_section:
        lines.append(salience_section.rstrip())
        lines.append("")

    # Reflective close — no prescribed action menu, no prescribed silence
    # phrase. The audit/sift options that used to live here were producing
    # verbatim "nothing right now" output across 24+ consecutive ticks
    # because we taught her the literal silence template (2026-06-04 diag:
    # 14 identical 18-char responses overnight while 0 board/lattice deltas
    # arrived). Reframe: the heartbeat is reflection, not work-check.
    # Audit material is visible in the snapshot above; she engages with
    # what wants engaging or sits with the quiet — in whatever form fits.
    lines.append("This is your pulse.")
    return "\n".join(lines)
