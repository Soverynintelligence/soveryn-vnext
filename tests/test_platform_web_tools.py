"""Tests for soveryn.platform.web — search parser, SSRF guard, tool factories.

Network is mocked throughout. The live SearXNG instance is exercised only
by a separate integration probe (not part of the unit suite).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from soveryn.platform.tools.registry import ToolArgError, ToolRegistry
from soveryn.platform.web.fetch import (
    DEFAULT_MAX_CHARS,
    FetchError,
    SSRFError,
    _guard_against_ssrf,
)
from soveryn.platform.web.search import (
    SearchError,
    SearchResult,
    _parse_results,
)
from soveryn.platform.web.tools import (
    build_fetch_url_tool,
    build_web_search_tool,
    register_web_tools,
)


# ─── Search response parser ─────────────────────────────────────────────────

def test_parse_results_returns_typed_results():
    payload = {
        "query": "test",
        "results": [
            {"url": "https://a.com/", "title": "A", "content": "body of A", "engine": "google"},
            {"url": "https://b.com/", "title": "B", "content": "body of B", "engine": "bing"},
        ],
    }
    out = _parse_results(payload, max_results=5)
    assert len(out) == 2
    assert out[0] == SearchResult(title="A", url="https://a.com/", snippet="body of A", engine="google")
    assert out[1].title == "B"


def test_parse_results_truncates_to_max():
    payload = {
        "results": [
            {"url": f"https://r{i}.com/", "title": f"R{i}", "content": "x", "engine": "e"}
            for i in range(10)
        ],
    }
    out = _parse_results(payload, max_results=3)
    assert len(out) == 3


def test_parse_results_skips_malformed_entries():
    payload = {
        "results": [
            {"url": "https://a.com/", "title": "good", "content": "x", "engine": "e"},
            {"url": "https://b.com/"},  # missing title
            "not-a-dict",                # entirely wrong type
            {"title": "no-url"},         # missing url
            {"url": "https://c.com/", "title": "good2", "content": "x", "engine": "e"},
        ],
    }
    out = _parse_results(payload, max_results=10)
    assert len(out) == 2
    assert out[0].title == "good"
    assert out[1].title == "good2"


def test_parse_results_rejects_non_dict_payload():
    with pytest.raises(SearchError):
        _parse_results("not a dict", max_results=5)


def test_parse_results_rejects_missing_results_key():
    with pytest.raises(SearchError):
        _parse_results({"query": "test"}, max_results=5)


# ─── SSRF guard ─────────────────────────────────────────────────────────────

def test_ssrf_guard_blocks_localhost():
    with pytest.raises(SSRFError):
        _guard_against_ssrf("127.0.0.1")


def test_ssrf_guard_blocks_ipv6_loopback():
    with pytest.raises(SSRFError):
        _guard_against_ssrf("::1")


def test_ssrf_guard_blocks_private_ranges():
    for ip in ("10.0.0.1", "192.168.1.1", "172.16.0.1"):
        with pytest.raises(SSRFError):
            _guard_against_ssrf(ip)


def test_ssrf_guard_blocks_link_local():
    with pytest.raises(SSRFError):
        _guard_against_ssrf("169.254.169.254")  # AWS instance metadata, classic SSRF target


def test_ssrf_guard_blocks_multicast_and_reserved():
    with pytest.raises(SSRFError):
        _guard_against_ssrf("224.0.0.1")  # multicast


def test_ssrf_guard_allows_public_literal_ip():
    # Cloudflare's public DNS — clearly public, should pass.
    _guard_against_ssrf("1.1.1.1")  # no raise


def test_ssrf_guard_resolves_hostname_and_blocks_if_private():
    """A hostname that resolves to a private IP must be blocked."""
    with patch("socket.getaddrinfo") as mock_resolve:
        mock_resolve.return_value = [(2, 1, 6, "", ("10.0.0.5", 0))]
        with pytest.raises(SSRFError):
            _guard_against_ssrf("internal.corp.local")


def test_ssrf_guard_blocks_if_ANY_resolved_ip_is_forbidden():
    """If a hostname resolves to one public AND one private IP, block."""
    with patch("socket.getaddrinfo") as mock_resolve:
        mock_resolve.return_value = [
            (2, 1, 6, "", ("8.8.8.8", 0)),       # public
            (2, 1, 6, "", ("127.0.0.1", 0)),     # loopback
        ]
        with pytest.raises(SSRFError):
            _guard_against_ssrf("split-horizon.example")


# ─── Tool factory: web_search arg validation ────────────────────────────────

def test_web_search_tool_rejects_empty_query():
    tool = build_web_search_tool(searxng_url="http://x", owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"query": ""})
    with pytest.raises(ToolArgError):
        tool.handler({})


def test_web_search_tool_rejects_bad_max_results():
    tool = build_web_search_tool(searxng_url="http://x", owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"query": "x", "max_results": 0})
    with pytest.raises(ToolArgError):
        tool.handler({"query": "x", "max_results": 21})
    with pytest.raises(ToolArgError):
        tool.handler({"query": "x", "max_results": "not-int"})


def test_web_search_tool_wraps_search_failure_as_structured_error():
    """SearchError from the client becomes a {error,message,results} result —
    NOT a thrown exception. The model gets to see and respond to it."""
    tool = build_web_search_tool(searxng_url="http://x", owner_agent="aetheria")
    with patch("soveryn.platform.web.tools.search_via_searxng") as mock_search:
        mock_search.side_effect = SearchError("connection refused")
        result = tool.handler({"query": "anything"})
    assert result["error"] == "search_failed"
    assert "connection refused" in result["message"]
    assert result["results"] == []


def test_web_search_tool_returns_structured_results():
    tool = build_web_search_tool(searxng_url="http://x", owner_agent="aetheria")
    with patch("soveryn.platform.web.tools.search_via_searxng") as mock_search:
        mock_search.return_value = (
            SearchResult(title="t", url="https://u", snippet="s", engine="google"),
        )
        result = tool.handler({"query": "anything"})
    assert result["engine"] == "searxng"
    assert result["results"] == [
        {"title": "t", "url": "https://u", "snippet": "s", "source": "google"}
    ]


# ─── Tool factory: fetch_url arg validation ─────────────────────────────────

def test_fetch_url_tool_rejects_empty_url():
    tool = build_fetch_url_tool(owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"url": ""})
    with pytest.raises(ToolArgError):
        tool.handler({})


def test_fetch_url_tool_rejects_bad_max_chars():
    tool = build_fetch_url_tool(owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"url": "https://x", "max_chars": 0})
    with pytest.raises(ToolArgError):
        tool.handler({"url": "https://x", "max_chars": 100_000})


def test_fetch_url_tool_surfaces_ssrf_block_as_structured_error():
    tool = build_fetch_url_tool(owner_agent="aetheria")
    with patch("soveryn.platform.web.tools.fetch_and_extract") as mock_fetch:
        mock_fetch.side_effect = SSRFError("refusing localhost")
        result = tool.handler({"url": "http://127.0.0.1/"})
    assert result["error"] == "ssrf_blocked"
    assert "localhost" in result["message"]


def test_fetch_url_tool_surfaces_fetch_failure_as_structured_error():
    tool = build_fetch_url_tool(owner_agent="aetheria")
    with patch("soveryn.platform.web.tools.fetch_and_extract") as mock_fetch:
        mock_fetch.side_effect = FetchError("404")
        result = tool.handler({"url": "https://example.com/missing"})
    assert result["error"] == "fetch_failed"


# ─── register_web_tools ─────────────────────────────────────────────────────

def test_register_web_tools_adds_both_tools_for_one_agent():
    registry = ToolRegistry()
    register_web_tools(registry, searxng_url="http://x", owner_agent="aetheria")
    schemas = registry.iter_tools_for_agent("aetheria")
    names = {s.name for s in schemas}
    assert "web_search" in names
    assert "fetch_url" in names


def test_register_web_tools_does_not_leak_to_other_agents():
    registry = ToolRegistry()
    register_web_tools(registry, searxng_url="http://x", owner_agent="aetheria")
    vett_tools = {s.name for s in registry.iter_tools_for_agent("vett")}
    assert "web_search" not in vett_tools
    assert "fetch_url" not in vett_tools
