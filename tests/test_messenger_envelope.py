"""Envelope dataclasses match spec §6 verbatim."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.envelope import (
    InboundMessage,
    OutboundIntent,
    ThreadListEntry,
    MessageEnvelope,
)


def test_inbound_message_required_fields():
    msg = InboundMessage(
        client_msg_id="abc",
        thread_id="tid",
        agent="aetheria",
        content="hi",
        attachments=(),
        device_id="did",
        client_ts="2026-06-14T08:00:00-04:00",
    )
    assert msg.client_msg_id == "abc"
    assert msg.attachments == ()


def test_outbound_intent_required_fields():
    intent = OutboundIntent(
        intent_id="iid",
        agent="aetheria",
        thread_id=None,
        content="quick thought",
        context_hint="dark search reflection",
        urgency="routine",
        triggered_by="background_review",
        created_at="2026-06-14T08:00:00-04:00",
    )
    assert intent.urgency == "routine"
    assert intent.thread_id is None  # default thread


def test_outbound_intent_rejects_invalid_urgency():
    with pytest.raises(ValueError, match="urgency"):
        OutboundIntent(
            intent_id="iid", agent="aetheria", thread_id=None,
            content="x", context_hint="x",
            urgency="critical",  # not in enum
            triggered_by="x", created_at="2026-06-14T08:00:00-04:00",
        )


def test_message_envelope_marks_by_user_or_agent():
    e = MessageEnvelope(
        message_id="m1", thread_id="t1", by="user", agent="aetheria",
        content="hi", client_msg_id="c1",
        created_at="2026-06-14T08:00:00-04:00",
        delivered_at=None, read_at=None,
        tool_calls=None, finish_reason=None,
        context_hint=None, urgency=None,
    )
    assert e.by == "user"
