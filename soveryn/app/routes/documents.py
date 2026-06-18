"""SOVERYN vNext — /documents + /api/documents/* routes (D4).

Surfaces the DocumentStore for Jon to browse, view, and download agent
deliverables (Aetheria + Vett reports / drafts) as md / html / pdf / docx.

Routes:
  GET /documents                    — documents.html UI page
  GET /api/documents                — JSON list (id, title, agent, status, updated_at)
  GET /api/documents/<id>           — JSON detail (all fields + content)
  GET /documents/<id>/download?fmt  — file download (md/html/pdf/docx); default fmt=md

document_store is read from app.extensions["soveryn"]["document_store"] per
the established pattern in api_memory.py / chat.py.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, make_response, request

from soveryn.platform.documents.render import render_document, _FMT_MIME

bp = Blueprint("documents", __name__)

_TEMPLATE = Path(__file__).parent.parent / "templates" / "documents.html"

_VALID_FMTS = frozenset(_FMT_MIME.keys())  # md, html, pdf, docx
_DEFAULT_FMT = "md"


def _err(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def _get_store():
    state = current_app.extensions["soveryn"]
    return state["document_store"]


# ─── UI page ─────────────────────────────────────────────────────────────────

@bp.get("/documents")
def documents_ui():
    if not _TEMPLATE.is_file():
        return _err("ui_unavailable", f"Documents template missing at {_TEMPLATE}", 500)
    html = _TEMPLATE.read_text(encoding="utf-8")
    resp = make_response(html, 200)
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["X-SOVERYN-UI-Source"] = "vnext-native"
    return resp


# ─── API: list ───────────────────────────────────────────────────────────────

@bp.get("/api/documents")
def api_documents_list():
    """Return all documents newest-first (no content field to keep payload small)."""
    store = _get_store()
    agent_filter = request.args.get("agent") or None
    status_filter = request.args.get("status") or None
    docs = store.list_documents(agent=agent_filter, status=status_filter)
    return jsonify({
        "documents": [
            {
                "id":         d.id,
                "title":      d.title,
                "agent":      d.agent,
                "status":     d.status,
                "format":     d.format,
                "tags":       list(d.tags),
                "updated_at": d.updated_at,
                "created_at": d.created_at,
            }
            for d in docs
        ],
    }), 200


# ─── API: detail ─────────────────────────────────────────────────────────────

@bp.get("/api/documents/<doc_id>")
def api_document_detail(doc_id: str):
    store = _get_store()
    doc = store.get_document(doc_id)
    if doc is None:
        return _err("not_found", f"No document with id {doc_id!r}", 404)
    return jsonify({
        "id":         doc.id,
        "title":      doc.title,
        "agent":      doc.agent,
        "status":     doc.status,
        "format":     doc.format,
        "content":    doc.content,
        "tags":       list(doc.tags),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }), 200


# ─── Download ────────────────────────────────────────────────────────────────

@bp.get("/documents/<doc_id>/download")
def document_download(doc_id: str):
    """Render and download the document in the requested format.

    ?fmt=md|html|pdf|docx  (default: md)
    """
    store = _get_store()
    doc = store.get_document(doc_id)
    if doc is None:
        return _err("not_found", f"No document with id {doc_id!r}", 404)

    fmt = (request.args.get("fmt") or _DEFAULT_FMT).lower().strip()
    if fmt not in _VALID_FMTS:
        return _err(
            "invalid_format",
            f"Unknown format {fmt!r}. Supported: {sorted(_VALID_FMTS)}",
            400,
        )

    try:
        data, mime = render_document(doc.content, fmt, title=doc.title)
    except ValueError as exc:
        # render_document raises ValueError for unknown fmt — shouldn't happen
        # given the guard above, but be safe.
        return _err("invalid_format", str(exc), 400)
    except RuntimeError as exc:
        return _err("render_error", str(exc), 500)

    # Sanitize title for Content-Disposition filename
    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in doc.title)
    safe_title = safe_title.strip().replace(" ", "_") or "document"
    filename = f"{safe_title}.{fmt}"

    resp = make_response(data, 200)
    resp.headers["Content-Type"] = mime
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Content-Length"] = str(len(data))
    return resp
