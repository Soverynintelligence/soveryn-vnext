"""Tests for soveryn.validation.compare. Mocks urllib — NO live calls."""

import io
import json
from unittest.mock import patch
import pytest

from soveryn.validation.compare import (
    ComparisonReport, SideResult, _aggregate_sse_events, _build_parser,
    _ensure_session, format_report, run_comparison, run_one_side,
)


# ─── Fake urlopen helpers ────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status, body_bytes):
        self.status = status
        self._body = body_bytes
    def read(self):
        return self._body
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class _FakeSSEResp:
    def __init__(self, status, lines):
        self.status = status
        self._lines = list(lines)
    def __iter__(self):
        return iter(self._lines)
    def close(self):
        pass


def _json_resp(status, payload):
    return _FakeResp(status, json.dumps(payload).encode("utf-8"))


def _sse_lines(events):
    """Build SSE response lines from a list of dicts."""
    out = []
    for e in events:
        out.append(f"data: {json.dumps(e)}\n".encode("utf-8"))
        out.append(b"\n")
    out.append(b"data: [DONE]\n")
    return out


# ─── _aggregate_sse_events (pure) ────────────────────────────────────────────

def test_aggregate_handles_token_then_done():
    evs = [
        {"type": "token", "delta": "hi"},
        {"type": "token", "delta": " there"},
        {"type": "done", "content": "hi there", "finish_reason": "stop",
         "tool_calls": None, "usage": {"total_tokens": 8}},
    ]
    content, fr, usage = _aggregate_sse_events(evs)
    assert content == "hi there"
    assert fr == "stop"
    assert usage == {"total_tokens": 8}


def test_aggregate_empty_returns_empty_content():
    content, fr, usage = _aggregate_sse_events([])
    assert content == ""
    assert fr is None
    assert usage is None


def test_aggregate_error_event_embeds_marker_in_content():
    evs = [
        {"type": "token", "delta": "partial"},
        {"type": "error", "code": "chat_timeout", "message": "60s"},
    ]
    content, fr, usage = _aggregate_sse_events(evs)
    assert "partial" in content
    assert "[ERROR chat_timeout" in content
    assert fr is None


def test_aggregate_done_event_content_wins_over_token_accumulation():
    """If done.content disagrees with token accumulation, done is authoritative."""
    evs = [
        {"type": "token", "delta": "garbled"},
        {"type": "done", "content": "final", "finish_reason": "stop"},
    ]
    content, fr, _ = _aggregate_sse_events(evs)
    assert content == "final"
    assert fr == "stop"


def test_aggregate_unknown_shape_best_effort():
    """Production may use a different schema — pull from common fields."""
    evs = [{"content": "hello"}]
    content, fr, _ = _aggregate_sse_events(evs)
    assert content == "hello"


# ─── _ensure_session ─────────────────────────────────────────────────────────

def test_ensure_session_returns_existing_unchanged():
    sid, err = _ensure_session("http://x", "aetheria", "preexisting-id", 10.0)
    assert sid == "preexisting-id"
    assert err is None


def test_ensure_session_creates_new_when_absent():
    with patch("urllib.request.urlopen",
               return_value=_json_resp(201, {"session_id": "new-sid", "agent": "aetheria"})):
        sid, err = _ensure_session("http://x", "aetheria", None, 10.0)
    assert sid == "new-sid"
    assert err is None


def test_ensure_session_reports_http_error():
    with patch("urllib.request.urlopen",
               return_value=_json_resp(400, {"error": "bad"})):
        sid, err = _ensure_session("http://x", "aetheria", None, 10.0)
    assert sid is None
    assert "HTTP 400" in err


def test_ensure_session_reports_transport_error():
    import urllib.error
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("connection refused")):
        sid, err = _ensure_session("http://x", "aetheria", None, 10.0)
    assert sid is None
    assert "transport error" in err


# ─── run_one_side — sync /chat ───────────────────────────────────────────────

def test_run_one_side_sync_happy_path():
    """Two urlopen calls: session create, then /chat."""
    call_seq = [
        _json_resp(201, {"session_id": "sid-1", "agent": "aetheria"}),
        _json_resp(200, {
            "agent": "aetheria", "session_id": "sid-1",
            "content": "hello back", "finish_reason": "stop",
            "tool_calls": None, "usage": {"total_tokens": 5},
        }),
    ]
    with patch("urllib.request.urlopen", side_effect=call_seq):
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=False, timeout=10.0)
    assert r.ok is True
    assert r.status_code == 200
    assert r.session_id == "sid-1"
    assert r.content == "hello back"
    assert r.finish_reason == "stop"
    assert r.usage == {"total_tokens": 5}
    assert r.latency_ms is not None and r.latency_ms >= 0


