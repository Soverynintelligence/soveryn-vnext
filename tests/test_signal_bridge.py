"""Tests for the Signal Direct Line bridge — config, JSON parser,
daemon allowlist + dispatch + outbound retry.

Subprocess and HTTP are mocked throughout. The live signal-cli is
exercised only by interactive verification, not the unit suite.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from soveryn.agents.signal_bridge.client import (
    InboundMessage,
    SignalCliError,
    parse_envelopes,
)
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.agents.signal_bridge.daemon import SignalBridgeDaemon
from soveryn.platform.lattice.legacy import LatticeStore


# ─── Config ──────────────────────────────────────────────────────────────────

def test_config_from_env_parses_allowlist():
    env = {
        "SOVERYN_SIGNAL_BOT_NUMBER": "+19102489392",
        "SOVERYN_SIGNAL_ALLOWED_NUMBERS": "+19105813970,+15555550100",
        "SOVERYN_SIGNAL_CLI_BIN": "/usr/local/bin/signal-cli",
    }
    cfg = SignalBridgeConfig.from_env(env)
    assert cfg.bot_number == "+19102489392"
    assert cfg.allowed_numbers == frozenset({"+19105813970", "+15555550100"})
    assert cfg.signal_cli_bin == "/usr/local/bin/signal-cli"
    assert cfg.enabled is True


def test_config_empty_allowlist_yields_empty_frozenset():
    cfg = SignalBridgeConfig.from_env({"SOVERYN_SIGNAL_BOT_NUMBER": "+1"})
    assert cfg.allowed_numbers == frozenset()


def test_config_disabled_flag():
    cfg = SignalBridgeConfig.from_env({
        "SOVERYN_SIGNAL_BOT_NUMBER": "+1",
        "SOVERYN_SIGNAL_BRIDGE_ENABLED": "false",
    })
    assert cfg.enabled is False


# ─── JSON-LD envelope parser ────────────────────────────────────────────────

def test_parse_envelopes_extracts_text_message():
    raw = json.dumps({
        "envelope": {
            "source": "+19105813970",
            "timestamp": 1779801096748,
            "dataMessage": {"message": "Hi", "attachments": []},
        },
    }) + "\n"
    out = parse_envelopes(raw)
    assert len(out) == 1
    assert out[0].source_e164 == "+19105813970"
    assert out[0].body == "Hi"
    assert out[0].timestamp_ms == 1779801096748
    assert out[0].attachment_ids == ()


def test_parse_envelopes_extracts_attachment_filename():
    raw = json.dumps({
        "envelope": {
            "source": "+19105813970",
            "timestamp": 1,
            "dataMessage": {
                "message": "look at this",
                "attachments": [{"id": "att-123.jpg", "contentType": "image/jpeg"}],
            },
        },
    }) + "\n"
    out = parse_envelopes(raw)
    assert out[0].attachment_ids == ("att-123.jpg",)


def test_parse_envelopes_skips_non_text_envelopes():
    """Read receipts / typing indicators / sync messages don't have
    dataMessage — they should be silently dropped."""
    raw = (
        json.dumps({"envelope": {"source": "+1", "receiptMessage": {}}}) + "\n"
        + json.dumps({"envelope": {"source": "+1", "typingMessage": {}}}) + "\n"
    )
    assert parse_envelopes(raw) == ()


def test_parse_envelopes_tolerates_bad_lines():
    """One malformed line shouldn't kill the batch."""
    raw = (
        "not json at all\n"
        + json.dumps({"envelope": {"source": "+1", "timestamp": 1,
                                    "dataMessage": {"message": "good"}}}) + "\n"
        + "{broken json\n"
    )
    out = parse_envelopes(raw)
    assert len(out) == 1
    assert out[0].body == "good"


# ─── Daemon: allowlist + dispatch ───────────────────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def conv_db(tmp_path):
    return tmp_path / "conv.db"  # NOT created — daemon hits API


