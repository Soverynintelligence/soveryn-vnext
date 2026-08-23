"""Email tools for citizens — stdlib SMTP/IMAP, env-configured only.

Never phones home to a mail SaaS control plane. If SMTP is not configured,
registration is skipped and the Citizens board shows email as granted-but-unarmed.

From addresses are citizen identities (see identities.py) — not Jon's Gmail.
"""
from __future__ import annotations

import email
import imaplib
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Mapping

from soveryn.citizens.connectors import email_armed, email_config, email_list_armed
from soveryn.platform.email.identities import resolve_from_address
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


def _send_for(owner_agent: str):
    def _send(args: Mapping[str, Any]) -> dict[str, Any]:
        armed, why = email_armed()
        if not armed:
            return {"ok": False, "error": why}
        cfg = email_config()
        to = (args.get("to") or "").strip()
        subject = (args.get("subject") or "").strip()
        body = (args.get("body") or "").strip()
        if not to or not subject or not body:
            return {"ok": False, "error": "to, subject, and body are required"}
        recipients = [a.strip() for a in to.split(",") if a.strip()]
        if len(recipients) > 10:
            return {"ok": False, "error": "at most 10 recipients per send"}

        requested = (args.get("from") or args.get("from_address") or "").strip() or None
        from_addr, err = resolve_from_address(owner_agent, requested)
        if err or not from_addr:
            return {"ok": False, "error": err or "no from address"}

        # Envelope sender stays the house SMTP mailbox when set; header From
        # is the citizen identity (aliases must be authorized at the provider).
        envelope_from = (cfg["smtp_from"] or from_addr).strip()

        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.set_content(body)
        if envelope_from and envelope_from.lower() != from_addr.lower():
            msg["Sender"] = envelope_from

        host = cfg["smtp_host"] or ""
        port = int(cfg["smtp_port"] or 587)
        try:
            if port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as smtp:
                    if cfg["smtp_user"]:
                        smtp.login(cfg["smtp_user"] or "", cfg["smtp_pass"] or "")
                    smtp.send_message(msg, from_addr=envelope_from)
            else:
                with smtplib.SMTP(host, port, timeout=30) as smtp:
                    smtp.ehlo()
                    try:
                        smtp.starttls(context=ssl.create_default_context())
                        smtp.ehlo()
                    except smtplib.SMTPException:
                        pass
                    if cfg["smtp_user"]:
                        smtp.login(cfg["smtp_user"] or "", cfg["smtp_pass"] or "")
                    smtp.send_message(msg, from_addr=envelope_from)
        except Exception as exc:
            return {"ok": False, "error": f"smtp failed: {exc!r}"}
        return {
            "ok": True,
            "to": recipients,
            "subject": subject,
            "from": from_addr,
            "envelope_from": envelope_from,
            "citizen": owner_agent,
        }

    return _send


def _list_inbox(args: Mapping[str, Any]) -> dict[str, Any]:
    armed, why = email_list_armed()
    if not armed:
        return {"ok": False, "error": why}
    cfg = email_config()
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 30))
    host = cfg["imap_host"] or ""
    port = int(cfg["imap_port"] or 993)
    user = cfg["imap_user"] or cfg["smtp_user"] or ""
    password = cfg["imap_pass"] or cfg["smtp_pass"] or ""
    if not user:
        return {"ok": False, "error": "IMAP user not configured"}
    try:
        with imaplib.IMAP4_SSL(host, port, timeout=30) as imap:
            imap.login(user, password)
            imap.select("INBOX", readonly=True)
            typ, data = imap.search(None, "ALL")
            if typ != "OK" or not data or not data[0]:
                return {"ok": True, "messages": [], "count": 0}
            ids = data[0].split()
            ids = ids[-limit:]
            messages = []
            for mid in reversed(ids):
                typ, msg_data = imap.fetch(mid, "(RFC822.HEADER)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                parsed = email.message_from_bytes(raw)
                messages.append(
                    {
                        "id": mid.decode() if isinstance(mid, bytes) else str(mid),
                        "from": parsed.get("From", ""),
                        "to": parsed.get("To", ""),
                        "subject": parsed.get("Subject", ""),
                        "date": parsed.get("Date", ""),
                    }
                )
            return {"ok": True, "messages": messages, "count": len(messages)}
    except Exception as exc:
        return {"ok": False, "error": f"imap failed: {exc!r}"}


def register_email_tools(registry: ToolRegistry, *, owner_agent: str) -> int:
    """Register email_send (if SMTP armed) and email_list (if IMAP armed). Returns count."""
    n = 0
    send_ok, _ = email_armed()
    if send_ok:
        registry.register(
            ToolSpec(
                name="email_send",
                owner=owner_agent,
                description=(
                    "Send email as this citizen's house identity (not Jon's personal "
                    "Gmail). Default From is their SOVERYN/CWG alias; optional "
                    "`from` must be on their allowlist (Aetheria/Vett may send-as "
                    "pondwright@carolinawatergardens.com for CWG). Gate-approved "
                    "egress only — no spam, no unsolicited bulk. Args: to, subject, "
                    "body; optional from."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": "Recipient address or comma-separated list (max 10).",
                        },
                        "subject": {"type": "string"},
                        "body": {"type": "string"},
                        "from": {
                            "type": "string",
                            "description": (
                                "Optional From override — must be an allowlisted "
                                "alias for this citizen (or pondwright desk for "
                                "Aetheria/Vett)."
                            ),
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
                handler=_send_for(owner_agent),
            )
        )
        n += 1
    list_ok, _ = email_list_armed()
    if list_ok:
        registry.register(
            ToolSpec(
                name="email_list",
                owner=owner_agent,
                description=(
                    "List recent INBOX headers via house IMAP (from, subject, date). "
                    "Does not delete or mark mail. House mailbox only — not Jon's "
                    "personal inbox."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "How many recent messages (1–30).",
                            "default": 10,
                        },
                    },
                },
                handler=_list_inbox,
            )
        )
        n += 1
    return n
