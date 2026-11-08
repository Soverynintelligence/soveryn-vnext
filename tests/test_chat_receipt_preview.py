"""Chat receipt uploads preview only. Session first. Token required to book.

Isolated temp books. Never the house ledgers.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path

import pytest

from flask import Flask

from soveryn.agents.loop import AgentLoop
from soveryn.app.routes.chat import bp as chat_bp
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse, StreamChunk
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.intake.pdf import ExtractResult
from soveryn.platform.ledgers.auto import apply_chat_receipt, receipt_file_book
from soveryn.platform.ledgers.books import CSV_FIELDS, load_rows
from soveryn.platform.ledgers.ingest import ingest_path, peek_confirm_token

from tests.test_ledgers import STOREFRONT_BARE

PREVIEW_MSG = "Preview this CWG receipt only; do not book or file anything."


def _jpeg_data_url() -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (255, 255, 255)).save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_storefront(_path: Path) -> ExtractResult:
    return ExtractResult(
        status="ok",
        text=STOREFRONT_BARE,
        page_count=1,
        pages_with_text=1,
        chars=len(STOREFRONT_BARE),
        source_name="chat.jpg",
    )


def _isolate_books(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    header = ",".join(CSV_FIELDS) + "\n"
    soveryn_csv = tmp_path / "s.csv"
    cwg_csv = tmp_path / "c.csv"
    soveryn_csv.write_text(header, encoding="utf-8")
    cwg_csv.write_text(header, encoding="utf-8")
    books = {"soveryn": soveryn_csv, "cwg": cwg_csv}
    ev = {"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"}
    monkeypatch.setattr(
        "soveryn.platform.ledgers.ingest._registered_book_paths", lambda: books
    )
    monkeypatch.setattr(
        "soveryn.platform.ledgers.ingest._registered_evidence_roots", lambda: ev
    )
    monkeypatch.setattr(
        "soveryn.platform.ledgers.ingest.extract_receipt_path", _extract_storefront
    )
    return soveryn_csv, cwg_csv


class _FakeChat:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server})
        return ChatResponse(
            content="ok",
            finish_reason="stop",
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


class _StreamFn:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server})

        def _g():
            yield StreamChunk(
                delta="ok", finish_reason="stop", tool_calls_delta=None, usage=None, raw={}
            )

        return _g()


@pytest.fixture
def app_state(tmp_path, monkeypatch):
    _isolate_books(tmp_path, monkeypatch)
    conv = ConversationStore(tmp_path / "conv.db")
    fake = _FakeChat()
    stream = _StreamFn()
    loops = {
        name: AgentLoop(name, conv, chat_fn=fake, stream_fn=stream)
        for name in ACTIVE_AGENTS
    }
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    app.config["DEFER_CHAT"] = False
    app.register_blueprint(chat_bp)
    app.extensions["soveryn"] = {
        "conv_store": conv,
        "agent_loops": loops,
        "env": None,
    }
    return {
        "client": app.test_client(),
        "conv": conv,
        "fake": fake,
        "stream": stream,
        "tmp": tmp_path,
        "cwg": tmp_path / "c.csv",
        "sov": tmp_path / "s.csv",
    }


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


def _new_session(conv: ConversationStore, agent="aetheria") -> str:
    return conv.new_session(agent)


def _user_text(request) -> str:
    content = request.messages[-1].content
    if isinstance(content, str):
        return content
    bits = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            bits.append(part.get("text") or "")
        elif isinstance(part, str):
            bits.append(part)
    return "\n".join(bits)


def test_cwg_in_preview_wording_classifies_but_is_not_authorization():
    assert receipt_file_book(PREVIEW_MSG) == "cwg"
    assert receipt_file_book("draft an IG post for CWG") is None


def test_apply_chat_receipt_preview_writes_nothing(tmp_path, monkeypatch):
    sov, cwg = _isolate_books(tmp_path, monkeypatch)
    block = apply_chat_receipt(PREVIEW_MSG, (_jpeg_data_url(),))
    assert block is not None
    assert "action=preview" in block
    assert "PREVIEW ONLY" in block
    assert "chat token cannot book" in block
    assert "confirm_token=" in block
    assert load_rows(cwg) == []
    assert load_rows(sov) == []
    assert list((tmp_path / "ev-c").rglob("*")) == []
    assert list((tmp_path / "ev-s").rglob("*")) == []


def test_chat_actor_cannot_book_even_if_confirm_true(tmp_path, monkeypatch):
    sov, cwg = _isolate_books(tmp_path, monkeypatch)
    photo = tmp_path / "chat.jpg"
    photo.write_bytes(b"fake")
    result = ingest_path(
        photo,
        book="cwg",
        confirm=True,
        actor="chat_receipt_preview",
        extract=_extract_storefront,
        books={"soveryn": sov, "cwg": cwg},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
    )
    assert result.action == "preview"
    assert result.confirm_token
    assert load_rows(cwg) == []


def test_chat_preview_token_cannot_book(tmp_path, monkeypatch):
    sov, cwg = _isolate_books(tmp_path, monkeypatch)
    block = apply_chat_receipt(PREVIEW_MSG, (_jpeg_data_url(),))
    assert "chat token cannot book" in (block or "")
    token = re.search(r"confirm_token=(\S+)", block or "").group(1)
    payload = peek_confirm_token(token)
    assert payload is not None
    assert payload["source"] == "chat_preview"
    path = Path(payload["path"])
    books = {"soveryn": sov, "cwg": cwg}
    ev = {"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"}
    blocked = ingest_path(
        path,
        book="cwg",
        confirm=True,
        confirm_token=token,
        extract=_extract_storefront,
        books=books,
        evidence_roots=ev,
    )
    assert blocked.action == "blocked"
    assert load_rows(cwg) == []
    preview = ingest_path(
        path,
        book="cwg",
        confirm=False,
        extract=_extract_storefront,
        books=books,
        evidence_roots=ev,
    )
    first = ingest_path(
        path,
        book="cwg",
        confirm=True,
        confirm_token=preview.confirm_token,
        extract=_extract_storefront,
        books=books,
        evidence_roots=ev,
    )
    assert first.action == "appended"
    assert len(load_rows(cwg)) == 1
    stale = ingest_path(
        path,
        book="cwg",
        confirm=True,
        confirm_token=preview.confirm_token,
        extract=_extract_storefront,
        books=books,
        evidence_roots=ev,
    )
    assert stale.action == "blocked"
    assert len(load_rows(cwg)) == 1


def test_absent_and_mismatched_tokens_do_not_write(tmp_path, monkeypatch):
    sov, cwg = _isolate_books(tmp_path, monkeypatch)
    photo = tmp_path / "chat.jpg"
    photo.write_bytes(b"fake")
    other = tmp_path / "other.jpg"
    other.write_bytes(b"other-bytes")
    kw = dict(
        book="cwg",
        extract=_extract_storefront,
        books={"soveryn": sov, "cwg": cwg},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
    )
    preview = ingest_path(photo, confirm=False, **kw)
    assert preview.action == "preview"
    missing = ingest_path(photo, confirm=True, confirm_token="not-a-token", **kw)
    assert missing.action == "blocked"
    assert load_rows(cwg) == []
    from soveryn.platform.ledgers.ingest import issue_confirm_token

    expired, _ = issue_confirm_token({"kind": "ingest_path", "path": str(photo)}, ttl=-1)
    stale = ingest_path(photo, confirm=True, confirm_token=expired, **kw)
    assert stale.action == "blocked"
    assert load_rows(cwg) == []
    mismatched = ingest_path(
        other, confirm=True, confirm_token=preview.confirm_token, **kw
    )
    assert mismatched.action == "blocked"
    assert "does not match" in (mismatched.message or "")
    assert load_rows(cwg) == []


def test_original_and_derivative_same_invoice_one_row(tmp_path, monkeypatch):
    sov, cwg = _isolate_books(tmp_path, monkeypatch)
    kw = dict(
        book="cwg",
        extract=_extract_storefront,
        books={"soveryn": sov, "cwg": cwg},
        evidence_roots={"soveryn": tmp_path / "ev-s", "cwg": tmp_path / "ev-c"},
    )
    original = tmp_path / "original.jpg"
    derivative = tmp_path / "ocr-clean.jpg"
    original.write_bytes(b"original-bytes")
    derivative.write_bytes(b"derivative-bytes")
    first = ingest_path(original, confirm=False, **kw)
    booked = ingest_path(
        original, confirm=True, confirm_token=first.confirm_token, **kw
    )
    assert booked.action == "appended"
    second = ingest_path(derivative, confirm=False, **kw)
    assert second.action == "duplicate"
    assert len(load_rows(cwg)) == 1


def test_chat_preview_upload_does_not_book(app_state):
    client = app_state["client"]
    sid = _new_session(app_state["conv"])
    resp = _post(
        client,
        "/chat",
        {
            "agent": "aetheria",
            "session_id": sid,
            "message": PREVIEW_MSG,
            "attachments": [_jpeg_data_url()],
        },
    )
    assert resp.status_code == 200, resp.data
    text = _user_text(app_state["fake"].calls[-1]["request"])
    assert "action=preview" in text
    assert "PREVIEW ONLY" in text
    assert "chat token cannot book" in text
    assert PREVIEW_MSG in text
    assert load_rows(app_state["cwg"]) == []
    assert load_rows(app_state["sov"]) == []
    assert list((app_state["tmp"] / "ev-c").rglob("*")) == []


def test_chat_stream_preview_upload_does_not_book(app_state):
    client = app_state["client"]
    sid = _new_session(app_state["conv"])
    resp = _post(
        client,
        "/chat_stream",
        {
            "agent": "aetheria",
            "session_id": sid,
            "message": PREVIEW_MSG,
            "attachments": [_jpeg_data_url()],
        },
    )
    assert resp.status_code == 200, resp.data
    text = _user_text(app_state["stream"].calls[-1]["request"])
    assert "action=preview" in text
    assert "PREVIEW ONLY" in text
    assert "chat token cannot book" in text
    assert PREVIEW_MSG in text
    assert load_rows(app_state["cwg"]) == []
    assert load_rows(app_state["sov"]) == []
    assert list((app_state["tmp"] / "ev-c").rglob("*")) == []


def test_missing_session_with_receipt_photo_does_not_hook(app_state, monkeypatch):
    seen: list[str] = []

    def boom(message, images):
        seen.append(message)
        raise AssertionError("receipt hook must not run before session validation")

    monkeypatch.setattr("soveryn.app.routes.chat.ChatReceiptHook.apply", boom)
    resp = _post(
        app_state["client"],
        "/chat",
        {
            "agent": "aetheria",
            "session_id": "receipt-diagnostic-nonexistent",
            "message": PREVIEW_MSG,
            "attachments": [_jpeg_data_url()],
        },
    )
    assert resp.status_code == 404
    assert json.loads(resp.data)["error"]["code"] == "missing_session"
    assert seen == []
    assert load_rows(app_state["cwg"]) == []


def test_missing_session_stream_with_receipt_photo_does_not_hook(app_state, monkeypatch):
    seen: list[str] = []

    def boom(message, images):
        seen.append(message)
        raise AssertionError("receipt hook must not run before session validation")

    monkeypatch.setattr("soveryn.app.routes.chat.ChatReceiptHook.apply", boom)
    resp = _post(
        app_state["client"],
        "/chat_stream",
        {
            "agent": "aetheria",
            "session_id": "receipt-diagnostic-nonexistent",
            "message": PREVIEW_MSG,
            "attachments": [_jpeg_data_url()],
        },
    )
    assert resp.status_code == 404
    assert json.loads(resp.data)["error"]["code"] == "missing_session"
    assert seen == []
    assert load_rows(app_state["cwg"]) == []


def test_session_agent_mismatch_with_receipt_photo_does_not_hook(app_state, monkeypatch):
    seen: list[str] = []

    def boom(message, images):
        seen.append(message)
        raise AssertionError("receipt hook must not run on agent mismatch")

    monkeypatch.setattr("soveryn.app.routes.chat.ChatReceiptHook.apply", boom)
    sid = _new_session(app_state["conv"], agent="eve")
    resp = _post(
        app_state["client"],
        "/chat",
        {
            "agent": "aetheria",
            "session_id": sid,
            "message": PREVIEW_MSG,
            "attachments": [_jpeg_data_url()],
        },
    )
    assert resp.status_code == 409
    assert json.loads(resp.data)["error"]["code"] == "session_agent_mismatch"
    assert seen == []
    assert load_rows(app_state["cwg"]) == []
