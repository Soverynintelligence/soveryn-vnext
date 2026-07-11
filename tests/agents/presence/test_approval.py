"""Tests for Signal message formatting + reply classification.

classify_reply is the human-approval safety seam: an ambiguous or unexpected
reply must NEVER resolve to approve. Only exact affirm/reject tokens do;
everything else non-empty becomes an edit using that literal text.
"""

from soveryn.agents.presence.approval import format_signal_message, classify_reply
from soveryn.agents.presence.drafting import Draft

D = Draft("1", "reply", "Grounded > confident.", "confab data", "1")


def test_message_shows_provenance_and_link():
    m = format_signal_message(D, "d1")
    assert "confab data" in m
    assert "d1" in m
    assert "status/1" in m
    assert "x.com" in m


def test_approve_tokens():
    assert classify_reply("y") == ("approve", None)
    assert classify_reply("approve") == ("approve", None)


def test_reject_with_reason():
    assert classify_reply("reject: off message") == ("reject", "off message")


def test_freeform_is_edit():
    assert classify_reply("Say it softer, lead with the question.") == \
        ("edit", "Say it softer, lead with the question.")


def test_ambiguous_reply_never_approves():
    # "maybe later" is not a recognized affirm/reject token — must NOT approve.
    kind, payload = classify_reply("maybe later")
    assert kind != "approve"
    assert (kind, payload) == ("edit", "maybe later")


def test_more_approve_and_reject_tokens_case_and_whitespace_insensitive():
    assert classify_reply("Yes") == ("approve", None)
    assert classify_reply("  YES  ") == ("approve", None)
    assert classify_reply("Post") == ("approve", None)
    assert classify_reply("N") == ("reject", None)
    assert classify_reply("no") == ("reject", None)
    assert classify_reply("skip") == ("reject", None)
    assert classify_reply("reject") == ("reject", None)


def test_missing_provenance_is_flagged_in_message():
    unstated = Draft("2", "topic", "Some claim.", "(none stated)", None)
    m = format_signal_message(unstated, "d2")
    assert "(none stated)" in m
    # Must be visibly flagged, not just silently present.
    assert "NO PROVENANCE" in m.upper() or "UNSTATED" in m.upper() or "FLAG" in m.upper() or "WARNING" in m.upper() or "!" in m


def test_topic_draft_message_has_no_reply_link():
    topic = Draft("3", "topic", "On-device inference.", "our roadmap", None)
    m = format_signal_message(topic, "d3")
    assert "status/" not in m


def test_empty_reply_does_not_approve():
    kind, _ = classify_reply("")
    assert kind != "approve"
    kind2, _ = classify_reply("   ")
    assert kind2 != "approve"
