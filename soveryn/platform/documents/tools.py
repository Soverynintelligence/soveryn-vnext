"""Document tool factories for SOVERYN vNext.

Mirrors the pattern from soveryn.platform.library.tools exactly.

All four tools operate on a shared DocumentStore — there is no per-agent
partitioning. Aetheria and Vett can create, list, read, and edit any
document regardless of who authored it. Attribution is preserved via the
`agent` column on each row.

Scotty does NOT get these tools — deliverable document production is
Aetheria + Vett's surface; Scotty's surface is bounded mechanical tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from soveryn.platform.documents.store import DocumentStore
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


# ---------------------------------------------------------------------------
# build_create_document_tool
# ---------------------------------------------------------------------------

def build_create_document_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Tool that creates a new deliverable document in the shared store.

    The document is authored by ``owner_agent`` but visible and editable by
    every agent that has access to the shared DocumentStore.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        title = args.get("title", "")
        if not isinstance(title, str) or not title.strip():
            raise ToolArgError("title must be a non-empty string")
        content = args.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ToolArgError("content must be a non-empty string")
        tags_arg = args.get("tags") or []
        if not isinstance(tags_arg, list) or not all(isinstance(t, str) for t in tags_arg):
            raise ToolArgError("tags must be a list of strings (omit if none)")

        doc_id = store.create_document(
            agent=owner_agent,
            title=title.strip(),
            content=content.strip(),
            tags=list(tags_arg) if tags_arg else None,
        )
        return {
            "id": doc_id,
            "title": title.strip(),
            "status": "draft",
        }

    return ToolSpec(
        name="create_document",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": (
                        "Short descriptive title for the document. Jon can download "
                        "deliverables as Markdown, HTML, PDF, or DOCX — the title "
                        "becomes the filename, so keep it clean and specific "
                        "(e.g. 'Q2 Intelligence Brief', 'Project Proposal — EU Grant')."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Full Markdown body of the document. Use standard Markdown "
                        "headings, lists, and code fences. This is the canonical "
                        "text; the render pipeline converts it to other formats on "
                        "download. Write the complete document here, not a summary."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional list of short string tags for grouping and later "
                        "discovery (e.g. ['grant', 'eu', 'q2-2026']). Not required."
                    ),
                },
            },
            "required": ["title", "content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Create a new deliverable document in the shared document store. "
            "Documents are Markdown-authored and can be downloaded by Jon as "
            "Markdown, HTML, PDF, or DOCX. All agents share the same document "
            "space — the author agent is recorded on each document for attribution "
            "but any agent can read or edit any document. New documents start in "
            "'draft' status; use update_document to advance to 'final' or 'archived'."
        ),
    )


# ---------------------------------------------------------------------------
# build_list_documents_tool
# ---------------------------------------------------------------------------

def build_list_documents_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Tool that lists all documents in the shared store, newest first.

    The optional ``status`` filter narrows by lifecycle state. The calling
    agent is irrelevant to the result — the full shared space is always
    visible.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        status = args.get("status") or None
        if status is not None and not isinstance(status, str):
            raise ToolArgError("status must be a string (e.g. 'draft', 'final', 'archived')")
        docs = store.list_documents(agent=None, status=status)
        return [
            {
                "id": doc.id,
                "title": doc.title,
                "agent": doc.agent,
                "status": doc.status,
                "updated_at": doc.updated_at,
            }
            for doc in docs
        ]

    return ToolSpec(
        name="list_documents",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": (
                        "Optional lifecycle filter. Pass 'draft' to see in-progress "
                        "documents, 'final' to see finished deliverables, "
                        "'archived' to see archived ones. Omit to see all documents "
                        "regardless of status. Results are newest-first by update time."
                    ),
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List all deliverable documents in the shared document space, newest "
            "first. Documents from all agents (Aetheria and Vett) appear together — "
            "this is a shared workspace. Optionally filter by status "
            "('draft', 'final', 'archived'). Returns id, title, authoring agent, "
            "status, and last-updated timestamp for each document. Use "
            "read_document to fetch the full content of a specific document."
        ),
    )


# ---------------------------------------------------------------------------
# build_read_document_tool
# ---------------------------------------------------------------------------

def build_read_document_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Tool that returns the full content of any document by id."""

    def handler(args: Mapping[str, Any]) -> Any:
        doc_id = args.get("id", "")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ToolArgError("id must be a non-empty string")
        doc = store.get_document(doc_id.strip())
        if doc is None:
            raise ToolArgError(f"Document {doc_id!r} not found")
        return {
            "id": doc.id,
            "title": doc.title,
            "agent": doc.agent,
            "status": doc.status,
            "format": doc.format,
            "content": doc.content,
        }

    return ToolSpec(
        name="read_document",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": (
                        "UUID of the document to retrieve. Obtain this from "
                        "create_document or list_documents."
                    ),
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Fetch the full content of a specific deliverable document by its id. "
            "Returns id, title, authoring agent, lifecycle status, format, and the "
            "full Markdown content. Any agent can read any document — the store is "
            "shared. Use list_documents first if you need to find a document id."
        ),
    )


# ---------------------------------------------------------------------------
# build_update_document_tool
# ---------------------------------------------------------------------------

