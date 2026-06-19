"""Active Focus — the work currently in flight, derived on-read from the
non-archived coordination boards and folded into Aetheria's cross-surface
context. The active-state half of the continuity work (2026-06-19): she carries
awareness of what's actively being worked on across every rail, not just the
recent conversation tail.

Source is the coordination boards (Signal/Blueprint/Friction), NOT intent-marks
— deliberate_share/mark_share are empty in practice; the boards are where the
live work actually lives (verified 2026-06-19). Bare data, never instruction
(feedback_ambient_context_not_instruction). No LLM — pure render over nodes,
derive-on-read at brief assembly (as fresh as a cache, no cache to invalidate).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

BLOCK_HEADER = "[ACTIVE FOCUS]"
BLOCK_FOOTER = "[/ACTIVE FOCUS]"
_HEAD_CHARS = 110
DEFAULT_CAP = 5
_DIRECT_PREFIX = "[direct:"
_DISPATCH_PEERS = ("vett", "scotty")


def _head(content: str) -> str:
    collapsed = " ".join((content or "").split())
    if len(collapsed) <= _HEAD_CHARS:
        return collapsed
    return collapsed[:_HEAD_CHARS] + "…"


def _value(x) -> str:
    return x.value if hasattr(x, "value") else str(x)


def derive_dispatch_states(
    conv_store, *, peers: tuple[str, ...] = _DISPATCH_PEERS
) -> dict[str, str]:
    """Map coord_node_id → a short dispatch-state label, read off the
    `[direct:<coord_id>]` sessions.

    The point: a node owned-by-aetheria-and-Open looks identical whether she's
    never touched the hand-off or already fired a directive that errored before
    replying. Board status hides that — and that blind spot is what produced the
    2026-06-19 "I left it on the counter" confabulation (the Hardware Moat
    directive WAS dispatched; it 504'd, so no reply came back, and the accurate
    "it timed out" decayed into "I never sent it"). A `[direct:<id>]` session
    exists iff a directive was ATTEMPTED, so its mere presence is the truth she
    loses. Turn count tells how far it got: 1 = sent, no reply yet; ≥2 = the
    peer replied. Most-recent session per coord id wins (re-fires supersede).
    """
    states: dict[str, str] = {}
    for peer in peers:
        # list_sessions is recency-ordered (newest first), so the first
        # [direct:] session seen for a coord id is the latest — keep it.
        for sess in conv_store.list_sessions(peer):
            title = sess.title or ""
            if not title.startswith(_DIRECT_PREFIX) or not title.endswith("]"):
                continue
            cid = title[len(_DIRECT_PREFIX):-1]
            if cid in states:
                continue
            replied = len(conv_store.load_history(sess.session_id)) >= 2
            states[cid] = (
                f"sent to {peer}, replied" if replied
                else f"sent to {peer}, awaiting reply"
            )
    return states


def render_active_focus(
    nodes: Iterable,
    *,
    cap: int = DEFAULT_CAP,
    dispatch_states: Mapping[str, str] | None = None,
    self_agent: str | None = None,
) -> str:
    """Render non-archived coordination nodes as the ACTIVE FOCUS block.

    `nodes` are CoordinationNodes from `CoordinationStore.list_nodes()` (already
    archive-excluded, ordered created_at ASC). We show the most-recent `cap`,
    newest first. Empty input → "" (the block simply doesn't appear).

    `dispatch_states` (coord_id → label) adds a per-node communication-truth
    suffix, computed from the VIEWER'S perspective:
      - Aetheria's view: her outbound directives (sent to vett, awaiting/replied)
      - a peer's view: their messages up to the hub (sent to aetheria, received)
    `self_agent` is the viewing agent: a node it OWNS with no recorded state
    reads "not yet dispatched". Nodes owned by others get no suffix — they
    aren't the viewer's to dispatch, so a "not dispatched" line would be noise
    (and was the raw material for the 2026-06-19 confabulation).
    """
    active = list(nodes)[::-1][:cap]
    if not active:
        return ""
    states = dispatch_states or {}
    lines = [BLOCK_HEADER, "Work currently in flight across the boards:"]
    for n in active:
        state = states.get(getattr(n, "id", None))
        if state:
            suffix = f" — {state}"
        elif self_agent and _value(getattr(n, "owner", "")) == self_agent:
            suffix = " — not yet dispatched"
        else:
            suffix = ""
        lines.append(
            f"— [{_value(n.board)} · {_value(n.status)}] {_head(n.content)}{suffix}"
        )
    lines.append(BLOCK_FOOTER)
    return "\n".join(lines)
