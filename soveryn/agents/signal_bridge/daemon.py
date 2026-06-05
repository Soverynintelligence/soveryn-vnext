"""Signal bridge daemon.

Polls signal-cli for inbound messages, routes each accepted one through
Aetheria's /chat surface, sends her response back over signal-cli. Drops
off-allowlist senders silently (with an audit row). Persists every
event to signal_log.

Process shape mirrors heartbeat / patrol daemons (signal handler for
SIGTERM/SIGINT, single-threaded loop, sleep-with-shutdown-poll). Run as
`python -m soveryn.agents.signal_bridge`.

Session model: one durable conversation_meta row per allowlisted sender,
titled `[signal] +E164`. Inbound text becomes a user turn; Aetheria's
reply becomes an assistant turn — same shape as /chat for the chat UI.
"""

from __future__ import annotations

import json
import logging
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

from soveryn.agents.signal_bridge.client import (
    InboundMessage,
    SignalCliError,
    receive_once,
    send_once,
)
from soveryn.agents.signal_bridge.config import SignalBridgeConfig


logger = logging.getLogger(__name__)


DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")
DEFAULT_CONV_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/conversations_vnext.db")
SIGNAL_SESSION_TITLE_PREFIX = "[signal] "
SIGNAL_AGENT = "aetheria"


class SignalBridgeDaemon:
    """Single-threaded loop. One receive pass at a time."""

    def __init__(
        self,
        config: SignalBridgeConfig,
        *,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
    ) -> None:
        self.config = config
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
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
                attachment_count=len(msg.attachment_paths),
                error="sender not in allowlist",
            )
            logger.info("dropped inbound from %s (not allowlisted)", msg.source_e164)
            return

        self._log_event(
            direction="inbound",
            sender=msg.source_e164, recipient=self.config.bot_number,
            body_head=msg.body[:200],
            attachment_count=len(msg.attachment_paths),
            error=None,
        )

        # Per-sender durable session — find existing or create.
        session_id = self._ensure_session(msg.source_e164)

        # Build the dispatch body: include the raw message + attachment
        # hints. Attachments-as-vision-image is wired in a follow-up; for
        # v1 we just name the attachment count.
        body = msg.body or ""
        if msg.attachment_paths:
            body = (
                (body + "\n\n" if body else "")
                + f"[Signal: {len(msg.attachment_paths)} attachment(s) attached "
                f"— vision pipeline integration pending]"
            )
        if not body.strip():
            body = "(empty message)"

        # Dispatch to Aetheria via the standard /chat path.
        try:
            response_content = self._call_vnext_chat(session_id, body)
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

    def _call_vnext_chat(self, session_id: str, body: str) -> str:
        payload = {"agent": SIGNAL_AGENT, "session_id": session_id, "message": body}
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
