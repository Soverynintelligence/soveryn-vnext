"""Publisher — posts an approved draft to X, on approval only.

Anti-double-post / anti-silent-drop invariants:
- `store.mark(candidate_tweet_id, "posted")` only happens AFTER x_client
  returns a real posted id, so a failed call can never leave a candidate
  marked "posted" (which would cause a retry to post it again).
- On `XClientError`, the candidate is marked "failed" — it stays
  recoverable, never silently dropped.
- `store.record_posted_id(posted_id)` is called on success so our own post
  is never re-ingested as a fresh candidate later.
"""

from __future__ import annotations

from dataclasses import dataclass

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.drafting import Draft
from soveryn.agents.presence.x_client import XClientError


@dataclass(frozen=True)
class PublishResult:
    """Result of a publish attempt.

    Attributes:
        ok: True if the post succeeded.
        posted_id: The X-assigned tweet id on success, else None.
        error: The XClientError message on failure, else None.
    """
    ok: bool
    posted_id: str | None
    error: str | None


def publish(text: str, draft: Draft, x_client, store: CandidateStore) -> PublishResult:
    """Publish `text` (Jon's approved/edited text) for `draft` via `x_client`.

    Routes to `x_client.reply_tweet(text, draft.in_reply_to)` when
    `draft.in_reply_to` is set, else `x_client.create_tweet(text)`.

    `text` is published exactly as passed in — it is not necessarily
    `draft.text`, since Jon may have edited it during approval.
    """
    try:
        if draft.in_reply_to is not None:
            posted_id = x_client.reply_tweet(text, draft.in_reply_to)
        else:
            posted_id = x_client.create_tweet(text)
    except XClientError as exc:
        store.mark(draft.candidate_tweet_id, "failed")
        return PublishResult(ok=False, posted_id=None, error=str(exc))

    store.record_posted_id(posted_id)
    store.mark(draft.candidate_tweet_id, "posted")
    return PublishResult(ok=True, posted_id=posted_id, error=None)
