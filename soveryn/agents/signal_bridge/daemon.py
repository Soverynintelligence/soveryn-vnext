"""Signal bridge daemon.

Polls signal-cli for inbound messages and routes each accepted one to one
of two places: Aetheria's /chat surface, or — if the sender is the presence
approver (`SIGNAL_USER_NUMBER`) replying to a live pending presence draft —
the shared `PendingStore` reply queue that `soveryn-presence.service` (a
separate process) drains each loop. See `_maybe_handle_presence_reply`.
Drops off-allowlist senders silently (with an audit row). Persists every
event to signal_log.

Process shape mirrors heartbeat / patrol daemons (signal handler for
SIGTERM/SIGINT, single-threaded loop, sleep-with-shutdown-poll). Run as
`python -m soveryn.agents.signal_bridge`.

Session model: one durable conversation_meta row per allowlisted sender,
titled `[signal] +E164`. Inbound text becomes a user turn; Aetheria's
reply becomes an assistant turn — same shape as /chat for the chat UI.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import signal
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.inbound import parse_draft_reply
from soveryn.agents.presence.pending_store import PendingStore
from soveryn.agents.signal_bridge.client import (
    InboundMessage,
    SignalCliError,
    receive_once,
    resolve_attachment_id,
    send_once,
)
from soveryn.agents.signal_bridge.config import SignalBridgeConfig


logger = logging.getLogger(__name__)


DEFAULT_LATTICE_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"
DEFAULT_CONV_DB = Path.home() / "soveryn_vnext" / "data" / "memory" / "conversations_vnext.db"
# Shared with soveryn-presence.service — the ONLY channel the two processes
# communicate over. See PendingStore's module docstring.
DEFAULT_PENDING_DB = PresenceConfig.default().pending_db_path
SIGNAL_SESSION_TITLE_PREFIX = "[signal] "
SIGNAL_AGENT = "aetheria"
# Env var the presence daemon's SignalSender (soveryn.agents.ares.signal_sender)
# reads as its Signal send recipient — i.e. Jon, the presence approver. A
# reply from this number that leads with a live pending draft-id is a
# presence approval/reject/edit, not a chat message.
SIGNAL_USER_NUMBER_ENV = "SIGNAL_USER_NUMBER"


# Inbound image extension -> MIME mapping. Canonical source is
# soveryn.platform.vision_types.IMAGE_EXT_TO_MIME so that the daemon, the
# /chat route validator, and the UI's accept attribute can't drift apart.
from soveryn.platform.vision_types import IMAGE_EXT_TO_MIME as _IMAGE_EXT_TO_MIME  # noqa: E402

# Per-file cap for inbound encoding. Matches the UI's 16MB client-side cap
# and signal_send's outbound 16MB cap so all three surfaces have the same
# size ceiling. Without this, the bridge would base64-encode arbitrarily
# large signal-cli attachments and balloon the /chat POST body before the
# route's 33MB data:URL string check rejected it.
_MAX_INBOUND_IMAGE_BYTES = 16 * 1024 * 1024


def _encode_image_attachment(path: Path) -> str | None:
    """Encode a local image file as a data: URL for vision-format chat.

    Returns the data URL on success, or None if the extension isn't a
    supported image type, the file is missing/unreadable, OR the file
    exceeds _MAX_INBOUND_IMAGE_BYTES. Failures are logged at WARNING and
    treated as 'skipped' by the caller — the daemon must NOT crash on bad
    attachments because a single inbound message could have a mix of
    supported and unsupported attachments.
    """
    ext = path.suffix.lower()
    mime = _IMAGE_EXT_TO_MIME.get(ext)
    if mime is None:
        return None
    try:
        size = path.stat().st_size
    except OSError as e:
        logger.warning("failed to stat attachment %s: %s", path, e)
        return None
    if size > _MAX_INBOUND_IMAGE_BYTES:
        logger.warning(
            "attachment %s exceeds %d-byte inbound cap (actual %d); skipping",
            path, _MAX_INBOUND_IMAGE_BYTES, size,
        )
        return None
    try:
        data = path.read_bytes()
    except (OSError, IOError) as e:
        logger.warning("failed to read attachment %s: %s", path, e)
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


class SignalBridgeDaemon:
    """Single-threaded loop. One receive pass at a time."""

    def __init__(
        self,
        config: SignalBridgeConfig,
        *,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
        pending_db_path: Path = DEFAULT_PENDING_DB,
    ) -> None:
        self.config = config
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self.pending_db_path = Path(pending_db_path)
        self._stop = False

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "signal bridge starting. bot=%s allowlist_size=%d enabled=%s",
            self.config.bot_number, len(self.config.allowed_numbers),
            self.config.enabled,
        )
        if not self.config.bot_number:
            logger.error("SOVERYN_SIGNAL_BOT_NUMBER missing; refusing to start")
            return
        if not self.config.allowed_numbers:
            logger.warning(
                "SOVERYN_SIGNAL_ALLOWED_NUMBERS empty; every inbound will be dropped"
            )

        while not self._stop:
            if not self.config.enabled:
                self._sleep_with_shutdown(self.config.poll_interval_seconds)
                continue
            try:
                inbound = receive_once(
                    signal_cli_bin=self.config.signal_cli_bin,
                    bot_number=self.config.bot_number,
                )
            except SignalCliError as e:
                logger.warning("receive failed: %s", e)
                self._sleep_with_shutdown(self.config.poll_interval_seconds)
                continue
            except Exception:
                logger.exception("unexpected receive error")
                self._sleep_with_shutdown(self.config.poll_interval_seconds)
                continue

            for msg in inbound:
                if self._stop:
                    break
                try:
                    self._handle_inbound(msg)
                except Exception:
                    logger.exception(
                        "failed to handle inbound from %s", msg.source_e164,
                    )

            self._sleep_with_shutdown(self.config.poll_interval_seconds)

        logger.info("signal bridge stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("signal bridge received shutdown signal")
        self._stop = True

    def _sleep_with_shutdown(self, seconds: float) -> None:
        end_at = time.monotonic() + seconds
        while not self._stop and time.monotonic() < end_at:
            time.sleep(min(0.5, max(0.05, end_at - time.monotonic())))

    # ─── Per-message handling ───────────────────────────────────────────────

    def _handle_inbound(self, msg: InboundMessage) -> None:
        """Route one inbound message: allowlist check → session lookup →
        /chat dispatch → outbound reply → audit. Each step writes a
        signal_log row so a replay is possible without conversations DB."""
        if msg.source_e164 not in self.config.allowed_numbers:
            self._log_event(
                direction="dropped",
                sender=msg.source_e164, recipient=self.config.bot_number,
                body_head=msg.body[:200],
                attachment_count=len(msg.attachment_ids),
                error="sender not in allowlist",
            )
            logger.info("dropped inbound from %s (not allowlisted)", msg.source_e164)
            return

        if self._maybe_handle_presence_reply(msg):
            return

        self._log_event(
            direction="inbound",
            sender=msg.source_e164, recipient=self.config.bot_number,
            body_head=msg.body[:200],
            attachment_count=len(msg.attachment_ids),
            error=None,
        )

        # Per-sender durable session — find existing or create.
        session_id = self._ensure_session(msg.source_e164)

        # Build the dispatch body: encode supported image attachments to
        # data: URLs and forward via the /chat attachments field. Non-image
        # or unreadable attachments are surfaced as a count hint in the
        # text body so Aetheria knows something was sent.
        body = msg.body or ""
        image_data_urls: list[str] = []
        skipped_count = 0
        for attachment_id in msg.attachment_ids:
            try:
                p = resolve_attachment_id(attachment_id)
            except ValueError as e:
                logger.warning("rejecting attachment id %r: %s", attachment_id, e)
                skipped_count += 1
                continue
            url = _encode_image_attachment(p)
            if url is None:
                skipped_count += 1
            else:
                image_data_urls.append(url)

        if skipped_count > 0:
            suffix = f"[Signal: {skipped_count} non-image attachment(s) skipped]"
            body = (body + "\n\n" if body else "") + suffix

        if not body.strip():
            if image_data_urls:
                body = "(image only)"
            else:
                body = "(empty message)"

        # Dispatch to Aetheria via the standard /chat path.
        try:
            response_content = self._call_vnext_chat(
                session_id, body, attachments=tuple(image_data_urls),
            )
        except Exception as e:
            self._log_event(
                direction="outbound",
                sender=self.config.bot_number, recipient=msg.source_e164,
                body_head="", attachment_count=0,
                error=f"chat dispatch failed: {type(e).__name__}: {e}",
            )
            logger.exception("chat dispatch failed for %s", msg.source_e164)
            return

        if not response_content.strip():
            self._log_event(
                direction="outbound",
                sender=self.config.bot_number, recipient=msg.source_e164,
                body_head="", attachment_count=0,
                error="empty response from Aetheria",
            )
            logger.warning("empty response from Aetheria for %s", msg.source_e164)
            return

        # Send back. Retry transient failures.
        last_error: str | None = None
        for attempt in range(self.config.outbound_max_retries):
            try:
                send_once(
                    signal_cli_bin=self.config.signal_cli_bin,
                    bot_number=self.config.bot_number,
                    recipient_e164=msg.source_e164,
                    body=response_content,
                )
                last_error = None
                break
            except SignalCliError as e:
                last_error = str(e)
                backoff = self.config.outbound_initial_backoff_seconds * (2 ** attempt)
                logger.warning(
                    "outbound to %s failed (attempt %d/%d): %s; backoff %.1fs",
                    msg.source_e164, attempt + 1,
                    self.config.outbound_max_retries, e, backoff,
                )
                self._sleep_with_shutdown(backoff)

        self._log_event(
            direction="outbound",
            sender=self.config.bot_number, recipient=msg.source_e164,
            body_head=response_content[:200],
            attachment_count=0,
            error=last_error,
        )

    # ─── Presence-reply short-circuit ───────────────────────────────────────

    def _maybe_handle_presence_reply(self, msg: InboundMessage) -> bool:
        """Route an approval-flow reply into `PendingStore` instead of /chat.

        The presence daemon (soveryn-presence.service) is a separate process
        that sends draft posts to Jon over Signal and drains its own
        `pending_replies` queue each loop. This bridge is the only process
        that actually receives inbound Signal, so a reply from Jon (the
        presence approver, `SIGNAL_USER_NUMBER`) that leads with a live
        pending draft-id must be handed to that queue here, not dispatched
        to Aetheria's /chat.

        Returns True if the message was claimed as a presence reply (caller
        must return without any further dispatch); False if it should fall
        through to normal /chat routing — either because the sender isn't
        the approver, `SIGNAL_USER_NUMBER` isn't configured, or the message
        body doesn't lead with a pending draft-id.
        """
        approver_number = os.environ.get(SIGNAL_USER_NUMBER_ENV, "").strip()
        if not approver_number or msg.source_e164 != approver_number:
            return False

        store = PendingStore(self.pending_db_path)
        parsed = parse_draft_reply(msg.body or "", store.draft_ids())
        if parsed is None:
            return False

        draft_id, reply_text = parsed
        store.enqueue_reply(draft_id, reply_text, now=datetime.now().isoformat())

        ack = f"Queued your reply for draft {draft_id} — resolving."
        last_error: str | None = None
        try:
            send_once(
                signal_cli_bin=self.config.signal_cli_bin,
                bot_number=self.config.bot_number,
                recipient_e164=msg.source_e164,
                body=ack,
            )
        except SignalCliError as e:
            last_error = str(e)
            logger.warning(
                "presence-reply ack to %s failed: %s", msg.source_e164, e,
            )

        self._log_event(
            direction="presence_reply",
            sender=msg.source_e164, recipient=self.config.bot_number,
            body_head=msg.body[:200],
            attachment_count=len(msg.attachment_ids),
            error=last_error,
        )
        logger.info(
            "routed inbound from %s to presence PendingStore (draft %s)",
            msg.source_e164, draft_id,
        )
        return True

    # ─── Session management ─────────────────────────────────────────────────

    def _ensure_session(self, sender_e164: str) -> str:
        title = SIGNAL_SESSION_TITLE_PREFIX + sender_e164
        with sqlite3.connect(str(self.conv_db)) as con:
            row = con.execute(
                "SELECT session_id FROM conversation_meta "
                "WHERE agent = ? AND title = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (SIGNAL_AGENT, title),
            ).fetchone()
        if row is not None:
            return row[0]
        # Create via the API so conversation_meta is touched the same way
        # /sessions endpoint does it.
        payload = {"agent": SIGNAL_AGENT, "title": title}
        resp = self._post_json("/sessions", payload, timeout=10)
        return resp["session_id"]

    def _call_vnext_chat(
        self,
        session_id: str,
        body: str,
        attachments: tuple[str, ...] = (),
    ) -> str:
        payload: dict = {
            "agent": SIGNAL_AGENT,
            "session_id": session_id,
            "message": body,
        }
        if attachments:
            payload["attachments"] = list(attachments)
        resp = self._post_json("/chat", payload, timeout=self.config.chat_timeout_seconds)
        return resp.get("content", "") if isinstance(resp, dict) else ""

    def _post_json(self, path: str, body: dict, *, timeout: int) -> dict:
        url = f"{self.config.vnext_base.rstrip('/')}{path}"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    # ─── Audit log ──────────────────────────────────────────────────────────

    def _log_event(
        self, *, direction: str, sender: str | None, recipient: str | None,
        body_head: str, attachment_count: int, error: str | None,
    ) -> None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.execute(
                    "INSERT INTO signal_log "
                    "(id, direction, sender_e164, recipient_e164, body_head, "
                    "attachment_count, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), direction, sender, recipient,
                     body_head, attachment_count, error,
                     datetime.now().isoformat()),
                )
        except Exception:
            logger.exception("failed to write signal_log row")


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = SignalBridgeConfig.from_env()
    daemon = SignalBridgeDaemon(config)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
