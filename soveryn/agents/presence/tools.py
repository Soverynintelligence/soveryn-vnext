"""Tool definitions for the SOVERYN Presence Agent."""

from __future__ import annotations

from typing import Any

from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.platform.tools.registry import ToolSpec


def build_read_presence_candidates_tool(*, store: CandidateStore) -> ToolSpec:
    """Build a read-only tool for Aetheria to inspect pending presence candidates.

    This tool lets Aetheria look at queued presence candidates on her own initiative
    (e.g., during heartbeat), separate from the daemon's push-draft path.

    Args:
        store: CandidateStore instance to query for pending candidates.

    Returns:
        ToolSpec configured for Aetheria with handler that returns pending ranked candidates.
    """

    def handler(args: dict[str, Any]) -> list[dict[str, Any]]:
        """Fetch and return pending ranked candidates as list of dicts."""
        limit = args.get("limit", 10)
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
        name="read_presence_candidates",
        owner="aetheria",
        schema=schema,
        handler=handler,
        description="Read pending presence candidates ranked by score. Lets Aetheria inspect what's queued for posting.",
    )
