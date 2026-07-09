"""Aetheria drafting — turns a Candidate into a Draft via an injected draft_fn.

No model calls happen here. `draft_fn` is injected (real Aetheria wiring is a
later task); this module only builds the prompt and defensively parses the
JSON contract `{"post": "...", "based_on": "...", "skip": bool}`.

Provenance is never fabricated: a post with missing `based_on` is surfaced
with the literal marker "(none stated)" rather than silently dropped, so the
downstream Signal approval message can flag it. A malformed (non-JSON, or
missing "post") return is treated as a skip — silence is always the safe
default, never a guessed post.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from soveryn.agents.presence.candidate_store import Candidate

NO_PROVENANCE_STATED = "(none stated)"

_REPLYABLE_KINDS = {"reply", "mention"}


@dataclass(frozen=True)
class Draft:
    """A drafted post awaiting approval.

    Attributes:
        candidate_tweet_id: tweet_id of the Candidate this draft is based on.
        kind: Candidate.kind carried through ("topic", "mention", or "reply").
        text: The post text, in Aetheria's voice.
        based_on: Provenance for the claim; "(none stated)" if she gave none.
        in_reply_to: Candidate.tweet_id when kind is "reply"/"mention", else None.
    """
    candidate_tweet_id: str
    kind: str
    text: str
    based_on: str
    in_reply_to: str | None


def _build_prompt(candidate: Candidate) -> str:
    """Build the prompt instructing Aetheria to draft (or skip) a post."""
    return (
        "You are drafting a post for the @Soveryn_AI X/Twitter presence, in your "
        "own voice.\n\n"
        f"Candidate kind: {candidate.kind}\n"
        f"Author: {candidate.author}\n"
        f"Candidate text: {candidate.text}\n"
        f"URL: {candidate.url}\n\n"
        "Write a substantive, grounded reply in your voice. Do not fabricate "
        "claims or data — if you reference a measurement, result, or fact, name "
        "what it's based on. If there is nothing worth saying, it is fine (and "
        "preferred) to stay silent — set skip to true.\n\n"
        "Respond with ONLY a JSON object of this exact shape, no other text:\n"
        '{"post": "<the post text, or empty string if skipping>", '
        '"based_on": "<what the claim is grounded in, or empty string if none>", '
        '"skip": <true or false>}'
    )


def draft_for_candidate(
    candidate: Candidate,
    draft_fn: Callable[[str], str],
) -> Draft | None:
    """Turn a Candidate into a Draft via the injected draft_fn.

    draft_fn takes the built prompt and returns Aetheria's raw text — no
    model call happens in this function. The raw text is parsed defensively:
    anything that isn't valid JSON with a "post" field is treated as a skip.

    Returns None when:
    - the parsed "skip" field is true, OR
    - the parsed "post" text is empty/missing, OR
    - draft_fn's return value isn't valid JSON with a "post" field.

    Otherwise returns a Draft with based_on set to the literal
    "(none stated)" when Aetheria didn't provide provenance.
    """
    raw = draft_fn(_build_prompt(candidate))

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(parsed, dict) or "post" not in parsed:
        return None

    post = parsed.get("post")
    if not isinstance(post, str) or not post.strip():
        return None

    if parsed.get("skip"):
        return None

    based_on = parsed.get("based_on")
    if not isinstance(based_on, str) or not based_on.strip():
        based_on = NO_PROVENANCE_STATED

    in_reply_to = candidate.tweet_id if candidate.kind in _REPLYABLE_KINDS else None

    return Draft(
        candidate_tweet_id=candidate.tweet_id,
        kind=candidate.kind,
        text=post,
        based_on=based_on,
        in_reply_to=in_reply_to,
    )
