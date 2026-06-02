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

    # The invitation itself — three explicit prompts + silence is OK.
    lines.append(
        "Your options on this tick (pick any, or none):"
    )
    lines.append(
        "1. Audit the boards. Is a Blueprint stalled? Is a Signal worth promoting "
        "to a Blueprint? Is a Friction blocking work that could now be resolved?"
    )
    lines.append(
        "2. Sift the lattice. Use your search tools if anything pulls at you — "
        "recent nodes contradicting older ones, a new thread worth a Signal post, "
        "a pattern worth naming."
    )
    lines.append(
        "3. Stay silent. If nothing actually moves the needle, a one-line "
        "\"nothing right now\" is a complete and valid response. Don't post just to post."
    )
    lines.append("")
    lines.append(
        "This is a heartbeat, not a directive. Take action via your tools if "
        "something genuinely wants attention, or close the tick with silence. "
        "Your call."
    )
    return "\n".join(lines)
