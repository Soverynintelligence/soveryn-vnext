import pytest
import requests

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


class RaisingHTTP:
    """Fake http whose .get/.post raise a raw requests exception, simulating
    a network failure (DNS, connection refused, timeout, etc.)."""

    def __init__(self, exc):
        self._exc = exc

    def get(self, *a, **kw):
        raise self._exc

    def post(self, *a, **kw):
        raise self._exc


class NonJsonErrorResp:
    """Fake response whose .json() raises, simulating a non-JSON error body
    (e.g. Cloudflare HTML on a 503)."""

    def __init__(self, status):
        self.status_code = status

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


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


def test_create_tweet_attaches_media_ids():
    http = FakeHTTP(FakeResp(201, {"data": {"id": "100"}}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    assert c.create_tweet("hello", media_ids=["777"]) == "100"
    _method, url, kw = http.calls[0]
    assert url.endswith("/2/tweets")
    assert kw["json"]["media"]["media_ids"] == ["777"]


def test_upload_media_returns_id(tmp_path):
    img = tmp_path / "chess.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    http = FakeHTTP(FakeResp(200, {"media_id_string": "555"}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    assert c.upload_media(str(img)) == "555"
    _method, url, kw = http.calls[0]
    assert "upload.twitter.com" in url
    assert "files" in kw


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


# ─── Finding 1: XClient must raise ONLY XClientError ───────────────────────


def test_search_recent_connection_error_becomes_x_client_error():
    http = RaisingHTTP(requests.exceptions.ConnectionError("connection refused"))
    c = XClient(bearer="SECRETBEARER", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError) as e:
        c.search_recent("local LLM")
    assert "SECRETBEARER" not in str(e.value)


def test_search_recent_timeout_becomes_x_client_error():
    http = RaisingHTTP(requests.exceptions.Timeout("timed out"))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError):
        c.search_recent("local LLM")


def test_post_tweet_connection_error_becomes_x_client_error():
    http = RaisingHTTP(requests.exceptions.ConnectionError("connection refused"))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError):
        c.create_tweet("hello")


def test_post_tweet_timeout_becomes_x_client_error():
    http = RaisingHTTP(requests.exceptions.Timeout("timed out"))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError):
        c.reply_tweet("hello", "1")


def test_error_response_non_json_body_raises_with_status_and_no_secret():
    # Simulates a 503 with a Cloudflare HTML body instead of JSON.
    http = FakeHTTP(NonJsonErrorResp(503))
    c = XClient(bearer="SECRETBEARER", oauth=("SECRETKEY", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError) as e:
        c.search_recent("local LLM")
    msg = str(e.value)
    assert "503" in msg
    assert "SECRETBEARER" not in msg
    assert "SECRETKEY" not in msg


def test_post_tweet_error_response_non_json_body_raises_with_status():
    http = FakeHTTP(NonJsonErrorResp(500))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError) as e:
        c.create_tweet("hello")
    assert "500" in str(e.value)


def test_post_tweet_malformed_2xx_body_missing_data_raises():
    http = FakeHTTP(FakeResp(201, {"unexpected": "shape"}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError):
        c.create_tweet("hello")


def test_post_tweet_malformed_2xx_body_missing_id_raises():
    http = FakeHTTP(FakeResp(201, {"data": {}}))
    c = XClient(bearer="B", oauth=("k", "s", "t", "ts"), http=http)
    with pytest.raises(XClientError):
        c.create_tweet("hello")
