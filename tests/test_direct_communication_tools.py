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
            "target": "eve",
            "message": "do X",
            # coord_node_id deliberately absent
        })


def test_direct_message_agent_rejects_invalid_target():
    """Only Eve/Kernel — Aetheria can't direct-message herself."""
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


@pytest.mark.parametrize("parked", ["vett", "scotty"])
def test_direct_message_agent_rejects_parked_vett_scotty(parked):
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="target"):
        tool.handler({
            "target": parked,
            "message": "x", "coord_node_id": "node-1",
        })


def test_direct_message_agent_rejects_invalid_mode():
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="mode"):
        tool.handler({
            "target": "eve",
            "message": "x", "coord_node_id": "node-1", "mode": "shout",
        })


def test_direct_message_agent_rejects_empty_message():
    tool = _build_tool()
    with pytest.raises(ToolArgError, match="message"):
        tool.handler({
            "target": "eve",
            "message": "  ", "coord_node_id": "node-1",
        })


def test_direct_message_agent_execute_mode_prefixes_directive():
    """The wire message the peer sees is prefixed with [DIRECTIVE FROM AETHERIA, ...]."""
    fake_poster, posted_calls = _ok_poster_factory(content="ack")
    tool = _build_tool(http_poster=fake_poster)
    result = tool.handler({
        "target": "eve",
        "message": "process the new audit findings",
        "coord_node_id": "node-42",
        "mode": "execute",
    })
    # Two POSTs: one to /sessions, one to /chat
    assert len(posted_calls) == 2
    chat_call = [c for c in posted_calls if c["url"].endswith("/chat")][0]
    body = chat_call["body"]
    assert body["agent"] == "eve"
    assert "[DIRECTIVE FROM AETHERIA" in body["message"]
    assert "coord:node-42" in body["message"]
    assert "process the new audit findings" in body["message"]
    assert result["target"] == "eve"
    assert result["response_content"] == "ack"
    assert result["coord_node_id"] == "node-42"
    assert result["finish_reason"] == "stop"


def test_direct_message_agent_query_mode_prefixes_query():
    """Query mode uses [QUERY FROM AETHERIA, ...] framing."""
    fake_poster, posted_calls = _ok_poster_factory(content="raw obs")
    tool = _build_tool(http_poster=fake_poster)
    tool.handler({
        "target": "eve",
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
        "target": "eve", "message": "x", "coord_node_id": "node-1",
    })  # no mode arg
    chat_call = [c for c in posted_calls if c["url"].endswith("/chat")][0]
    assert "[DIRECTIVE FROM AETHERIA" in chat_call["body"]["message"]


def test_direct_message_agent_writes_lattice_forensic_record_on_success():
    """Every successful call records a forensic record (node + edge) tying
    the direct message back to its coord node. The edge_writer receives
    sender, target, session_id, mode, and message head so the lattice
    captures enough to surface 'her recent directives to Scotty.'"""
    edge_calls = []
    def fake_edge(coord_node_id, sender, target, session_id, mode, message_head):
        edge_calls.append({
            "coord_node_id": coord_node_id,
            "sender": sender,
            "target": target,
            "session_id": session_id,
            "mode": mode,
            "message_head": message_head,
        })
        return ("msg-node-1", "edge-abc")
    fake_poster, _ = _ok_poster_factory()
    tool = _build_tool(edge_writer=fake_edge, http_poster=fake_poster)
    result = tool.handler({
        "target": "eve", "message": "do X",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert len(edge_calls) == 1
    call = edge_calls[0]
    assert call["coord_node_id"] == "node-1"
    assert call["sender"] == "aetheria"
    assert call["target"] == "eve"
    assert call["mode"] == "execute"
    assert "do X" in call["message_head"]
    assert result["edge_id"] == "edge-abc"
    assert result["message_node_id"] == "msg-node-1"


def test_direct_message_agent_continues_when_edge_writer_raises():
    """The chat already happened — a failed audit record can't undo the
    user-visible response. Edge failure logs + nulls the edge fields."""
    def boom_edge(*a, **kw):
        raise RuntimeError("FK constraint failed (simulating prod bug)")
    fake_poster, _ = _ok_poster_factory()
    tool = _build_tool(edge_writer=boom_edge, http_poster=fake_poster)
    result = tool.handler({
        "target": "eve", "message": "do X",
        "coord_node_id": "node-1", "mode": "execute",
    })
    # Tool result reflects the chat response, not the audit failure
    assert result["response_content"] == "ack"
    assert result["edge_id"] is None
    assert result["message_node_id"] is None


def test_direct_message_agent_returns_structured_error_when_rate_capped():
    """Rate-limit returns structured {error, retry_after_seconds}, not raise."""
    from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter
    limiter = DirectCommRateLimiter(per_minute_cap=0)  # always-capped
    fake_poster, posted_calls = _ok_poster_factory()
    tool = _build_tool(rate_limiter=limiter, http_poster=fake_poster)
    result = tool.handler({
        "target": "eve", "message": "x",
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
        "target": "eve", "message": "x",
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
        "target": "eve", "message": "x",
        "coord_node_id": "node-1", "mode": "execute",
    })
    assert result.get("error") == "dispatch_failed"
    assert "session" in result["message"].lower() or "500" in result["message"]
