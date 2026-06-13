"""Layer-aware retrieval miss hints.

When a lattice search returns no usable hits, this helper probes the
other layers with a coarse keyword scan and reports per-layer counts.
The hint surfaces in the tool result so the model can pivot to a
different layer-filter (or stop searching) instead of rephrasing the
same query into the same layer.

Named per Aetheria's 2026-06-13 Harness-1 verdict: she had no signal
that the rename memo lived in `global`, not `library`, so she just kept
rephrasing into the library-filtered search.

Design:
 - Strip the query down to content tokens (alphanumeric, lower-cased,
   stopwords removed).
 - One SQL query: count nodes per layer where content LIKE any token OR
   tags LIKE any token. Excludes historical_snapshot to match the
   filter the production search already applies.
 - Returns {layer: count, ...} with all known layers represented
   (zeros included) so the absence of a layer is meaningful.

Cost: one SQL pass over the nodes table per call, bounded by the
keyword count. Only invoked on empty searches, so the steady-state
cost is zero.
"""
from __future__ import annotations

import re
from typing import Iterable

from soveryn.platform.lattice.legacy import (
    LAYER_DREAM,
    LAYER_GLOBAL,
    LAYER_LIBRARY,
    LAYER_PRIVATE,
    LatticeStore,
)


_TOKEN_RE = re.compile(r"\w+")


# Stopwords — small list keeps the SQL LIKE bounded; covers common
# English-only filler that would otherwise match every row. Kept short
# (top-30ish) so we don't accidentally strip meaningful tokens.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "of", "for", "from",
    "to", "in", "on", "at", "by", "with", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those",
    "it", "its", "i", "you", "he", "she", "we", "they", "what", "which",
    "who", "when", "where", "why", "how", "do", "does", "did", "have",
    "has", "had", "can", "could", "will", "would", "should", "may",
    "might", "no", "not", "so", "than", "then", "there", "here",
})


# Token must be at least 3 chars to count — strips single-letter noise
# and short connectives that snuck past the stopword list.
_MIN_TOKEN_LENGTH = 3


# All known layers we probe. Order matters only for stable hint output.
_ALL_LAYERS: tuple[str, ...] = (
    LAYER_LIBRARY,
    LAYER_GLOBAL,
    LAYER_PRIVATE,
    LAYER_DREAM,
)


def extract_query_tokens(query: str) -> tuple[str, ...]:
    """Strip a query down to content-bearing tokens for the LIKE scan."""
    raw = _TOKEN_RE.findall(query or "")
    return tuple(
        t.lower()
        for t in raw
        if len(t) >= _MIN_TOKEN_LENGTH and t.lower() not in _STOPWORDS
    )


def count_matches_per_layer(
    store: LatticeStore,
    agent: str,
    query: str,
    *,
    max_tokens: int = 10,
) -> dict[str, int]:
    """Return per-layer match counts for tokens extracted from `query`.

    Match rule: a node counts as a hit if its content OR tags contains
    any of the extracted tokens (substring, case-insensitive).
    Excludes historical_snapshot rows to match the production search.

    Returns {layer: count, ...} with every layer in _ALL_LAYERS
    represented (zero when no hits) so callers can rely on presence.

    No-op when extraction yields zero tokens — returns all-zero counts.
    """
    tokens = extract_query_tokens(query)[:max_tokens]
    counts = {layer: 0 for layer in _ALL_LAYERS}
    if not tokens:
        return counts

    # LIKE clauses are slow but bounded by token count; this is only
    # invoked on empty searches where the latency cost is tolerable.
    like_clauses = []
    params: list[str] = []
    for token in tokens:
        like_clauses.append("LOWER(content) LIKE ?")
        params.append(f"%{token}%")
        like_clauses.append("LOWER(IFNULL(tags, '')) LIKE ?")
        params.append(f"%{token}%")
    where = " OR ".join(like_clauses)

    sql = (
        "SELECT layer, COUNT(*) FROM nodes "
        f"WHERE ({where}) "
        "  AND ((agent = ? OR layer = ?)) "
        "  AND IFNULL(tags, '[]') NOT LIKE '%historical_snapshot%' "
        "GROUP BY layer"
    )
    params.extend([agent, LAYER_GLOBAL])

    with store._conn() as conn:  # noqa: SLF001 — package-internal helper
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        layer = row[0]
        if layer in counts:
            counts[layer] = int(row[1])
    return counts


def build_miss_hint(
    store: LatticeStore,
    agent: str,
    query: str,
) -> dict[str, object]:
    """Build the JSON-serialisable miss hint payload.

    Shape:
      {"layer_counts": {library: N, global: N, private: N, dream: N},
       "tokens_probed": ["scotty", "rename", ...]}

    Callers attach this dict to their empty result under a "miss_hint" key.
    """
    tokens = extract_query_tokens(query)
    counts = count_matches_per_layer(store, agent, query)
    return {
        "layer_counts": counts,
        "tokens_probed": list(tokens[:10]),
    }
