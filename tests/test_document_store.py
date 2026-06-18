"""Tests for DocumentStore — D1 of the documents capability."""

from __future__ import annotations

import pytest

from soveryn.platform.documents.store import Document, DocumentStore


def test_create_and_get_document(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(
        agent="vett",
        title="FCC Q3 IPL draft",
        content="# Draft\n...",
        tags=["fcc", "draft"],
    )
    assert isinstance(doc_id, str) and len(doc_id) > 0

    doc = store.get_document(doc_id)
    assert doc is not None
    assert isinstance(doc, Document)
    assert doc.id == doc_id
    assert doc.agent == "vett"
    assert doc.title == "FCC Q3 IPL draft"
    assert doc.content == "# Draft\n..."
    assert doc.format == "markdown"
    assert doc.status == "draft"
    assert doc.tags == ("fcc", "draft")
    assert doc.created_at != ""
    assert doc.updated_at != ""
    assert doc.created_at == doc.updated_at


def test_get_document_missing(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    assert store.get_document("nope") is None


def test_list_documents_agent_filter(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(
        agent="vett",
        title="FCC Q3 IPL draft",
        content="# Draft\n...",
        tags=["fcc", "draft"],
    )

    vett_docs = store.list_documents(agent="vett")
    assert len(vett_docs) == 1
    assert vett_docs[0].id == doc_id

    aetheria_docs = store.list_documents(agent="aetheria")
    assert aetheria_docs == ()


def test_list_documents_no_filter(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    id1 = store.create_document(agent="vett", title="Doc 1", content="a")
    id2 = store.create_document(agent="aetheria", title="Doc 2", content="b")

    all_docs = store.list_documents()
    assert len(all_docs) == 2
    ids = {d.id for d in all_docs}
    assert {id1, id2} == ids


def test_list_documents_status_filter(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    draft_id = store.create_document(agent="vett", title="Draft", content="d")
    store.update_document(draft_id, status="final")
    final_id = draft_id

    draft2_id = store.create_document(agent="vett", title="Draft2", content="d2")

    finals = store.list_documents(status="final")
    assert len(finals) == 1
    assert finals[0].id == final_id

    drafts = store.list_documents(status="draft")
    assert len(drafts) == 1
    assert drafts[0].id == draft2_id


def test_update_document(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(
        agent="vett",
        title="FCC Q3 IPL draft",
        content="# Draft\n...",
        tags=["fcc", "draft"],
    )
    original = store.get_document(doc_id)
    assert original is not None

    result = store.update_document(doc_id, status="final", content="# Final")
    assert result is True

    updated = store.get_document(doc_id)
    assert updated is not None
    assert updated.status == "final"
    assert updated.content == "# Final"
    assert updated.title == "FCC Q3 IPL draft"  # unchanged
    assert updated.tags == ("fcc", "draft")       # unchanged
    assert updated.updated_at != original.updated_at


def test_update_document_missing(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    result = store.update_document("nope", status="x")
    assert result is False


def test_document_tags_none(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(agent="aetheria", title="No tags", content="x")
    doc = store.get_document(doc_id)
    assert doc is not None
    assert doc.tags == ()


def test_list_documents_newest_first(tmp_path):
    import time
    store = DocumentStore(tmp_path / "docs.db")
    id1 = store.create_document(agent="vett", title="First", content="a")
    time.sleep(0.01)
    id2 = store.create_document(agent="vett", title="Second", content="b")

    docs = store.list_documents(agent="vett")
    assert docs[0].id == id2
    assert docs[1].id == id1


def test_schema_idempotent(tmp_path):
    """Creating two DocumentStore instances on the same db must not fail."""
    db = tmp_path / "docs.db"
    s1 = DocumentStore(db)
    s1.create_document(agent="vett", title="T", content="c")
    s2 = DocumentStore(db)
    docs = s2.list_documents()
    assert len(docs) == 1


def test_document_is_frozen(tmp_path):
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(agent="vett", title="T", content="c")
    doc = store.get_document(doc_id)
    assert doc is not None
    with pytest.raises((AttributeError, TypeError)):
        doc.status = "mutated"  # type: ignore[misc]
