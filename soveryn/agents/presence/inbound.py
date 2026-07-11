"""Inbound Signal reply -> `PresenceDaemonSurface.resolve_reply` seam.

Correlates a Signal reply from Jon to a pending presence draft by matching
a leading draft-id token in the reply text — the same `draft_id`
`format_signal_message` (soveryn/agents/presence/approval.py) announces as
`Draft <id> (<kind>)`. `handle_inbound_reply` is the single call a live
inbound-Signal source (see the module docstring below for what that is,
and what's NOT yet wired) should make for every message from Jon before
falling back to any other routing.

Status: this seam exists and is unit-tested, but it is NOT connected to a
running inbound path as of Task 11. The only Signal receive loop in this
repo is `soveryn.agents.signal_bridge.daemon.SignalBridgeDaemon` — its own
long-lived process (soveryn-signal-bridge.service) that unconditionally
routes every allowlisted inbound message to Aetheria's /chat. The presence
daemon (soveryn-presence.service, Task 11) is a *separate* process with no
shared memory with the bridge, so `daemon.pending` here can't be reached
from there without either:
  (a) teaching SignalBridgeDaemon to check this module before dispatching
      to /chat (an edit to soveryn/agents/signal_bridge/daemon.py, out of
      this task's file scope), or
  (b) giving the presence daemon its own signal-cli receive loop (risks
      racing the bridge daemon for the same inbound queue on the same
      signal-cli account).
See task-11-report.md for the recommended follow-up.
"""

from __future__ import annotations

from collections.abc import Iterable

from soveryn.agents.presence.daemon import PresenceDaemonSurface


def parse_draft_reply(text: str, pending_ids: Iterable[str]) -> tuple[str, str] | None:
    """Split `text` into (draft_id, reply_text) if it leads with a pending id.

    Signal gives the daemon no quote/reply-to metadata, so correlation is
    done from the message body itself: the reply must begin with the exact
    draft id shown in `format_signal_message` (e.g. "184659... y" or
    "184659...\\nreject: too salesy"), followed by whitespace and the
    actual approve/reject/edit text. Returns None if the first
    whitespace-delimited token isn't one of `pending_ids`.
    """
    stripped = text.strip()
    if not stripped:
        return None
    parts = stripped.split(None, 1)
    draft_id = parts[0]
    if draft_id not in set(pending_ids):
        return None
    remainder = parts[1] if len(parts) > 1 else ""
    return draft_id, remainder


def handle_inbound_reply(daemon: PresenceDaemonSurface, text: str) -> bool:
    """Try to resolve `text` as a reply to one of `daemon`'s pending drafts.

    Returns True if `text` matched a pending draft id and was resolved
    (whatever the outcome — approve/edit/reject); False if it didn't match
    anything, so the caller should route it elsewhere (e.g. to Aetheria
    chat, if this is being called from a shared inbound dispatcher).

    On a publish attempt (approve/edit) that fails, sends Jon an explicit
    Signal failure notice via `daemon.send_fn` — an approved-but-failed
    post would otherwise be silently lost (the known Task 10 gap this
    closes).
    """
    parsed = parse_draft_reply(text, daemon.pending.keys())
    if parsed is None:
        return False

    draft_id, reply_text = parsed
    result = daemon.resolve_reply(draft_id, reply_text)

    if result is not None and not result.ok:
        daemon.send_fn(
            f"Draft {draft_id}: approved post FAILED to publish to X "
            f"({result.error}). It was NOT posted — you may need to "
            f"retry manually."
        )

    return True
