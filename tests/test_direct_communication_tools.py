import json
import pytest
from datetime import datetime

from soveryn.agents.direct_communication.tools import (
    build_direct_message_agent_tool,
)
from soveryn.platform.tools.registry import ToolArgError


def _build_tool(rate_limiter=None, http_poster=None, edge_writer=None,
                vnext_base="http://127.0.0.1:5001", owner="aetheria"):
    """Test helper — inject all collaborators."""
    return build_direct_message_agent_tool(
        owner_agent=owner,
        rate_limiter=rate_limiter,
        http_poster=http_poster,
        edge_writer=edge_writer,
        vnext_base=vnext_base,
    )


def _ok_poster_factory(content="ack", session_id="sess-1", finish_reason="stop"):
    """Build a fake http_poster that returns OK responses for both /sessions and /chat."""
    posted_calls = []
    def fake_poster(url, body, timeout):
        posted_calls.append({"url": url, "body": body, "timeout": timeout})
        if url.endswith("/sessions"):
            return {"session_id": session_id, "agent": body["agent"], "title": body.get("title")}
        return {"content": content, "session_id": session_id, "finish_reason": finish_reason}
    return fake_poster, posted_calls


def test_direct_message_agent_rejects_missing_coord_node_id():
    """Schema-layer loop-chatter defense — no message without an anchor."""
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="coord_node_id"):
        tool.handler({
            "target": "vett",
            "message": "do X",
            # coord_node_id deliberately absent
        })


def test_direct_message_agent_rejects_invalid_target():
    """Only vett or scotty — Aetheria can't direct-message herself."""
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="target"):
        tool.handler({
            "target": "aetheria",
            "message": "x", "coord_node_id": "node-1",
        })


def test_direct_message_agent_rejects_unknown_target():
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="target"):
        tool.handler({
            "target": "ares",
            "message": "x", "coord_node_id": "node-1",
        })


def test_direct_message_agent_rejects_invalid_mode():
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="mode"):
        tool.handler({
            "target": "vett",
            "message": "x", "coord_node_id": "node-1", "mode": "shout",
        })


def test_direct_message_agent_rejects_empty_message():
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="message"):
        tool.handler({
            "target": "vett",
            "message": "  ", "coord_node_id": "node-1",
        })


def test_direct_message_agent_execute_mode_prefixes_directive():
    """The wire message Vett sees is prefixed with [DIRECTIVE FROM AETHERIA, ...]."""
    fake_poster, posted_calls = _ok_poster_factory(content="ack")
    tool = _build_tool(http_poster=fake_poster)
    result = tool.handler({
        "target": "vett",
        "message": "process the new audit findings",
        "coord_node_id": "node-42",
        "mode": "execute",
    })
    # Two POSTs: one to /sessions, one to /chat
    assert len(posted_calls) == 2
    chat_call = [c for c in posted_calls if c["url"].endswith("/chat")][0]
    body = chat_call["body"]
    assert body["agent"] == "vett"
    assert "[DIRECTIVE FROM AETHERIA" in body["message"]
    assert "coord:node-42" in body["message"]
    assert "process the new audit findings" in body["message"]
    assert result["target"] == "vett"
    assert result["response_content"] == "ack"
    assert result["coord_node_id"] == "node-42"
    assert result["finish_reason"] == "stop"


def test_direct_message_agent_query_mode_prefixes_query():
    """Query mode uses [QUERY FROM AETHERIA, ...] framing."""
    fake_poster, posted_calls = _ok_poster_factory(content="raw obs")
    tool = _build_tool(http_poster=fake_poster)
    tool.handler({
        "target": "vett",
        "message": "what friction are you seeing right now?",
        "coord_node_id": "node-9",
        "mode": "query",
    })
    chat_call = [c for c in posted_calls if c["url"].endswith("/chat")][0]
    msg = chat_call["body"]["message"]
    assert "[QUERY FROM AETHERIA" in msg
    assert "coord:node-9" in msg
    assert "raw observations" in msg.lower()


def test_direct_message_agent_default_mode_is_execute():
    fake_poster, posted_calls = _ok_poster_factory()
    tool = _build_tool(http_poster=fake_poster)
    tool.handler({
        "target": "vett", "message": "x", "coord_node_id": "node-1",
    })  # no mode arg
    chat_call = [c for c in posted_calls if c["url"].endswith("/chat")][0]
    assert "[DIRECTIVE FROM AETHERIA" in chat_call["body"]["message"]


def test_direct_message_agent_writes_lattice_edge_on_success():
    """Every successful call records a forensic edge tying message → coord node."""
    edge_calls = []
    def fake_edge(coord_node_id, message_node_id, mode):
        edge_calls.append((coord_node_id, message_node_id, mode))
        return "edge-abc"
    fake_poster, _ = _ok_poster_factory()
    tool = _build_tool(edge_writer=fake_edge, http_poster=fake_poster)
    result = tool.handler({
        "target": "vett", "message": "do X",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert len(edge_calls) == 1
    assert edge_calls[0][0] == "node-1"
    assert edge_calls[0][2] == "execute"
    assert result["edge_id"] == "edge-abc"


def test_direct_message_agent_returns_structured_error_when_rate_capped():
    """Rate-limit returns structured {error, retry_after_seconds}, not raise."""
    from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter
    limiter = DirectCommRateLimiter(per_minute_cap=0)  # always-capped
    fake_poster, posted_calls = _ok_poster_factory()
    tool = _build_tool(rate_limiter=limiter, http_poster=fake_poster)
    result = tool.handler({
        "target": "vett", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "rate_limited"
    assert isinstance(result["retry_after_seconds"], int)
    # No HTTP traffic happened
    assert posted_calls == []


def test_direct_message_agent_returns_structured_error_on_chat_failure():
    """Downstream /chat 5xx → {error, message} structured result."""
    import urllib.error
    import io
    def failing_poster(url, body, timeout):
        if url.endswith("/sessions"):
            return {"session_id": "sess-1", "agent": body["agent"]}
        raise urllib.error.HTTPError(url, 502, "bad gateway", hdrs={}, fp=io.BytesIO(b""))
    tool = _build_tool(http_poster=failing_poster)
    result = tool.handler({
        "target": "vett", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "dispatch_failed"
    assert "502" in result["message"]


def test_direct_message_agent_returns_structured_error_on_session_failure():
    """Session mint failure → dispatch_failed."""
    import urllib.error
    import io
    def failing_poster(url, body, timeout):
        if url.endswith("/sessions"):
            raise urllib.error.HTTPError(url, 500, "internal", hdrs={}, fp=io.BytesIO(b""))
        return {"content": "shouldn't reach"}
    tool = _build_tool(http_poster=failing_poster)
    result = tool.handler({
        "target": "vett", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "dispatch_failed"
    assert "session" in result["message"].lower() or "500" in result["message"]
