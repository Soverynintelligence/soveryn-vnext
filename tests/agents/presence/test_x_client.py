import pytest

from soveryn.agents.presence.x_client import XClient, Tweet, XClientError


class FakeResp:
    def __init__(self, status, json):
        self.status_code, self._j = status, json

    def json(self):
        return self._j


class FakeHTTP:
    def __init__(self, resp):
        self.resp, self.calls = resp, []

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.resp

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.resp


def test_search_recent_parses_tweets():
    http = FakeHTTP(FakeResp(200, {"data": [
        {"id": "1", "author_id": "a", "text": "local LLM honesty"}]}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    out = c.search_recent("local LLM")
    assert out == [Tweet(id="1", author="a", text="local LLM honesty",
                         url="https://x.com/i/web/status/1")]


def test_create_tweet_returns_id():
    http = FakeHTTP(FakeResp(201, {"data": {"id": "99"}}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    assert c.create_tweet("hello") == "99"


def test_error_status_raises_without_leaking_creds():
    http = FakeHTTP(FakeResp(403, {"title": "Forbidden"}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError) as e:
        c.create_tweet("x")
    assert "403" in str(e.value) and "B" not in str(e.value)