def test_run_one_side_sync_session_already_provided_skips_creation():
    """When session_id is passed in, no POST /sessions happens — only /chat."""
    with patch("urllib.request.urlopen",
               return_value=_json_resp(200, {"content": "x"})) as m:
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id="given-sid", stream=False, timeout=10.0)
    assert r.session_id == "given-sid"
    assert m.call_count == 1  # only /chat, no /sessions


def test_run_one_side_sync_falls_back_to_alt_content_field():
    """If 'content' is missing, try 'response' / 'message' / 'text' / 'reply'."""
    seq = [
        _json_resp(201, {"session_id": "sid", "agent": "a"}),
        _json_resp(200, {"response": "prod-shape content"}),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=False, timeout=10.0)
    assert r.ok is True
    assert r.content == "prod-shape content"


def test_run_one_side_sync_chat_failure_captured_not_raised():
    """A non-2xx on /chat → ok=False, error set, no exception."""
    import urllib.error
    seq = [
        _json_resp(201, {"session_id": "sid", "agent": "a"}),
        urllib.error.HTTPError("u", 502, "bad gateway", {}, io.BytesIO(b'{"error":"x"}')),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=False, timeout=10.0)
    assert r.ok is False
    assert "HTTP 502" in r.error


def test_run_one_side_sync_session_create_failure_skips_chat():
    """Session create failure → ok=False, no /chat attempted."""
    import urllib.error
    with patch("urllib.request.urlopen",
               side_effect=urllib.error.URLError("nope")) as m:
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=False, timeout=10.0)
    assert r.ok is False
    assert "transport error" in r.error
    assert m.call_count == 1  # only the failed session POST


def test_run_one_side_transport_error_during_chat():
    import urllib.error
    seq = [
        _json_resp(201, {"session_id": "sid", "agent": "a"}),
        urllib.error.URLError("dropped"),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=False, timeout=10.0)
    assert r.ok is False
    assert "transport error" in r.error
    assert r.latency_ms is not None


# ─── run_one_side — stream /chat_stream ──────────────────────────────────────

