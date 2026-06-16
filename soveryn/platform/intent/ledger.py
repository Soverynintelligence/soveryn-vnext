"""The deliberate-share ledger writer.

record_intent() is the single source of truth for turning a deliberate
share into a behavioral correlate in the Lattice — one node + one
triggered_by edge — regardless of which surface emitted it. The edges
table FK on source_id/target_id requires real nodes, so a live trigger
that isn't a node yet is materialized into a typed anchor first.

Pattern mirrors legacy.record_direct_communication_edge (node, then edge).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from soveryn.platform.lattice.legacy import LatticeStore, LAYER_PRIVATE
from soveryn.platform.intent.grammar import DeliberateShareIntent

DELIBERATE_SHARE_TYPE = "deliberate_share"
TRIGGER_ANCHOR_TYPE = "trigger_anchor"
TRIGGERED_BY = "triggered_by"


def resolve_trigger(store: LatticeStore, *, agent: str, trigger_ref: str) -> str:
    """Return a real lattice node id for trigger_ref.

    If trigger_ref is already an existing node id, return it unchanged.
    Otherwise materialize a lightweight typed anchor node (the trigger as a
    witnessed event) and return its id. Either way the caller gets a node id
    the edges FK will accept — no free-prose triggers reach the graph.
    """
    if store.get_node(trigger_ref) is not None:
        return trigger_ref
    return store.write_node(
        agent=agent,
        content=trigger_ref,
        node_type=TRIGGER_ANCHOR_TYPE,
        layer=LAYER_PRIVATE,
        provenance={"kind": TRIGGER_ANCHOR_TYPE},
    )


def record_intent(
    store: LatticeStore,
    *,
    agent: str,
    content: str,
    intent: DeliberateShareIntent,
    channel: str,
) -> tuple[str, str, str]:
    """Write the deliberate_share mark node + triggered_by edge.

    Returns (mark_node_id, trigger_node_id, edge_id).
    """
    trigger_node_id = resolve_trigger(store, agent=agent, trigger_ref=intent.trigger)
    mark_node_id = store.write_node(
        agent=agent,
        content=content,
        node_type=DELIBERATE_SHARE_TYPE,
        layer=LAYER_PRIVATE,
        intent=intent.stance,
        provenance={
            "kind": DELIBERATE_SHARE_TYPE,
            "why": intent.why,
            "stance": intent.stance,
            "trigger": trigger_node_id,
            "channel": channel,
        },
    )
    edge_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO edges "
            "(id, source_id, target_id, relationship, strength, bidirectional, "
            "archived, reinforcement_count, reinforced_at, created_at) "
            "VALUES (?, ?, ?, ?, 0.5, 0, 0, 1, ?, ?)",
            (edge_id, mark_node_id, trigger_node_id, TRIGGERED_BY, now, now),
        )
    return mark_node_id, trigger_node_id, edge_id
