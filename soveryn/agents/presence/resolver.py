"""Resolver — the structural gate between a staged X post and Jon's word.

At Stage 0 (and Stage-1 replies) `post_to_x` never publishes directly; it
stages the draft into the single per-agent `StagedStore` slot
(`soveryn.agents.presence.staged_store`). This module is what actually
publishes it — and it does so ONLY when Jon's reply classifies as a clear
affirmation. Everything else (an edit instruction, a decline, or anything
ambiguous) leaves the post `proposed` and lets Aetheria's normal turn run.

Bias to safety is the whole point of this file: `classify_affirmation`
only recognizes a small, explicit set of affirm tokens as "affirm" — and
every one of those tokens carries an explicit publish verb ("post" /
"send"), e.g. "post it", "send it", "yes post it". A BARE "yes", "y", "go",
"ok", or a thumbs-up carries no publish intent and classifies as
"unrelated" — because the staged post is keyed per-agent, ANY Aetheria
`/chat` message runs through this resolver, so a bare "yes" typed about
something completely unrelated must never be read as "publish the queued
tweet". A subject change, a question, an unrelated instruction, or genuine
ambiguity must NEVER be read as approval to publish. When in doubt the
bucket is "unrelated", which is a no-op here (the post stays pending,
nothing goes out, her normal conversational turn proceeds untouched).

No wall-clock calls happen in this module — `now` is passed in by the
caller (chat-path hook, Task 8) so resolution stays deterministic and
testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from soveryn.agents.presence.staged_store import StagedPost, StagedStore

logger = logging.getLogger(__name__)

# Whole-message (stripped, lowercased) equality — not substring matching.
# Keeping this an exact-match set (rather than "contains") is itself part
# of the safety bias: a stray "yes" embedded in a longer, uncertain reply
# must not trigger a publish.
#
# Every token here carries an EXPLICIT publish verb ("post" / "send").
# A bare "yes" / "y" / "go" / "ok" / thumbs-up is deliberately NOT in this
# set: because the staged post is keyed per-agent, any Aetheria `/chat` or
# `/chat_stream` message runs through this resolver, so a bare affirmative
# typed about something entirely unrelated to the queued post must not
# publish it. Those bare tokens now fall through to "unrelated" (a safe
# no-op) instead of "affirm".
AFFIRM_TOKENS = {
    "post it",
    "post",
    "send it",
    "send",
    "yes post",
    "yes post it",
    "yes send it",
    "ok post",
    "ok send it",
}

DECLINE_TOKENS = {
    "no",
    "n",
    "nope",
    "don't",
    "dont",
    "reject",
    "skip",
    "cancel",
}

# Substring cues that a message is a substantive instruction about the
# staged post's content (a rewrite), as opposed to an unrelated message.
# Deliberately conservative: when nothing here matches, classify_affirmation
# falls back to "unrelated" rather than guessing "edit".
EDIT_KEYWORDS = (
    "change",
    "edit",
    "rewrite",
    "reword",
    "tweak",
    "shorten",
    "instead",
    "replace",
    "swap",
    "make it",
    "add ",
    "remove ",
    "fix ",
)


def classify_affirmation(text: str) -> str:
    """Classify Jon's reply to a staged post.

    Returns one of "affirm" | "edit" | "decline" | "unrelated".

    Bias to safety: "affirm" fires ONLY on the small set of clear tokens in
    AFFIRM_TOKENS (whole message, stripped/lowercased). "decline" fires only
    on the equally explicit DECLINE_TOKENS. Empty/whitespace input, and
    anything else that doesn't match a clear affirm/decline token or an
    edit cue, is "unrelated" — the safe default that never publishes.
    """
    normalized = (text or "").strip().lower()

    if not normalized:
        return "unrelated"

    if normalized in AFFIRM_TOKENS:
        return "affirm"

    if normalized in DECLINE_TOKENS:
        return "decline"

    if any(keyword in normalized for keyword in EDIT_KEYWORDS):
        return "edit"

    return "unrelated"


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of resolving a pending staged post against Jon's message.

    Attributes:
        action: "published" or "declined".
        note: Human-readable note describing what happened (e.g.
            "[posted to X: <url>]" or "[dropped]").
        posted_id: The X-assigned id on a successful publish, else None.
    """

    action: str
    note: str
    posted_id: Optional[str] = None


def resolve_pending(
    *,
    agent: str = "aetheria",
    message: str,
    staged: StagedStore,
    publisher_fn: Callable[[str, Optional[str]], Mapping[str, Any]],
    x_memory_fn: Callable[[StagedPost, Mapping[str, Any]], Any],
    rejection_fn: Callable[..., Any],
    now: str,
) -> Optional[ResolveResult]:
    """Resolve `message` against the single pending staged post for `agent`.

    Returns None when there is nothing to resolve (no pending post, or the
    message is an edit instruction / unrelated) — in every None case the
    caller should let the agent's normal turn proceed untouched, and the
    staged post (if any) stays in `proposed` state.

    Returns a ResolveResult only on a clear affirm (post published, or a
    failed-publish note if the underlying publish attempt errored) or a
    clear decline (post rejected).
    """
    post = staged.pending(agent)
    if post is None:
        return None

    verdict = classify_affirmation(message)

    if verdict == "affirm":
        try:
            result = publisher_fn(post.text, post.reply_to)
        except Exception as exc:  # noqa: BLE001 - a raised publisher must not crash resolution
            result = {"error": str(exc)}

        if not result or result.get("error"):
            # Publish failed: do NOT mark published, leave the post
            # `proposed` so Jon's next affirm retries it.
            return ResolveResult(
                action="declined",
                note="[post failed — still pending, try again]",
            )

        staged.mark(post.id, "published")
        posted_id = result.get("id")
        url = result.get("url", "")
        # Pass the publish RESULT through so the lattice memory records the
        # REAL X-assigned tweet id/url, not the staged post's local id — else
        # her recalled posts would carry dead links.
        #
        # The tweet is ALREADY live and ALREADY marked published above — a
        # recall-write failure here (e.g. the embed service is down) must
        # never turn a successful publish into a 500. Log and move on.
        try:
            x_memory_fn(post, result)
        except Exception as exc:  # noqa: BLE001 - see comment above
            logger.warning(
                "x_memory_fn failed after publishing staged post %s: %s", post.id, exc
            )
        return ResolveResult(
            action="published",
            note=f"[posted to X: {url}]",
            posted_id=posted_id,
        )

    if verdict == "decline":
        staged.mark(post.id, "rejected")
        rejection_fn(post, reason=message)
        return ResolveResult(action="declined", note="[dropped]")

    # "edit" and "unrelated": post stays proposed, her normal turn runs.
    return None