def test_run_one_side_stream_happy_path():
    seq = [
        _json_resp(201, {"session_id": "sid", "agent": "a"}),
        _FakeSSEResp(200, _sse_lines([
            {"type": "token", "delta": "hi"},
            {"type": "token", "delta": " there"},
            {"type": "done", "content": "hi there", "finish_reason": "stop",
             "tool_calls": None, "usage": {"total_tokens": 8}},
        ])),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        r = run_one_side(base="http://x", agent="aetheria", message="hi",
                         session_id=None, stream=True, timeout=10.0)
    assert r.ok is True
    assert r.content == "hi there"
    assert r.finish_reason == "stop"
    assert r.usage["total_tokens"] == 8


# ─── run_comparison + format_report ──────────────────────────────────────────

def test_run_comparison_match_when_contents_identical():
    seq = [
        _json_resp(201, {"session_id": "p-sid"}),   # prod sessions
        _json_resp(200, {"content": "same"}),        # prod chat
        _json_resp(201, {"session_id": "v-sid"}),   # vnext sessions
        _json_resp(200, {"content": "same"}),        # vnext chat
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        report = run_comparison(agent="aetheria", message="hi", stream=False)
    assert report.prod.ok and report.vnext.ok
    assert report.contents_match is True
    assert report.diff == []


def test_run_comparison_diff_when_contents_differ():
    seq = [
        _json_resp(201, {"session_id": "p"}),
        _json_resp(200, {"content": "prod reply"}),
        _json_resp(201, {"session_id": "v"}),
        _json_resp(200, {"content": "vnext reply"}),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        report = run_comparison(agent="aetheria", message="hi", stream=False)
    assert report.contents_match is False
    assert report.diff  # non-empty unified diff
    diff_text = "\n".join(report.diff)
    assert "prod" in diff_text and "vnext" in diff_text


def test_run_comparison_one_side_fails_other_still_recorded():
    """Prod fails session create; vNext succeeds. Report shows both."""
    import urllib.error
    seq = [
        urllib.error.URLError("prod down"),
        _json_resp(201, {"session_id": "v"}),
        _json_resp(200, {"content": "vnext alone"}),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        report = run_comparison(agent="aetheria", message="hi", stream=False)
    assert report.prod.ok is False
    assert report.vnext.ok is True
    assert report.vnext.content == "vnext alone"
    assert report.contents_match is False
    assert report.diff == []  # diff skipped when one side fails


def test_format_report_renders_human_readable():
    side_prod = SideResult(base_url="http://prod", ok=True, status_code=200,
                           latency_ms=120.5, session_id="psid", content="hello",
                           finish_reason="stop",
                           usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3})
    side_v = SideResult(base_url="http://vnext", ok=True, status_code=200,
                        latency_ms=140.0, session_id="vsid", content="hello",
                        finish_reason="stop", usage=None)
    report = ComparisonReport(agent="aetheria", message="hi", stream=False,
                              prod=side_prod, vnext=side_v, contents_match=True)
    out = format_report(report)
    assert "agent=aetheria" in out
    assert "PROD" in out and "vNEXT" in out
    assert "120ms" in out and "140ms" in out
    assert "Contents match exactly" in out


def test_format_report_shows_diff_when_present():
    side_prod = SideResult(base_url="http://prod", ok=True, status_code=200,
                           latency_ms=10.0, content="alpha")
    side_v = SideResult(base_url="http://vnext", ok=True, status_code=200,
                        latency_ms=12.0, content="beta")
    diff = ["--- prod", "+++ vnext", "-alpha", "+beta"]
    report = ComparisonReport(agent="a", message="m", stream=False,
                              prod=side_prod, vnext=side_v, contents_match=False,
                              diff=diff)
    out = format_report(report)
    assert "Diff" in out
    assert "-alpha" in out
    assert "+beta" in out


def test_format_report_shows_failure_clearly():
    side_prod = SideResult(base_url="http://prod", ok=False, error="connection refused")
    side_v = SideResult(base_url="http://vnext", ok=True, content="x", status_code=200,
                        latency_ms=5.0)
    report = ComparisonReport(agent="a", message="m", stream=False,
                              prod=side_prod, vnext=side_v)
    out = format_report(report)
    assert "FAILED" in out
    assert "connection refused" in out


# ─── CLI parser ──────────────────────────────────────────────────────────────

def test_parser_requires_message():
    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])  # --message is required


def test_parser_defaults():
    parser = _build_parser()
    args = parser.parse_args(["--message", "hi"])
    assert args.agent == "aetheria"
    assert args.prod_base == "http://127.0.0.1:5000"
    assert args.vnext_base == "http://127.0.0.1:5001"
    assert args.stream is False
    assert args.session_prod is None
    assert args.json_out is None
    assert args.timeout == 120.0


def test_parser_stream_flag():
    parser = _build_parser()
    args = parser.parse_args(["--message", "hi", "--stream"])
    assert args.stream is True


def test_parser_custom_bases():
    parser = _build_parser()
    args = parser.parse_args(["--message", "hi",
                              "--prod-base", "http://other:6000",
                              "--vnext-base", "http://other:6001"])
    assert args.prod_base == "http://other:6000"
    assert args.vnext_base == "http://other:6001"


# ─── --json-out persistence ──────────────────────────────────────────────────

def test_json_out_writes_full_report(tmp_path):
    from soveryn.validation.compare import main
    seq = [
        _json_resp(201, {"session_id": "p"}),
        _json_resp(200, {"content": "same"}),
        _json_resp(201, {"session_id": "v"}),
        _json_resp(200, {"content": "same"}),
    ]
    out_path = tmp_path / "report.json"
    with patch("urllib.request.urlopen", side_effect=seq):
        rc = main(["--message", "hi", "--json-out", str(out_path)])
    assert rc == 0  # both ok, contents match
    payload = json.loads(out_path.read_text())
    assert payload["contents_match"] is True
    assert payload["prod"]["ok"] is True
    assert payload["vnext"]["ok"] is True


def test_main_exit_code_diff_is_1(tmp_path):
    from soveryn.validation.compare import main
    seq = [
        _json_resp(201, {"session_id": "p"}),
        _json_resp(200, {"content": "alpha"}),
        _json_resp(201, {"session_id": "v"}),
        _json_resp(200, {"content": "beta"}),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        rc = main(["--message", "hi"])
    assert rc == 1


def test_main_exit_code_one_side_failed_is_2(tmp_path):
    from soveryn.validation.compare import main
    import urllib.error
    seq = [
        urllib.error.URLError("down"),
        _json_resp(201, {"session_id": "v"}),
        _json_resp(200, {"content": "ok"}),
    ]
    with patch("urllib.request.urlopen", side_effect=seq):
        rc = main(["--message", "hi"])
    assert rc == 2


def test_main_rejects_empty_message():
    from soveryn.validation.compare import main
    rc = main(["--message", "   "])
    assert rc == 2