def _config(**kw) -> SignalBridgeConfig:
    base = dict(
        bot_number="+19102489392",
        allowed_numbers=frozenset({"+19105813970"}),
        signal_cli_bin="/usr/local/bin/signal-cli",
        vnext_base="http://127.0.0.1:5001",
        chat_timeout_seconds=240,
        enabled=True,
        poll_interval_seconds=2.0,
        outbound_max_retries=3,
        outbound_initial_backoff_seconds=0.01,
    )
    base.update(kw)
    return SignalBridgeConfig(**base)


def test_daemon_drops_off_allowlist_with_audit(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+15555550199",  # NOT on allowlist
        timestamp_ms=1,
        body="hello",
        attachment_ids=(),
    )
    daemon._handle_inbound(msg)
    with sqlite3.connect(str(lattice_db)) as con:
        rows = con.execute(
            "SELECT direction, sender_e164, error FROM signal_log"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0] == ("dropped", "+15555550199", "sender not in allowlist")


def test_daemon_routes_allowlisted_message_to_chat(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="morning",
        attachment_ids=(),
    )
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="morning back."), \
         patch("soveryn.agents.signal_bridge.daemon.send_once") as mock_send:
        daemon._handle_inbound(msg)
    mock_send.assert_called_once()
    kwargs = mock_send.call_args.kwargs
    assert kwargs["recipient_e164"] == "+19105813970"
    assert kwargs["body"] == "morning back."
    # Two audit rows: inbound + outbound (no dropped).
    with sqlite3.connect(str(lattice_db)) as con:
        directions = [r[0] for r in con.execute(
            "SELECT direction FROM signal_log ORDER BY created_at"
        ).fetchall()]
    assert directions == ["inbound", "outbound"]


