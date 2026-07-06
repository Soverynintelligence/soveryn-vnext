"""TDD tests for soveryn.platform.documents.tools — document tool factories.

Tests are ordered to exercise the full lifecycle:
  create → list → read → update

Cross-agent collaboration is verified: tools are registered per-agent but
the underlying store is shared, so aetheria can list and edit vett's docs
and vice versa.

Run before implementing tools.py to confirm RED state:
  pytest tests/test_document_tools.py -v
"""

from __future__ import annotations

import pytest

from soveryn.platform.documents.store import DocumentStore
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path):
    return DocumentStore(tmp_path / "docs_test.db")


def _make_registry():
    from soveryn.config.runtime import ACTIVE_AGENTS
    return ToolRegistry(active_agents=ACTIVE_AGENTS, audit_hook=lambda e: None)


def _register_for(registry, store, owner_agent):
    from soveryn.platform.documents.tools import register_document_tools
    register_document_tools(registry, store=store, owner_agent=owner_agent)


def _invoke(registry, agent, tool, **kwargs):
    return registry.invoke(agent, tool, kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return _make_store(tmp_path)


@pytest.fixture
def registry():
    return _make_registry()


@pytest.fixture
def vett_registry(registry, store):
    _register_for(registry, store, "vett")
    return registry


@pytest.fixture
def both_registry(registry, store):
    _register_for(registry, store, "aetheria")
    _register_for(registry, store, "vett")
    return registry


# ---------------------------------------------------------------------------
# 1. Registration smoke test
# ---------------------------------------------------------------------------

def test_register_document_tools_for_vett(registry, store):
    _register_for(registry, store, "vett")
    names = {spec.name for spec in registry.iter_tools_for_agent("vett")}
    assert {"create_document", "list_documents", "read_document", "update_document"} <= names


def test_register_document_tools_for_aetheria(registry, store):
    _register_for(registry, store, "aetheria")
    names = {spec.name for spec in registry.iter_tools_for_agent("aetheria")}
    assert {"create_document", "list_documents", "read_document", "update_document"} <= names


# ---------------------------------------------------------------------------
# 2. create_document
# ---------------------------------------------------------------------------

def test_create_document_returns_id_title_status(vett_registry, store):
    result = _invoke(vett_registry, "vett", "create_document",
                     title="My Report", content="# Hello world")
    assert "id" in result
    assert result["title"] == "My Report"
    assert result["status"] == "draft"
    # Verify the row landed in the store
    doc = store.get_document(result["id"])
    assert doc is not None
    assert doc.agent == "vett"
    assert doc.title == "My Report"


def test_create_document_with_tags(vett_registry, store):
    result = _invoke(vett_registry, "vett", "create_document",
                     title="Tagged", content="body", tags=["ai", "research"])
    doc = store.get_document(result["id"])
    assert "ai" in doc.tags and "research" in doc.tags


def test_create_document_empty_title_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "create_document",
                title="", content="some content")


def test_create_document_whitespace_title_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "create_document",
                title="   ", content="some content")


def test_create_document_empty_content_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "create_document",
                title="Valid Title", content="")


def test_create_document_whitespace_content_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "create_document",
                title="Valid Title", content="   ")


# ---------------------------------------------------------------------------
# 3. list_documents — shared across agents
# ---------------------------------------------------------------------------

def test_list_documents_empty_store(vett_registry):
    result = _invoke(vett_registry, "vett", "list_documents")
    assert result == []


def test_list_documents_sees_own_doc(vett_registry):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Vett's doc", content="content here")
    listed = _invoke(vett_registry, "vett", "list_documents")
    ids = [d["id"] for d in listed]
    assert created["id"] in ids


def test_list_documents_shared_across_agents(both_registry):
    """Aetheria can see vett's doc and vice versa — shared document space."""
    vett_doc = _invoke(both_registry, "vett", "create_document",
                       title="Vett's Analysis", content="vett wrote this")
    aetheria_doc = _invoke(both_registry, "aetheria", "create_document",
                           title="Aetheria's Report", content="aetheria wrote this")

    # Vett's list sees both
    vett_list = _invoke(both_registry, "vett", "list_documents")
    vett_ids = {d["id"] for d in vett_list}
    assert vett_doc["id"] in vett_ids
    assert aetheria_doc["id"] in vett_ids

    # Aetheria's list sees both
    aetheria_list = _invoke(both_registry, "aetheria", "list_documents")
    aetheria_ids = {d["id"] for d in aetheria_list}
    assert vett_doc["id"] in aetheria_ids
    assert aetheria_doc["id"] in aetheria_ids


