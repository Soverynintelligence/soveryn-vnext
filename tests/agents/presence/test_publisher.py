from soveryn.agents.presence.publisher import publish
from soveryn.agents.presence.drafting import Draft
from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.x_client import XClientError


class FakeX:
    def __init__(self, fail=False): self.fail, self.calls = fail, []
    def create_tweet(self, text):
        if self.fail: raise XClientError("X API 500: boom")
        self.calls.append(("post", text)); return "posted-1"
    def reply_tweet(self, text, in_reply_to):
        self.calls.append(("reply", text, in_reply_to)); return "posted-2"


def test_reply_routes_and_records(tmp_path):
    store = CandidateStore(tmp_path/"c.db")
    d = Draft("1","reply","hi","x","1")
    r = publish("hi", d, FakeX(), store)
    assert r.ok and r.posted_id=="posted-2" and store.is_seen("posted-2")


def test_failure_marks_failed_no_post(tmp_path):
    store = CandidateStore(tmp_path/"c.db")
    d = Draft("1","topic","hi","x",None)
    r = publish("hi", d, FakeX(fail=True), store)
    assert not r.ok and r.posted_id is None


def test_failure_does_not_mark_posted_or_record_id(tmp_path):
    store = CandidateStore(tmp_path/"c.db")
    d = Draft("1","topic","hi","x",None)
    x = FakeX(fail=True)
    r = publish("hi", d, x, store)

    assert not r.ok
    assert r.error is not None
    assert x.calls == []

    with store._conn() as conn:
        row = conn.execute(
            "SELECT status FROM candidates WHERE tweet_id = ?", ("1",)
        ).fetchone()
    # No candidate row was inserted by publish(); status must not be "posted"
    # anywhere, and nothing should have been recorded to posted_ids.
    assert row is None or row["status"] != "posted"

    with store._conn() as conn:
        posted = conn.execute(
            "SELECT 1 FROM posted_ids WHERE tweet_id = ?", ("hi",)
        ).fetchone()
    assert posted is None
    assert not store.is_seen("posted-1")
