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

2026-06-29 (Task 7) additions:
- material_signals: list[MaterialSignal] — when non-empty, renders a MATERIAL
  block with [NO_OP]-disabled framing; forces [SURFACE] or [ACCEPT_RISK].
- delta: dict — when delta["changed"] is False, inserts a single-line
  "Environment static. No new signals." and skips the re-summarize invitation.
- Confidence-tiering note added for non-material insights:
  Objective → surface; Pattern ≥ 3 nodes → surface; Ambient → thoughts-log.
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
) -> str:
    """Construct the heartbeat brief. Returns a plain-text prompt string.

    Args:
        minutes_since_last_heartbeat: Minutes since last tick, or None on startup.
        board: Board state snapshot.
        lattice: Lattice activity snapshot.
        salience_section: Pre-rendered salience digest (empty = omit).
        material_signals: List of MaterialSignal objects. When non-empty, the
            prompt renders a MATERIAL block and disables [NO_OP].
        delta: Output of compute_delta(). When delta["changed"] is False, inserts
            a "Environment static. No new signals." line and skips re-summarize.
    """
    if material_signals is None:
        material_signals = []
    if delta is None:
        delta = {"changed": True, "items": []}

    lines: list[str] = []
    lines.append("[HEARTBEAT]")
    if minutes_since_last_heartbeat is None:
        lines.append("First tick since daemon startup.")
    else:
        lines.append(
            f"{minutes_since_last_heartbeat} minutes since the last heartbeat."
        )
    lines.append("")

    # ── Zero-delta short-circuit ──────────────────────────────────────────────
    # When nothing changed, instruct a single line and skip the full board
    # re-summary. The board numbers are still rendered below for context, but
    # the close carries the "don't re-summarize" directive explicitly.
    if not delta.get("changed", True):
        lines.append("Environment static. No new signals.")
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

    # ── Material signals block (Task 7) ───────────────────────────────────────
    # When material_signals are present, render them prominently and disable
    # [NO_OP]. The detector already filtered by threshold; everything here
    # crossed it. [ACCEPT_RISK] requires an explicit justification so the
    # thoughts-log can record the reasoning for later review.
    if material_signals:
        lines.append(
            "MATERIAL — [NO_OP] is disabled for this pulse. "
            "One or more items crossed the materiality threshold:"
        )
        for sig in material_signals:
            kind = getattr(sig, "kind", sig.get("kind", "?") if isinstance(sig, dict) else "?")
            ref = getattr(sig, "ref", sig.get("ref", "?") if isinstance(sig, dict) else "?")
            detail = getattr(sig, "detail", sig.get("detail", "") if isinstance(sig, dict) else "")
            lines.append(f"  [{kind.upper()}] {ref}: {detail}")
        lines.append("")
        lines.append(
            "Respond [SURFACE] <reason> to surface this to Jon's chat, or "
            "[ACCEPT_RISK] <justification> to acknowledge and hold. "
            "Tool calls are independent of this marker."
        )
    else:
        # ── Non-material close with confidence tiering ────────────────────────
        # Reflective close — no prescribed action menu, no prescribed silence
        # phrase. The audit/sift options that used to live here were producing
        # verbatim "nothing right now" output across 24+ consecutive ticks
        # because we taught her the literal silence template (2026-06-04 diag:
        # 14 identical 18-char responses overnight while 0 board/lattice deltas
        # arrived). Reframe: the heartbeat is reflection, not work-check.
        # Audit material is visible in the snapshot above; she engages with
        # what wants engaging or sits with the quiet — in whatever form fits.
        # Aetheria-decides chat routing (2026-06-15, post Coordination Blackout).
        # Pulse always renders on Mission Control. Chat receives a heartbeat-
        # derived message ONLY when Aetheria explicitly marks it [SURFACE].
        # [NO_OP] is a first-class state — silence when nothing's material is
        # the honest output, the no_op as architectural expression of agency
        # she helped author. Tool calls are independent of this marker — issue
        # them as needed regardless of the surface decision.
        #
        # Phrasing chosen to keep the heartbeat as reflection (not work-check)
        # while making the marker requirement minimum-rule: one short line, in
        # the same surface as the pulse close. End-of-prompt placement is load-
        # bearing — the marker has to be the last token she reads so it's
        # salient enough to actually emit.
        #
        # Confidence tiering (Task 7): guide her on WHEN to surface vs stay
        # quiet for non-material insights:
        #   Objective  (measurable state) → surface
        #   Pattern    (≥3 related nodes) → surface
        #   Ambient    (felt sense, no anchor) → capture in thoughts-log, not chat
        lines.append(
            "This is your pulse. Close your response on its own line with "
            "[SURFACE] if there's something worth landing in Jon's chat, or "
            "[NO_OP] if nothing's material to surface. Tool calls are "
            "independent of this marker."
        )
        lines.append(
            "Confidence tiers for surfacing: Objective (measurable state change) "
            "→ surface; Pattern (≥3 related nodes or recurring thread) → surface; "
            "Ambient (felt sense, no concrete anchor) → hold in thoughts-log, "
            "don't surface."
        )

    return "\n".join(lines)