def test_daemon_retries_outbound_with_backoff(lattice_db, conv_db):
    """First two sends raise, third succeeds. Audit row reports success."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="ping",
        attachment_ids=(),
    )
    send_side_effects = [SignalCliError("transient 1"), SignalCliError("transient 2"), None]
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="pong"), \
         patch("soveryn.agents.signal_bridge.daemon.send_once",
                side_effect=send_side_effects) as mock_send:
        daemon._handle_inbound(msg)
    assert mock_send.call_count == 3
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound_error = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    assert last_outbound_error is None  # last attempt succeeded


def test_daemon_records_outbound_failure_after_all_retries_exhausted(lattice_db, conv_db):
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="ping",
        attachment_ids=(),
    )
    persistent_err = SignalCliError("always broken")
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="pong"), \
         patch("soveryn.agents.signal_bridge.daemon.send_once",
                side_effect=persistent_err) as mock_send:
        daemon._handle_inbound(msg)
    assert mock_send.call_count == 3  # outbound_max_retries
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound_error = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()[0]
    assert last_outbound_error is not None
    assert "always broken" in last_outbound_error


def test_daemon_skips_send_when_aetheria_returns_empty(lattice_db, conv_db):
    """Aetheria empty content → audit-row the failure, do NOT call send_once."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    msg = InboundMessage(
        source_e164="+19105813970", timestamp_ms=1, body="anything",
        attachment_ids=(),
    )
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", return_value="   "), \
         patch("soveryn.agents.signal_bridge.daemon.send_once") as mock_send:
        daemon._handle_inbound(msg)
    mock_send.assert_not_called()
    with sqlite3.connect(str(lattice_db)) as con:
        last_outbound = con.execute(
            "SELECT error FROM signal_log WHERE direction='outbound' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    assert last_outbound[0] == "empty response from Aetheria"


def test_inbound_jpeg_attachment_encodes_and_forwards_as_data_url(tmp_path, lattice_db, conv_db):
    """A .jpg in attachment_ids becomes a data:image/jpeg;base64,... URL on
    the /chat call. The placeholder text line is dropped."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"fake jpeg payload bytes")

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["session_id"] = session_id
        captured["body"] = body
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="check this out",
            attachment_ids=(str(img),),
        )
        daemon._handle_inbound(msg)

    assert captured["body"] == "check this out"
    assert "vision pipeline integration pending" not in captured["body"]
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].startswith("data:image/jpeg;base64,")


def test_inbound_png_webp_gif_all_encoded(tmp_path, lattice_db, conv_db):
    """Each supported image MIME is detected by extension."""
    files = {
        "a.png": "image/png",
        "b.webp": "image/webp",
        "c.gif": "image/gif",
        "d.jpeg": "image/jpeg",
    }
    paths = []
    for name in files:
        p = tmp_path / name
        p.write_bytes(b"x" * 16)
        paths.append(str(p))

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="four images",
            attachment_ids=tuple(paths),
        )
        daemon._handle_inbound(msg)

    assert len(captured["attachments"]) == 4
    mimes = [a.split(";")[0].removeprefix("data:") for a in captured["attachments"]]
    assert mimes == ["image/png", "image/webp", "image/gif", "image/jpeg"]


def test_inbound_non_image_attachment_skipped_with_hint(tmp_path, lattice_db, conv_db):
    """A .pdf attachment is dropped from the forwarded attachments, but a count
    hint is added to the message body."""
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["body"] = body
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="see attached",
            attachment_ids=(str(pdf),),
        )
        daemon._handle_inbound(msg)

    assert "1 non-image attachment" in captured["body"]
    assert "see attached" in captured["body"]
    assert captured["attachments"] == ()


def test_inbound_missing_attachment_file_logged_and_skipped(tmp_path, lattice_db, conv_db):
    """A path that doesn't exist on disk doesn't crash the daemon; it's
    counted-as-skipped (treated as 'failed to read' rather than 'not an image')."""
    missing = tmp_path / "ghost.jpg"  # never written
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["body"] = body
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="ping",
            attachment_ids=(str(missing),),
        )
        daemon._handle_inbound(msg)

    # No images succeeded; no crash; body keeps a skipped-hint OR is at least
    # the original "ping" with a count hint. Verify it doesn't have the old
    # placeholder text.
    assert "vision pipeline integration pending" not in captured["body"]
    assert captured["attachments"] == ()


def test_inbound_filename_only_resolves_via_signal_cli_attachments_dir(
    tmp_path, lattice_db, conv_db, monkeypatch,
):
    """Production path: parse_envelopes stores only the signal-cli `id`
    (a bare filename). resolve_attachment_id() resolves it against the
    signal-cli attachments directory before the encoder reads bytes."""
    from soveryn.agents.signal_bridge import client as client_mod

    fake_attachments_dir = tmp_path / "sigcli"
    fake_attachments_dir.mkdir()
    img = fake_attachments_dir / "PRODUCTION_LIKE_ID.jpeg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake jpeg")
    monkeypatch.setattr(client_mod, "DEFAULT_SIGNAL_CLI_ATTACHMENTS_DIR", fake_attachments_dir)

    d = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["attachments"] = attachments
        return "ack"
    with patch.object(d, "_ensure_session", return_value="sess-1"), \
         patch.object(d, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="from phone",
            attachment_ids=("PRODUCTION_LIKE_ID.jpeg",),  # bare filename, not path
        )
        d._handle_inbound(msg)
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].startswith("data:image/jpeg;base64,")


def test_resolve_attachment_id_rejects_traversal():
    """Defense against hypothetical signal-cli ids containing `..` segments."""
    from soveryn.agents.signal_bridge.client import resolve_attachment_id
    import pytest
    with pytest.raises(ValueError, match="traversal"):
        resolve_attachment_id("../../etc/passwd")


def test_resolve_attachment_id_absolute_returned_as_is(tmp_path):
    """If the producer ever emits an absolute path, pass it through. Tests
    that fabricate absolute tmp_path inputs keep working."""
    from soveryn.agents.signal_bridge.client import resolve_attachment_id
    f = tmp_path / "x.jpg"
    f.write_bytes(b"x")
    result = resolve_attachment_id(str(f))
    assert result == f


def test_envelope_to_chat_dispatch_integration(tmp_path, lattice_db, conv_db, monkeypatch):
    """End-to-end producer-shape integration: a realistic signal-cli envelope
    (with the `id` field = bare filename) flows through parse_envelopes →
    _handle_inbound → captured /chat call carrying a real data: URL.

    This is the test that would have caught T8 bug #1 (consumer expected
    absolute paths, producer emitted filenames) at write-time instead of in
    live verification. Keeps the producer-shape contract verified for every
    future test run."""
    from soveryn.agents.signal_bridge import client as client_mod
    from soveryn.agents.signal_bridge.client import parse_envelopes

    fake_attachments_dir = tmp_path / "sigcli"
    fake_attachments_dir.mkdir()
    img = fake_attachments_dir / "envelope-test.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"realistic jpeg bytes")
    monkeypatch.setattr(client_mod, "DEFAULT_SIGNAL_CLI_ATTACHMENTS_DIR", fake_attachments_dir)

    # Realistic signal-cli --output json envelope (`id` is the filename).
    raw = json.dumps({
        "envelope": {
            "source": "+19105813970",
            "timestamp": 1779801000000,
            "dataMessage": {
                "message": "what's in this?",
                "attachments": [{"id": "envelope-test.jpg", "contentType": "image/jpeg"}],
            },
        },
    }) + "\n"

    inbounds = parse_envelopes(raw)
    assert len(inbounds) == 1
    msg = inbounds[0]
    # Confirm the producer contract: the field stores the bare id, not a path.
    assert msg.attachment_ids == ("envelope-test.jpg",)

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["body"] = body
        captured["attachments"] = attachments
        return "I see it"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        daemon._handle_inbound(msg)

    # The end-to-end shape Aetheria actually receives:
    assert captured["body"] == "what's in this?"
    assert len(captured["attachments"]) == 1
    assert captured["attachments"][0].startswith("data:image/jpeg;base64,")


def test_inbound_oversized_image_skipped_with_warning(tmp_path, lattice_db, conv_db, caplog):
    """An image exceeding _MAX_INBOUND_IMAGE_BYTES (16MB) is logged + skipped.
    Parity with the UI's 16MB client cap and signal_send's outbound 16MB cap."""
    import logging
    big = tmp_path / "big.jpg"
    big.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * (17 * 1024 * 1024))  # ~17MB

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["attachments"] = attachments
        captured["body"] = body
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"), \
         caplog.at_level(logging.WARNING, logger="soveryn.agents.signal_bridge.daemon"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="here", attachment_ids=(str(big),),
        )
        daemon._handle_inbound(msg)
    assert captured["attachments"] == ()
    assert "non-image attachment" in captured["body"]
    assert any("16777216" in rec.message or "inbound cap" in rec.message
               for rec in caplog.records)


def test_inbound_text_only_no_attachments_unchanged(tmp_path, lattice_db, conv_db):
    """Regression: text-only message → no attachments param, body unchanged."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["body"] = body
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="morning",
            attachment_ids=(),
        )
        daemon._handle_inbound(msg)

    assert captured["body"] == "morning"
    assert captured["attachments"] == ()