def build_update_document_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Tool that edits any document's title, content, or status.

    At least one of ``title``, ``content``, or ``status`` must be supplied.
    Passing none of them is a ToolArgError — there is nothing to update.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        doc_id = args.get("id", "")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ToolArgError("id must be a non-empty string")

        title = args.get("title")
        content = args.get("content")
        status = args.get("status")

        # Require at least one update field
        if title is None and content is None and status is None:
            raise ToolArgError(
                "At least one of 'title', 'content', or 'status' must be provided"
            )

        # Verify document exists before attempting the update
        if store.get_document(doc_id.strip()) is None:
            raise ToolArgError(f"Document {doc_id!r} not found")

        updated = store.update_document(
            doc_id.strip(),
            title=title,
            content=content,
            status=status,
        )
        return {
            "id": doc_id.strip(),
            "updated": updated,
        }

    return ToolSpec(
        name="update_document",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "UUID of the document to update.",
                },
                "title": {
                    "type": "string",
                    "description": (
                        "New title for the document. Omit to leave the current "
                        "title unchanged."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Replacement Markdown body for the document. Omit to "
                        "leave the current content unchanged. This replaces the "
                        "entire body — include everything you want to preserve. "
                        "For a LONG document, do NOT rewrite the whole body here "
                        "(it can exceed the output limit and fail) — use "
                        "append_to_document to add a section or replace_in_document "
                        "to change one passage instead."
                    ),
                },
                "status": {
                    "type": "string",
                    "description": (
                        "New lifecycle status. Use 'draft' while working, "
                        "'final' when the document is ready for Jon to download, "
                        "'archived' to retire a document without deleting it."
                    ),
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Edit an existing deliverable document's title, content, or lifecycle "
            "status. Any agent can edit any document — this is a collaborative "
            "shared workspace. Supply at least one of title, content, or status; "
            "the updated_at timestamp is bumped automatically. Returns "
            "{id, updated: bool}. ToolArgError if the document is not found or if "
            "no update fields are provided."
        ),
    )


# ---------------------------------------------------------------------------
# build_append_to_document_tool / build_replace_in_document_tool
# ---------------------------------------------------------------------------
# Delta edits: the tool-call argument carries only the NEW section or the one
# changed passage — never the whole (growing) document. Fix for the 2026-07-06
# truncation ("missing closing quote") where re-emitting a full ~4KB body into
# an update_document call exceeded the output-token budget and the tool failed.

def build_append_to_document_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Append a new section to a document; only the new text is sent."""

    def handler(args: Mapping[str, Any]) -> Any:
        doc_id = args.get("id", "")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ToolArgError("id must be a non-empty string")
        text = args.get("text", "")
        if not isinstance(text, str) or not text.strip():
            raise ToolArgError("text must be a non-empty string")
        if not store.append_to_document(doc_id.strip(), text):
            raise ToolArgError(f"Document {doc_id!r} not found")
        return {"id": doc_id.strip(), "appended": True}

    return ToolSpec(
        name="append_to_document",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "UUID of the document to append to."},
                "text": {
                    "type": "string",
                    "description": (
                        "The new Markdown text to add to the END of the document. "
                        "Send ONLY this new section — never the whole document."
                    ),
                },
            },
            "required": ["id", "text"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Add a new section to the END of an existing document. You send ONLY "
            "the new text, not the whole document — so it works no matter how long "
            "the document already is. PREFER this over update_document to grow a "
            "document: rewriting a long body in one call can exceed the output "
            "limit and fail."
        ),
    )


def build_replace_in_document_tool(*, store: DocumentStore, owner_agent: str) -> ToolSpec:
    """Replace one exact passage in a document; only the passage is sent."""

    def handler(args: Mapping[str, Any]) -> Any:
        doc_id = args.get("id", "")
        if not isinstance(doc_id, str) or not doc_id.strip():
            raise ToolArgError("id must be a non-empty string")
        old = args.get("old_text", "")
        new = args.get("new_text", "")
        if not isinstance(old, str) or not old:
            raise ToolArgError("old_text must be a non-empty string")
        if not isinstance(new, str):
            raise ToolArgError("new_text must be a string")
        status = store.replace_in_document(doc_id.strip(), old, new)
        if status == "missing":
            raise ToolArgError(f"Document {doc_id!r} not found")
        if status == "not_present":
            raise ToolArgError("old_text was not found — copy it exactly, including whitespace")
        if status == "ambiguous":
            raise ToolArgError(
                "old_text appears more than once — include more surrounding "
                "context so it uniquely identifies one passage"
            )
        return {"id": doc_id.strip(), "replaced": True}

    return ToolSpec(
        name="replace_in_document",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "UUID of the document to edit."},
                "old_text": {
                    "type": "string",
                    "description": (
                        "The exact passage to replace — must appear exactly once. "
                        "Send only this passage, not the whole document."
                    ),
                },
                "new_text": {"type": "string", "description": "The replacement text."},
            },
            "required": ["id", "old_text", "new_text"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Edit a document by replacing one specific passage. Send only the exact "
            "old passage and its replacement — never the whole document. old_text "
            "must match exactly and appear exactly once. PREFER this over "
            "update_document for targeted edits to a long document."
        ),
    )


# ---------------------------------------------------------------------------
# register_document_tools
# ---------------------------------------------------------------------------

def register_document_tools(
    registry: ToolRegistry,
    *,
    store: DocumentStore,
    owner_agent: str,
) -> None:
    """Register all document tools for one agent.

    Call once per agent that should have document capability (aetheria, vett).
    The underlying ``store`` is shared — multiple calls with different
    ``owner_agent`` values point to the same SQLite file.
    """
    registry.register(build_create_document_tool(store=store, owner_agent=owner_agent))
    registry.register(build_list_documents_tool(store=store, owner_agent=owner_agent))
    registry.register(build_read_document_tool(store=store, owner_agent=owner_agent))
    registry.register(build_update_document_tool(store=store, owner_agent=owner_agent))
    registry.register(build_append_to_document_tool(store=store, owner_agent=owner_agent))
    registry.register(build_replace_in_document_tool(store=store, owner_agent=owner_agent))