def test_list_documents_result_shape(vett_registry):
    """Each item in the list has the expected keys."""
    _invoke(vett_registry, "vett", "create_document",
            title="Shape check", content="body text")
    listed = _invoke(vett_registry, "vett", "list_documents")
    assert len(listed) == 1
    item = listed[0]
    for key in ("id", "title", "agent", "status", "updated_at"):
        assert key in item, f"missing key {key!r} in list result"


def test_list_documents_newest_first(vett_registry):
    """list_documents returns newest-first (by updated_at)."""
    import time
    r1 = _invoke(vett_registry, "vett", "create_document",
                 title="First", content="first content")
    time.sleep(0.01)
    r2 = _invoke(vett_registry, "vett", "create_document",
                 title="Second", content="second content")
    listed = _invoke(vett_registry, "vett", "list_documents")
    ids = [d["id"] for d in listed]
    assert ids.index(r2["id"]) < ids.index(r1["id"]), \
        "Second (newer) doc should appear before First (older)"


def test_list_documents_status_filter(vett_registry):
    """Optional status filter narrows results."""
    _invoke(vett_registry, "vett", "create_document",
            title="Draft Doc", content="draft content")
    listed_draft = _invoke(vett_registry, "vett", "list_documents", status="draft")
    assert all(d["status"] == "draft" for d in listed_draft)
    listed_final = _invoke(vett_registry, "vett", "list_documents", status="final")
    assert listed_final == []


# ---------------------------------------------------------------------------
# 4. read_document — any agent can read any doc
# ---------------------------------------------------------------------------

def test_read_document_returns_full_fields(vett_registry):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Full Read", content="full body text")
    result = _invoke(vett_registry, "vett", "read_document", id=created["id"])
    assert result["id"] == created["id"]
    assert result["title"] == "Full Read"
    assert result["content"] == "full body text"
    assert result["agent"] == "vett"
    assert result["status"] == "draft"
    assert "format" in result


def test_read_document_cross_agent(both_registry):
    """Aetheria can read vett's document."""
    vett_doc = _invoke(both_registry, "vett", "create_document",
                       title="Vett's Private Thoughts", content="not really private")
    result = _invoke(both_registry, "aetheria", "read_document", id=vett_doc["id"])
    assert result["id"] == vett_doc["id"]
    assert result["agent"] == "vett"


def test_read_document_not_found_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "read_document",
                id="00000000-0000-0000-0000-000000000000")


# ---------------------------------------------------------------------------
# 5. update_document — any agent can update any doc
# ---------------------------------------------------------------------------

def test_update_document_title(vett_registry, store):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Original Title", content="body")
    result = _invoke(vett_registry, "vett", "update_document",
                     id=created["id"], title="Updated Title")
    assert result["updated"] is True
    doc = store.get_document(created["id"])
    assert doc.title == "Updated Title"


def test_update_document_content(vett_registry, store):
    """Full-body rewrite via update_document is a first-class capability."""
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Title", content="original body")
    _invoke(vett_registry, "vett", "update_document",
            id=created["id"], content="revised body")
    assert store.get_document(created["id"]).content == "revised body"


def test_replace_in_document_edits_body(vett_registry, store):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Title", content="original body")
    _invoke(vett_registry, "vett", "replace_in_document",
            id=created["id"], old_text="original", new_text="revised")
    assert store.get_document(created["id"]).content == "revised body"


def test_update_document_status(vett_registry, store):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Title", content="body")
    _invoke(vett_registry, "vett", "update_document",
            id=created["id"], status="final")
    doc = store.get_document(created["id"])
    assert doc.status == "final"


def test_document_cross_agent_body_edit(both_registry, store):
    """Aetheria can edit vett's document body via append (collaborative)."""
    vett_doc = _invoke(both_registry, "vett", "create_document",
                       title="Joint Draft", content="vett's draft")
    _invoke(both_registry, "aetheria", "append_to_document",
            id=vett_doc["id"], text="aetheria's addition")
    doc = store.get_document(vett_doc["id"])
    assert "vett's draft" in doc.content and "aetheria's addition" in doc.content


def test_update_document_returns_id(vett_registry):
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Title", content="body")
    result = _invoke(vett_registry, "vett", "update_document",
                     id=created["id"], title="New Title")
    assert result["id"] == created["id"]


def test_update_document_not_found_raises(vett_registry):
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "update_document",
                id="00000000-0000-0000-0000-000000000000",
                title="irrelevant")


def test_update_document_nothing_to_update_raises(vett_registry):
    """Calling update with no fields to change should raise ToolArgError."""
    created = _invoke(vett_registry, "vett", "create_document",
                      title="Title", content="body")
    with pytest.raises(ToolArgError):
        _invoke(vett_registry, "vett", "update_document", id=created["id"])
