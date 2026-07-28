"""Aetheria's X (Twitter) tools: read_x + trust-gated post_to_x.

`read_x` is a plain read of the isolated feed worker's candidate queue —
adapted from the committed `build_read_presence_candidates_tool`
(`soveryn/agents/presence/tools.py`), just renamed to the public `read_x`
name Aetheria's loop exposes.

`post_to_x` is the gate: whether a proposed post publishes immediately or
waits for Jon depends on the runtime trust stage (`soveryn.agents.presence
.trust.read_trust_stage`), read FRESH on every call so a panic-to-0 takes
effect on her very next turn, no redeploy needed.

  - Stage 0 (safest): every post — original or reply — is staged into the
    single per-agent `StagedStore` slot and waits for Jon's affirmation in
    chat. `publisher_fn` is never called at this stage.
  - Stage 1 (replies gated): a reply (`reply_to` set) still stages; an
    original post (no `reply_to`) publishes immediately.
  - Stage 2 (autonomous): everything publishes immediately.

The handler receives ONLY the validated args dict (no session_id) per the
platform tool registry's contract — staging is agent-scoped, not
session-scoped, which is exactly what lets Jon's approval (landing in his
primary chat thread) resolve a post Aetheria proposed during a heartbeat
wake (a different session entirely).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.staged_store import StagedBusyError, StagedStore
from soveryn.agents.presence.trust import read_trust_stage
from soveryn.platform.tools.registry import ToolSpec

logger = logging.getLogger(__name__)

PublisherFn = Callable[..., Any]
NowFn = Callable[[], str]
XMemoryFn = Callable[[str, "str | None", dict[str, Any]], Any]

DEFAULT_TTL_HOURS = 12.0


def _noop_x_memory_fn(text: str, reply_to: "str | None", result: dict[str, Any]) -> None:
    """Default no-op x_memory_fn — callers that don't care about lattice
    recall (e.g. most existing tests) don't have to wire one."""
    return None

STAGED_MESSAGE = (
    "Staged — it will NOT post until Jon replies 'post it' (or 'send it'). "
    "Tell Jon what you'd like to post to @Soveryn_AI, show him the text, "
    "and ask for his go-ahead."
)
BUSY_MESSAGE = (
    "You already have a post waiting on Jon; resolve that first — remind "
    "him it needs him to reply 'post it' (or 'send it') before it goes out."
)


def build_read_x_tool(*, owner_agent: str = "aetheria", store: CandidateStore) -> ToolSpec:
    """Build the read-only `read_x` tool over the isolated feed's candidate queue.

    Handler returns the ranked pending feed as plain dicts — real data from
    `store.pending_ranked`, or an honest empty list when nothing is queued.
    Never fabricates candidates.
    """

    def handler(args: Mapping[str, Any]) -> list[dict[str, Any]]:
        limit = args.get("limit") or 10
        candidates = store.pending_ranked(limit)
        return [
            {
                "tweet_id": c.tweet_id,
                "author": c.author,
                "text": c.text,
                "url": c.url,
                "kind": c.kind,
                "score": c.score,
                "status": c.status,
                "created_at": c.created_at,
            }
            for c in candidates
        ]

    schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of candidates to return (default 10)",
                "minimum": 1,
            }
        },
        "additionalProperties": False,
    }

    return ToolSpec(
        name="read_x",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description="Read the pending X feed (mentions + niche candidates), ranked by score.",
    )


def build_post_to_x_tool(
    *,
    owner_agent: str = "aetheria",
    staged: StagedStore,
    publisher_fn: PublisherFn,
    trust_path: Path,
    now_fn: NowFn,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    x_memory_fn: XMemoryFn = _noop_x_memory_fn,
    active_context=None,
) -> ToolSpec:
    """Build the trust-gated `post_to_x` tool.

    The trust stage is re-read from `trust_path` on every invocation (never
    cached), so a Stage-0 panic mid-session takes effect starting with the
    very next call — no redeploy, no stale in-memory gate.

    Every call first expires any stale `proposed` staged post older than
    `ttl_hours` (default 12h) BEFORE checking busy/stages. Without this, a
    staged post Jon never answers would permanently occupy the single
    per-agent slot and lock out all future posts.

    `x_memory_fn(text, reply_to, result)` is called after a SUCCESSFUL
    autonomous publish (Stage 1 original / Stage 2) so that post is written
    into the lattice and stays recallable — the resolver's chat-path
    approval flow (a DIFFERENT injection point, different signature) writes
    its own lattice node separately. A failure in `x_memory_fn` is logged
    and swallowed — the tweet is already live; a recall-write failure must
    never turn a successful publish into a tool error.
    """

    def _stage_it(text: str, reply_to: str | None) -> dict[str, Any]:
        try:
            staged.stage(agent=owner_agent, text=text, reply_to=reply_to, now=now_fn())
        except StagedBusyError:
            return {"status": "busy", "message": BUSY_MESSAGE}
        # Give the staged post a READ path. Until 2026-07-28 it had none: no
        # route listed staged posts, no tool let her check for one, and the
        # audit tool did not cover the store. Five consecutive daily posts
        # expired unseen (07-22 → 07-27) while she correctly believed she had
        # written them. Same defect as the invisible delegations — an action
        # with no way back to the actor.
        if active_context is not None:
            try:
                active_context.record_action(
                    rail="heartbeat", action="x_post_staged", detail=text,
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    "active-context write failed; post is still staged"
                )
        return {"status": "staged", "message": STAGED_MESSAGE}

    def _publish_it(text: str, reply_to: str | None) -> dict[str, Any]:
        try:
            result = publisher_fn(text, reply_to=reply_to)
        except Exception as exc:  # noqa: BLE001 - report, never crash the loop
            return {
                "status": "error",
                "message": f"Posting failed: {exc}",
            }
        if isinstance(result, dict) and result.get("id") and not result.get("error"):
            try:
                x_memory_fn(text, reply_to, result)
            except Exception as exc:  # noqa: BLE001 - the tweet is already live;
                # a broken recall write must not turn success into an error.
                logger.warning("x_memory_fn failed after successful publish: %s", exc)
        return {
            "status": "posted",
            "message": "Posted to X.",
            "result": result,
        }

    def handler(args: Mapping[str, Any]) -> dict[str, Any]:
        text = args["text"]
        reply_to = args.get("reply_to")

        # Expire any stale proposed post FIRST, before busy/stage checks —
        # a never-answered staged post must not permanently occupy the
        # single per-agent slot (Finding 1).
        staged.expire_stale(now_fn(), ttl_hours)

        stage = read_trust_stage(trust_path)

        if stage == 0:
            return _stage_it(text, reply_to)
        if stage == 1:
            if reply_to is not None:
                return _stage_it(text, reply_to)
            return _publish_it(text, reply_to)
        # Stage 2: fully autonomous.
        return _publish_it(text, reply_to)

    schema = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The post text.",
            },
            "reply_to": {
                "type": "string",
                "description": "Tweet id this replies to (omit for an original post).",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="post_to_x",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Propose or publish an X post. Gated by the runtime trust dial: "
            "at low trust it stages for Jon's approval instead of posting."
        ),
    )
