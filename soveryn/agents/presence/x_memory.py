"""x_memory — published-only lattice writes for Aetheria's X presence.

Two separate stores, deliberately kept apart:

- `write_x_post_node` writes a lattice `x_post` node for every PUBLISHED
  post, so her account compounds and she remembers what she's said. The
  node MUST be written WITH an `embedding` — a node stored without one is
  keyword-findable but does NOT surface in her per-turn
  `find_nodes_by_embedding` recall (`soveryn/platform/lattice/legacy.py`).
  Omitting the embedding here would silently defeat the entire point of
  this module: she'd post things she can never actually recall.

- `log_rejection` appends a rejected draft + Jon's reason to a small
  JSONL signal file. This is intentionally NOT a lattice write — a
  rejected draft is a tuning signal, not part of her recallable public
  voice, and must never become surfaceable as something she "said".

No wall-clock calls happen in this module — `now` is passed in by the
caller so both writes stay deterministic and testable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional, Sequence


def write_x_post_node(
    *,
    lattice_store,
    embed_fn: Callable[[str], Sequence[float]],
    agent: str = "aetheria",
    text: str,
    source_tweet: Optional[str],
    edited_by_jon: bool,
    posted_id: str,
    now: str,
) -> str:
    """Write a lattice `x_post` node for a PUBLISHED post, with an embedding.

    Args:
        lattice_store: A `LatticeStore`-like object exposing `write_node`
            (`soveryn/platform/lattice/legacy.py:462`).
        embed_fn: Embeds `text` into a vector; the SAME embed function
            Aetheria's loop uses, so this node is recallable alongside
            everything else she's ever said.
        agent: The agent whose voice this is (default "aetheria").
        text: The published post text.
        source_tweet: The tweet id this replied to, or None for an
            original post.
        edited_by_jon: Whether Jon edited the draft before it went out.
        posted_id: The X-assigned id of the published post.
        now: ISO timestamp of the publish (caller-supplied; no wall clock
            here).

    Returns:
        The new lattice node id.
    """
    return lattice_store.write_node(
        agent,
        text,
        node_type="x_post",
        tags=("x", "post"),
        embedding=embed_fn(text),
        provenance={
            "source_tweet": source_tweet,
            "posted_id": posted_id,
            "url": f"https://x.com/i/web/status/{posted_id}",
            "edited_by_jon": edited_by_jon,
            "posted_at": now,
        },
    )


def log_rejection(
    *,
    signal_path: Path,
    text: str,
    reason: str,
    now: str,
) -> None:
    """Append a rejected draft + Jon's reason to a JSONL coaching-signal file.

    Deliberately takes no `lattice_store` — a rejection creates zero
    lattice nodes. This is a tuning signal only, kept separate from her
    recallable public voice.

    Args:
        signal_path: Path to the JSONL signal file (created, including
            parent directories, if it doesn't exist).
        text: The rejected draft text.
        reason: Jon's stated reason for rejecting it.
        now: ISO timestamp of the rejection (caller-supplied).
    """
    signal_path = Path(signal_path)
    signal_path.parent.mkdir(parents=True, exist_ok=True)
    record = {"text": text, "reason": reason, "now": now}
    with signal_path.open("a") as f:
        f.write(json.dumps(record) + "\n")