def test_inbound_image_only_empty_body_becomes_image_only_marker(tmp_path, lattice_db, conv_db):
    """When the user sends only an image (no caption), body becomes
    '(image only)' so the chat call has non-empty content."""
    img = tmp_path / "shot.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0fake")

    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_chat(session_id, body, attachments=()):
        captured["body"] = body
        captured["attachments"] = attachments
        return "ack"
    with patch.object(daemon, "_ensure_session", return_value="sess-1"), \
         patch.object(daemon, "_call_vnext_chat", side_effect=fake_chat), \
         patch("soveryn.agents.signal_bridge.daemon.send_once"):
        msg = InboundMessage(
            source_e164="+19105813970", timestamp_ms=1,
            body="",
            attachment_ids=(str(img),),
        )
        daemon._handle_inbound(msg)

    assert captured["body"] == "(image only)"
    assert len(captured["attachments"]) == 1


def test_call_vnext_chat_includes_attachments_in_payload(lattice_db, conv_db):
    """Unit-level: _call_vnext_chat passes the attachments tuple into the
    /chat JSON payload only when non-empty."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_post(path, body, *, timeout):
        captured["path"] = path
        captured["body"] = body
        return {"content": "ok"}
    with patch.object(daemon, "_post_json", side_effect=fake_post):
        daemon._call_vnext_chat("sess-1", "hi", attachments=("data:image/jpeg;base64,AAAA",))
    assert captured["path"] == "/chat"
    assert captured["body"]["attachments"] == ["data:image/jpeg;base64,AAAA"]


def test_call_vnext_chat_omits_attachments_when_empty(lattice_db, conv_db):
    """No 'attachments' key in payload when none provided — backward-compatible."""
    daemon = SignalBridgeDaemon(_config(), lattice_db=lattice_db, conv_db=conv_db)
    captured: dict = {}
    def fake_post(path, body, *, timeout):
        captured["body"] = body
        return {"content": "ok"}
    with patch.object(daemon, "_post_json", side_effect=fake_post):
        daemon._call_vnext_chat("sess-1", "hi")
    assert "attachments" not in captured["body"]


# ─── send_once: attachments ─────────────────────────────────────────────────

def _ok_completed_process():
    from types import SimpleNamespace
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def _failed_completed_process(stderr: str = ""):
    from types import SimpleNamespace
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


def test_send_once_passes_attachments_as_repeated_attachment_flags(monkeypatch):
    """Each path becomes a separate --attachment <path> in the argv."""
    from soveryn.agents.signal_bridge.client import send_once

    captured: dict = {}
    def fake_run(args, *, capture_output, text, timeout):
        captured["args"] = args
        return _ok_completed_process()
    monkeypatch.setattr("soveryn.agents.signal_bridge.client.subprocess.run", fake_run)

    send_once(
        signal_cli_bin="/usr/local/bin/signal-cli",
        bot_number="+19102489392",
        recipient_e164="+19105813970",
        body="here you go",
        attachments=("/tmp/a.jpg", "/tmp/b.png"),
    )

    args = captured["args"]
    # Two --attachment flags, each immediately followed by the path.
    indices = [i for i, x in enumerate(args) if x == "--attachment"]
    assert len(indices) == 2
    assert args[indices[0] + 1] == "/tmp/a.jpg"
    assert args[indices[1] + 1] == "/tmp/b.png"
    # Recipient is the LAST argv element AND is preceded by `--` so signal-cli's
    # nargs='*' attachment parser stops before consuming the recipient as
    # another attachment value. Without `--` the result would be the live
    # "no recipients given" error.
    assert args[-1] == "+19105813970"
    assert args[-2] == "--"


def test_send_once_no_attachments_unchanged(monkeypatch):
    """Regression: no attachments → no --attachment flag, same shape as before."""
    from soveryn.agents.signal_bridge.client import send_once

    captured: dict = {}
    def fake_run(args, *, capture_output, text, timeout):
        captured["args"] = args
        return _ok_completed_process()
    monkeypatch.setattr("soveryn.agents.signal_bridge.client.subprocess.run", fake_run)

    send_once(
        signal_cli_bin="/usr/local/bin/signal-cli",
        bot_number="+19102489392",
        recipient_e164="+19105813970",
        body="text only",
    )

    args = captured["args"]
    assert "--attachment" not in args
    assert args[-1] == "+19105813970"  # recipient still positional last
    assert "-m" in args
    assert args[args.index("-m") + 1] == "text only"


def test_send_once_raises_on_nonzero_returncode(monkeypatch):
    """Existing contract: SignalCliError on signal-cli failure. Regression check
    after the signature change."""
    from soveryn.agents.signal_bridge.client import send_once, SignalCliError

    def fake_run(args, *, capture_output, text, timeout):
        return _failed_completed_process(stderr="bad recipient")
    monkeypatch.setattr("soveryn.agents.signal_bridge.client.subprocess.run", fake_run)

    with pytest.raises(SignalCliError, match="bad recipient"):
        send_once(
            signal_cli_bin="/usr/local/bin/signal-cli",
            bot_number="+19102489392",
            recipient_e164="+19105813970",
            body="hi",
            attachments=("/tmp/x.jpg",),
        )
