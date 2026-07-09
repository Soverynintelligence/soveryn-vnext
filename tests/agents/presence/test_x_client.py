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


def test_from_env_uses_canonical_var_names(monkeypatch):
    # These five names must match ~/.config/soveryn/x_presence.env exactly.
    for k in ("X_API_KEY","X_API_SECRET","X_ACCESS_TOKEN","X_ACCESS_TOKEN_SECRET","X_BEARER_TOKEN"):
        monkeypatch.setenv(k, "v-"+k)
    c = XClient.from_env(http=FakeHTTP(FakeResp(200, {"data": []})))
    assert c._bearer == "v-X_BEARER_TOKEN"
    assert c._oauth == ("v-X_API_KEY","v-X_API_SECRET","v-X_ACCESS_TOKEN","v-X_ACCESS_TOKEN_SECRET")


def test_from_env_missing_var_raises(monkeypatch):
    for k in ("X_API_KEY","X_ACCESS_TOKEN","X_ACCESS_TOKEN_SECRET","X_BEARER_TOKEN"):
        monkeypatch.setenv(k, "v")
    monkeypatch.delenv("X_API_SECRET", raising=False)   # the exact name that was wrong before
    import pytest as _pytest
    with _pytest.raises(XClientError):
        XClient.from_env(http=FakeHTTP(FakeResp(200, {"data": []})))
