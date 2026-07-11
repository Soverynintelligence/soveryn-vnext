"""Tests for the approval resolver: affirm-only publishes, bias to safety.

`resolve_pending` looks up the single per-agent staged-post slot
(`StagedStore.pending`) and only ever acts (publish or reject) on a clear
affirm/decline from Jon. Anything else — including a plausible-sounding
but ambiguous reply — must leave the post untouched and return None so the
agent's normal conversational turn runs instead.
"""

from __future__ import annotations

import pytest

from soveryn.agents.presence.resolver import ResolveResult, classify_affirmation, resolve_pending
from soveryn.agents.presence.staged_store import StagedStore


def make_staged(tmp_path, *, text="draft text", reply_to=None, now="2026-07-11T10:00:00"):
    staged = StagedStore(tmp_path / "staged.db")
    post = staged.stage(agent="aetheria", text=text, reply_to=reply_to, now=now)
    return staged, post


class Recorder:
    """Call recorder for the injected publisher/x_memory/rejection fns."""

    def __init__(self, publish_result=None, publish_raises=None):
        self.publish_calls: list[tuple[str, str | None]] = []
        self.x_memory_calls: list = []
        self.rejection_calls: list[tuple] = []
        self._publish_result = publish_result if publish_result is not None else {
            "id": "12345",
            "url": "https://x.com/Soveryn_AI/status/12345",
        }
        self._publish_raises = publish_raises

    def publisher_fn(self, text, reply_to):
        self.publish_calls.append((text, reply_to))
        if self._publish_raises is not None:
            raise self._publish_raises
        return self._publish_result

    def x_memory_fn(self, post):
        self.x_memory_calls.append(post)

    def rejection_fn(self, post, reason=None):
        self.rejection_calls.append((post, reason))


# ---------------------------------------------------------------------------
# classify_affirmation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["yes", "Y", " y ", "post it", "GO", "send it", "👍", "ok post", "Yes"])
def test_classify_clear_affirm_tokens(text):
    assert classify_affirmation(text) == "affirm"


@pytest.mark.parametrize("text", ["no", "N", " no ", "nope", "don't", "dont", "reject", "skip", "cancel", "No"])
def test_classify_clear_decline_tokens(text):
    assert classify_affirmation(text) == "decline"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_classify_empty_or_whitespace_is_unrelated(text):
    assert classify_affirmation(text) == "unrelated"


@pytest.mark.parametrize(
    "text",
    [
        "hold on, let me check the other thing",
        "what's the weather like",
        "remind me to call mom",
        "yes but let me think about it first",
        "no idea what you mean",
        "maybe later",
    ],
)
def test_classify_ambiguous_or_subject_change_is_unrelated_never_affirm(text):
    verdict = classify_affirmation(text)
    assert verdict != "affirm"
    assert verdict == "unrelated"


@pytest.mark.parametrize(
    "text",
    [
        "change the last line to something punchier",
        "can you shorten it a bit",
        "reword the opening",
        "instead of that, mention the paper",
        "add a link to the repo",
    ],
)
def test_classify_substantive_rewrite_instruction_is_edit(text):
    assert classify_affirmation(text) == "edit"


def test_classify_bias_to_safety_ambiguous_never_yields_affirm():
    ambiguous_messages = [
        "hmm",
        "not sure",
        "let me think",
        "yesish",
        "nah maybe",
        "hold on",
        "ya think so?",
    ]
    for text in ambiguous_messages:
        assert classify_affirmation(text) != "affirm"


# ---------------------------------------------------------------------------
# resolve_pending
# ---------------------------------------------------------------------------


def test_no_pending_returns_none(tmp_path):
    staged = StagedStore(tmp_path / "staged.db")
    rec = Recorder()

    result = resolve_pending(
        agent="aetheria",
        message="yes",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:00:00",
    )

    assert result is None
    assert rec.publish_calls == []


def test_affirm_publishes_marks_and_writes_memory(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder(publish_result={"id": "999", "url": "https://x.com/Soveryn_AI/status/999"})

    result = resolve_pending(
        agent="aetheria",
        message="yes",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert isinstance(result, ResolveResult)
    assert result.action == "published"
    assert result.posted_id == "999"
    assert "https://x.com/Soveryn_AI/status/999" in result.note

    assert rec.publish_calls == [("hello world", None)]
    assert rec.x_memory_calls == [post]
    assert staged.pending("aetheria") is None  # no longer proposed


def test_affirm_with_publisher_error_does_not_mark_published(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder(publish_result={"error": "rate limited"})

    result = resolve_pending(
        agent="aetheria",
        message="yes",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert isinstance(result, ResolveResult)
    assert result.action != "published"
    assert rec.x_memory_calls == []
    # Post is still pending/proposed, retryable.
    assert staged.pending("aetheria") is not None
    assert staged.pending("aetheria").id == post.id


def test_affirm_with_publisher_exception_does_not_mark_published(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder(publish_raises=RuntimeError("network down"))

    result = resolve_pending(
        agent="aetheria",
        message="go",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert isinstance(result, ResolveResult)
    assert result.action != "published"
    assert rec.x_memory_calls == []
    assert staged.pending("aetheria") is not None
    assert staged.pending("aetheria").id == post.id


def test_unrelated_message_returns_none_no_publish_post_stays_proposed(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder()

    result = resolve_pending(
        agent="aetheria",
        message="hold on, let me check the other thing",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert result is None
    assert rec.publish_calls == []
    assert rec.x_memory_calls == []
    assert rec.rejection_calls == []
    pending = staged.pending("aetheria")
    assert pending is not None
    assert pending.id == post.id
    assert pending.state == "proposed"


def test_edit_message_returns_none_no_publish_post_stays_proposed(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder()

    result = resolve_pending(
        agent="aetheria",
        message="can you shorten it a bit",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert result is None
    assert rec.publish_calls == []
    pending = staged.pending("aetheria")
    assert pending is not None
    assert pending.id == post.id


def test_decline_marks_rejected_and_calls_rejection_fn_no_publish(tmp_path):
    staged, post = make_staged(tmp_path, text="hello world", reply_to=None)
    rec = Recorder()

    result = resolve_pending(
        agent="aetheria",
        message="no",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert isinstance(result, ResolveResult)
    assert result.action == "declined"
    assert rec.publish_calls == []
    assert rec.x_memory_calls == []
    assert len(rec.rejection_calls) == 1
    rejected_post, reason = rec.rejection_calls[0]
    assert rejected_post == post
    assert reason == "no"
    assert staged.pending("aetheria") is None


def test_affirm_publishes_reply_with_reply_to(tmp_path):
    staged, post = make_staged(tmp_path, text="a reply", reply_to="tweet-42")
    rec = Recorder(publish_result={"id": "1", "url": "https://x.com/Soveryn_AI/status/1"})

    result = resolve_pending(
        agent="aetheria",
        message="send it",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert result.action == "published"
    assert rec.publish_calls == [("a reply", "tweet-42")]


def test_agent_scoping_does_not_resolve_other_agents_post(tmp_path):
    staged = StagedStore(tmp_path / "staged.db")
    staged.stage(agent="aetheria", text="aetheria's draft", reply_to=None, now="2026-07-11T10:00:00")
    rec = Recorder()

    result = resolve_pending(
        agent="vett",
        message="yes",
        staged=staged,
        publisher_fn=rec.publisher_fn,
        x_memory_fn=rec.x_memory_fn,
        rejection_fn=rec.rejection_fn,
        now="2026-07-11T10:05:00",
    )

    assert result is None
    assert rec.publish_calls == []
    # aetheria's post is untouched.
    assert staged.pending("aetheria") is not None
