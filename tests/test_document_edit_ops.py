"""Delta-edit document ops (append / replace-passage).

Aetheria's heartbeat 502'd (2026-07-06) trying to save a growing document by
re-emitting the ENTIRE ~4KB body into an update_document tool call — the JSON
string truncated past her output-token budget ("missing closing quote"). The
fix: edit operations whose tool-call argument carries only the DELTA (a new
section, or one changed passage), never the whole document.
"""
import pytest

from soveryn.platform.documents.store import DocumentStore
from soveryn.platform.documents.tools import (
    build_append_to_document_tool,
    build_replace_in_document_tool,
)
from soveryn.platform.tools.registry import ToolArgError


def _store(tmp_path):
    return DocumentStore(tmp_path / "docs.db")


# ── store: append ──────────────────────────────────────────────────────────
def test_append_grows_content_with_paragraph_separation(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="# Head\n\nIntro.")
    assert s.append_to_document(did, "## Section 2\n\nMore.") is True
    assert s.get_document(did).content == "# Head\n\nIntro.\n\n## Section 2\n\nMore."


def test_append_missing_doc_returns_false(tmp_path):
    assert _store(tmp_path).append_to_document("nope", "x") is False


# ── store: replace ─────────────────────────────────────────────────────────
def test_replace_unique_passage(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="alpha BETA gamma")
    assert s.replace_in_document(did, "BETA", "delta") == "ok"
    assert s.get_document(did).content == "alpha delta gamma"


def test_replace_not_present(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="abc")
    assert s.replace_in_document(did, "zzz", "x") == "not_present"


def test_replace_ambiguous(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="x x x")
    assert s.replace_in_document(did, "x", "y") == "ambiguous"


def test_replace_missing_doc(tmp_path):
    assert _store(tmp_path).replace_in_document("nope", "a", "b") == "missing"


# ── tools ──────────────────────────────────────────────────────────────────
def test_append_tool_identity_and_effect(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="Base.")
    tool = build_append_to_document_tool(store=s, owner_agent="aetheria")
    assert tool.name == "append_to_document" and tool.owner == "aetheria"
    assert tool.handler({"id": did, "text": "Added."})["appended"] is True
    assert s.get_document(did).content == "Base.\n\nAdded."


def test_append_tool_rejects_missing_doc(tmp_path):
    tool = build_append_to_document_tool(store=_store(tmp_path), owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"id": "nope", "text": "x"})


def test_replace_tool_replaces(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="one OLD two")
    tool = build_replace_in_document_tool(store=s, owner_agent="aetheria")
    assert tool.name == "replace_in_document"
    assert tool.handler({"id": did, "old_text": "OLD", "new_text": "NEW"})["replaced"] is True
    assert s.get_document(did).content == "one NEW two"


def test_replace_tool_ambiguous_raises(tmp_path):
    s = _store(tmp_path)
    did = s.create_document(agent="aetheria", title="T", content="dup dup")
    tool = build_replace_in_document_tool(store=s, owner_agent="aetheria")
    with pytest.raises(ToolArgError):
        tool.handler({"id": did, "old_text": "dup", "new_text": "x"})
