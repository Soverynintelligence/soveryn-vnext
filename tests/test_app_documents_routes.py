"""Tests for /api/documents + /documents/* routes (D4).

Mirrors the pattern from test_app_api_memory_routes.py:
  - Inject ConversationStore + AgentLoop stubs into create_app
  - Seed a DocumentStore directly (bypassing agent tools)
  - Disable the localhost guard
  - Test JSON list / detail / download routes
"""

from __future__ import annotations

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.documents.store import DocumentStore


# ─── Shared stubs ────────────────────────────────────────────────────────────

@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )


# ─── Primary fixture: app with a seeded DocumentStore ────────────────────────

@pytest.fixture
def doc_store(tmp_path):
    """Seeded DocumentStore: two docs, one per agent."""
    store = DocumentStore(tmp_path / "docs.db")
    doc_id = store.create_document(
        agent="aetheria",
        title="Test Report",
        content="# Test\n\nHello world.",
        format="markdown",
        tags=["test", "report"],
    )
    store.create_document(
        agent="vett",
        title="Vett Draft",
        content="## Research\n\nSome findings.",
        format="markdown",
    )
    return store, doc_id  # also return the known id for detail/download tests


@pytest.fixture
def client(tmp_path, fake_chat, doc_store):
    store, _doc_id = doc_store
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    # Inject the pre-seeded document_store into extensions so the blueprint
    # reads the same data we seeded above.
    app.extensions["soveryn"]["document_store"] = store
    return app.test_client()


@pytest.fixture
def known_doc_id(doc_store):
    _store, doc_id = doc_store
    return doc_id


# ─── GET /api/documents (list) ───────────────────────────────────────────────

def test_list_documents_returns_200(client):
    resp = client.get("/api/documents")
    assert resp.status_code == 200


def test_list_documents_contains_seeded_docs(client, known_doc_id):
    resp = client.get("/api/documents")
    data = resp.get_json()
    assert "documents" in data
    assert len(data["documents"]) == 2


def test_list_documents_fields(client, known_doc_id):
    resp = client.get("/api/documents")
    data = resp.get_json()
    doc = next(d for d in data["documents"] if d["id"] == known_doc_id)
    assert doc["title"] == "Test Report"
    assert doc["agent"] == "aetheria"
    assert doc["status"] == "draft"
    assert "updated_at" in doc
    # content should NOT be in the list payload (bandwidth)
    assert "content" not in doc


def test_list_documents_newest_first(client):
    # The two docs were inserted in order; list should be newest first.
    resp = client.get("/api/documents")
    data = resp.get_json()
    docs = data["documents"]
    assert docs[0]["title"] == "Vett Draft"     # last inserted = newest
    assert docs[1]["title"] == "Test Report"


# ─── GET /api/documents/<id> (detail) ────────────────────────────────────────

def test_get_document_detail_200(client, known_doc_id):
    resp = client.get(f"/api/documents/{known_doc_id}")
    assert resp.status_code == 200


def test_get_document_detail_fields(client, known_doc_id):
    resp = client.get(f"/api/documents/{known_doc_id}")
    data = resp.get_json()
    assert data["id"] == known_doc_id
    assert data["title"] == "Test Report"
    assert data["agent"] == "aetheria"
    assert data["status"] == "draft"
    assert data["format"] == "markdown"
    assert "# Test" in data["content"]


def test_get_document_detail_404_missing(client):
    resp = client.get("/api/documents/does-not-exist")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"]["code"] == "not_found"


# ─── GET /documents/<id>/download?fmt=md ─────────────────────────────────────

def test_download_md_returns_200(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=md")
    assert resp.status_code == 200


def test_download_md_content_type(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=md")
    assert "text/markdown" in resp.content_type


def test_download_md_body_bytes(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=md")
    assert b"# Test" in resp.data


def test_download_md_content_disposition(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=md")
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd


def test_download_html_returns_200(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=html")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    assert b"<html" in resp.data


def test_download_bad_fmt_returns_400(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=badformat")
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"]["code"] == "invalid_format"


def test_download_missing_doc_returns_404(client):
    resp = client.get("/documents/no-such-id/download?fmt=md")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["error"]["code"] == "not_found"


def test_download_missing_fmt_defaults_md(client, known_doc_id):
    """Omitting ?fmt should default to md rather than 400."""
    resp = client.get(f"/documents/{known_doc_id}/download")
    assert resp.status_code == 200
    assert "text/markdown" in resp.content_type


# ─── GET /documents (UI page) ────────────────────────────────────────────────

def test_documents_ui_returns_html(client):
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


# ─── PDF / DOCX: integration only (skip by default) ─────────────────────────

@pytest.mark.integration
def test_download_pdf_returns_200(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=pdf")
    assert resp.status_code == 200
    assert resp.content_type == "application/pdf"
    assert resp.data[:4] == b"%PDF"


@pytest.mark.integration
def test_download_docx_returns_200(client, known_doc_id):
    resp = client.get(f"/documents/{known_doc_id}/download?fmt=docx")
    assert resp.status_code == 200
    ct = resp.content_type
    assert "wordprocessingml" in ct or "octet-stream" in ct
    # DOCX magic bytes: PK (zip)
    assert resp.data[:2] == b"PK"
