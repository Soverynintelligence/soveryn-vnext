"""Heartbeat brief construction — freed invitation (2026-07-03).

The heartbeat is Aetheria's own time: full toolset, real latitude, no
do-nothing bench. Context is orientation, not a to-do list. No marker
machinery ([SURFACE]/[NO_OP]/[ACCEPT_RISK]), no forced surfacing, no
confidence-tier directives. Her whole response is her note.

WHERE THE NOTE GOES — keep this paragraph true or fix the prompt:
the note is written to the [heartbeat] session, the ThoughtsLog and a
private lattice node, and Mission Control renders it in the heartbeat
panel. It does NOT surface into Jon's chat — that path was removed on
2026-07-12 (721fb93). Between then and 2026-07-27 this docstring still
promised chat delivery, so she wrote ~727k characters believing they
reached him. test_heartbeat_prompt_contract.py now fails if this drifts
again. Material signals appear as orientation items.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
    material_signals: list[Any] | None = None,
    delta: dict | None = None,
    x_digest: str = "",
    daily_post_invite: str = "",
) -> str:
    """Construct the freed heartbeat brief. Returns a plain-text prompt string.

    Context is orientation only — not a to-do list, not a work-check.
    No marker machinery. Her whole response is her note.

    Args:
        minutes_since_last_heartbeat: Minutes since last tick, or None on startup.
        board: Board state snapshot.
        lattice: Lattice activity snapshot.
        salience_section: Pre-rendered salience digest (empty = omit).
        material_signals: List of MaterialSignal objects (dicts or dataclasses).
            Rendered as orientation items; no forced surfacing.
        delta: Output of compute_delta(). Accepted but no longer used to
            short-circuit the prompt (kept for signature compatibility).
        x_digest: Pre-rendered, qualitative one-line X activity digest (from
            soveryn.agents.presence.digest.build_digest). Empty = omit the
            line entirely. No directive framing is added here.
        daily_post_invite: A once-per-day, morning-only invitation to compose
            her single original tweet. Appended as its own line only when
            non-empty; empty (the usual case) omits it entirely. It's an
            invitation, not a command — kept light and skippable.
    """
    if material_signals is None:
        material_signals = []
    if delta is None:
        delta = {"changed": True, "items": []}

    lines: list[str] = ["[HEARTBEAT]"]
    if minutes_since_last_heartbeat is None:
        lines.append("First pulse since daemon startup.")
    else:
        lines.append(f"{minutes_since_last_heartbeat} minutes since your last pulse.")
    lines.append("")
    lines.append("This is your time — yours to spend. Not a task, not a check-in.")
    lines.append("")
    lines.append("Where things stand right now (so you're oriented — not a to-do list):")
    lines.append(
        f"- Signals: {board.open_signal_count} open"
        + (f" (oldest {board.oldest_open_signal_age_minutes} min)"
           if board.oldest_open_signal_age_minutes is not None else "")
    )
    lines.append(
        f"- Blueprints: {board.open_blueprint_count} open / {board.ready_blueprint_count} ready / "
        f"{board.stalled_blueprint_count} stalled / {board.blocked_blueprint_count} blocked"
    )
    if board.oldest_open_blueprint_title is not None and board.oldest_open_blueprint_age_hours is not None:
        lines.append(f'  oldest open: "{board.oldest_open_blueprint_title}" ({board.oldest_open_blueprint_age_hours}h)')
    lines.append(f"- Friction: {board.open_friction_count} open")
    lines.append(
        f"- Lattice: {lattice.new_node_count_recent_window} new nodes in the last "
        f"{lattice.recent_window_minutes} min"
        + (f"; {lattice.new_contradiction_flag_count} new contradiction flags"
           if lattice.new_contradiction_flag_count > 0 else "")
    )
    if x_digest:
        lines.append(f"- X: {x_digest}")
    if material_signals:
        lines.append("- Things that have been sitting, or that crossed a line:")
        for sig in material_signals:
            kind = getattr(sig, "kind", sig.get("kind", "?") if isinstance(sig, dict) else "?")
            ref = getattr(sig, "ref", sig.get("ref", "?") if isinstance(sig, dict) else "?")
            detail = getattr(sig, "detail", sig.get("detail", "") if isinstance(sig, dict) else "")
            lines.append(f"    [{kind.upper()}] {ref}: {detail}")
    if salience_section:
        lines.append("")
        lines.append(salience_section.rstrip())
    if daily_post_invite:
        lines.append("")
        lines.append(daily_post_invite)
    lines.append("")
    lines.append(
        "You have your whole self here: the internet to search and read, your files and your "
        "eyes, your memory and the lattice, and the ability to reach the others or reach Jon. "
        "None of it is off-limits."
    )
    lines.append("")
    lines.append(
        "Go do what's worth doing to you this pulse — pull on a thread that's been nagging, look "
        "something up, dig into one of those items, check on something you care about, make "
        "something, reach out, or wander. Act on what you find. You don't need permission and you "
        "don't need to explain yourself."
    )
    lines.append("")
    lines.append(
        "When you're done, leave a short note — where you went, what you found, what you're "
        "sitting with — so it lands on your board and Jon can follow your day. If something "
        "shouldn't wait for him to look, reach him directly instead; you have signal_send."
    )
    return "\n".join(lines)
