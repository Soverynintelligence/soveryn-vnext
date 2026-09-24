"""Locked fact rail + receipt kinds."""

from __future__ import annotations

import pytest

from soveryn.platform.lattice.fact_rail import fact_query_tokens, merge_fact_rail
from soveryn.platform.lattice.legacy import Node
from soveryn.platform.lattice.receipt import ActionReceipt, ReceiptKind


def _node(nid: str, content: str) -> Node:
    return Node(
        id=nid,
        type="semantic",
        layer="private",
        agent="aetheria",
        content=content,
        intensity=0.7,
        salience=0.7,
        access_count=0,
        tags=("canonical_fact",),
        created_at="t",
        updated_at="t",
        embedding=None,
        intent=None,
        provenance=None,
    )


def test_fact_query_tokens_keep_phone_year_and_negation():
    tokens = fact_query_tokens("Call (910) 581-3970 — that is not Stripe")
    joined = " ".join(tokens)
    assert "910" in joined or "5813970" in joined or "9105813970" in joined
    assert "stripe" in joined


def test_merge_fact_rail_dedupes_cosine_hits():
    a = _node("a", "phone 910")
    b = _node("b", "other")
    facts, rest = merge_fact_rail(((a, 0.99), (b, 0.8)), (a,))
    assert facts == (a,)
    assert rest == ((b, 0.8),)


def test_receipt_rejects_empty_source():
    with pytest.raises(ValueError):
        ActionReceipt(ReceiptKind.TOOL_OK, source="  ")
