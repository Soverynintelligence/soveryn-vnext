"""Send Web Push to subscribed Messages PWAs — Gate / needs-you / overnight briefs."""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


def notify_needs_you(
    *,
    title: str,
    body: str = "",
    url: str = "/messages",
    tag: str | None = None,
) -> None:
    """Fire-and-forget push. Never raises into the caller (Gate / tools)."""
    try:
        threading.Thread(
            target=_send_all,
            kwargs={
                "title": title,
                "body": body,
                "url": url,
                "tag": tag or "soveryn-needs-you",
            },
            name="webpush-needs-you",
            daemon=True,
        ).start()
    except Exception:
        logger.exception("webpush: failed to spawn notify thread")


def _send_all(*, title: str, body: str, url: str, tag: str) -> None:
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("webpush: pywebpush not installed — skip notify")
        return

    from soveryn.platform.webpush.keys import load_vapid
    from soveryn.platform.webpush import store as push_store

    try:
        vapid = load_vapid()
    except Exception:
        logger.exception("webpush: VAPID load failed")
        return

    subs = push_store.list_subscriptions()
    if not subs:
        logger.debug("webpush: no subscriptions — skip")
        return

    payload = {
        "title": title[:80],
        "body": (body or "")[:140],
        "url": url,
        "tag": tag,
    }
    import json

    data = json.dumps(payload)
    claims = {"sub": vapid.get("subject") or "mailto:jon@soveryn.local"}
    dead: list[str] = []

    for row in subs:
        try:
            webpush(
                subscription_info=push_store.subscription_info(row),
                data=data,
                vapid_private_key=vapid["privateKeyPem"],
                vapid_claims=claims,
                ttl=120,
                timeout=10,
            )
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning(
                "webpush: send failed endpoint=…%s status=%s err=%s",
                row["endpoint"][-24:],
                status,
                exc,
            )
            if status in (404, 410):
                dead.append(row["endpoint"])
        except Exception:
            logger.exception(
                "webpush: send error endpoint=…%s", row["endpoint"][-24:]
            )

    for endpoint in dead:
        try:
            push_store.remove_subscription(endpoint)
        except Exception:
            logger.exception("webpush: failed pruning dead endpoint")


_LABELS = {
    "aetheria": "Aetheria",
    "eve": "Eve",
    "vett": "Vett",
    "scotty": "Scotty",
    "kernel": "Kernel",
}


def _label(citizen: str) -> str:
    who = (citizen or "house").strip().lower() or "house"
    return _LABELS.get(who, who[:1].upper() + who[1:])


def notify_gate(*, citizen: str, tool: str, approval_id: str) -> None:
    who = (citizen or "aetheria").strip().lower() or "aetheria"
    tool_s = (tool or "action").strip()
    notify_needs_you(
        title=f"{_label(who)} needs Gate",
        body=f"Allow {tool_s}?" if tool_s else "Needs your yes",
        url=f"/messages/{who}",
        tag=f"gate-{approval_id}" if approval_id else f"gate-{who}",
    )


def notify_share(*, agent: str, preview: str = "") -> None:
    who = (agent or "aetheria").strip().lower() or "aetheria"
    notify_needs_you(
        title=f"{_label(who)} — needs you",
        body=(preview or "Open Messages").strip()[:140],
        url=f"/messages/{who}",
        tag=f"share-{who}",
    )


def notify_overnight_brief(
    *,
    teammate_id: str,
    routine: str = "",
    status: str = "ok",
) -> None:
    """Thin heads-up when Critic/Scout lands in Messages — where to look, not the essay."""
    who = (teammate_id or "").strip().lower()
    agent = {"critic": "t_critic", "scout": "t_scout"}.get(who, "")
    if not agent:
        return
    name = "Critic" if who == "critic" else "Scout" if who == "scout" else who.title()
    bit = (routine or "overnight").strip() or "overnight"
    st = (status or "ok").strip() or "ok"
    notify_needs_you(
        title=f"{name} brief ready",
        body=f"{bit} · {st} — open Messages → {name}",
        url=f"/messages/{agent}",
        tag=f"overnight-{who}",
    )
