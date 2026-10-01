"""Google Business Profile client — CWG local posts. No passwords."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from soveryn.platform.gbp.config import CAPTION_LIMIT, GbpConfig, load_config
from soveryn.platform.gbp.oauth import GbpAuthError, get_access_token
from soveryn.platform.social.instagram_desk import DEFAULT_INBOX, list_inbox_images

HttpFn = Callable[..., dict[str, Any]]

ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
LOCATIONS_TMPL = (
    "https://mybusinessbusinessinformation.googleapis.com/v1/{account}/locations"
)
POSTS_TMPL = "https://mybusiness.googleapis.com/v4/{location}/localPosts"


class GbpError(RuntimeError):
    def __init__(self, message: str, *, status: str = "error", http_status: int = 0):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def _default_http(
    url: str,
    *,
    method: str = "GET",
    token: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", "replace")[:800]
        if e.code in (401, 403):
            low = err.lower()
            if "quota" in low or e.code == 403:
                raise GbpError(
                    "Google Business API quota is 0 until Google approves "
                    "the access request. See platform/gbp/SETUP.md.",
                    status="needs_api_access",
                    http_status=e.code,
                ) from e
            raise GbpError(
                "Google session expired. Jon re-runs "
                "`python -m soveryn.platform.gbp authorize`.",
                status="needs_login",
                http_status=e.code,
            ) from e
        raise GbpError(
            f"GBP HTTP {e.code}: {err}", status="error", http_status=e.code
        ) from e


def _save_location(path: Path, name: str, title: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"name": name, "title": title}, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_location(
    cfg: GbpConfig,
    token: str,
    *,
    http: HttpFn = _default_http,
) -> str:
    if cfg.location:
        return cfg.location
    accounts = http(ACCOUNTS_URL, method="GET", token=token)
    accs = accounts.get("accounts") or []
    if not accs:
        raise GbpError(
            "No Google Business accounts on this login.",
            status="needs_location",
        )
    account = accs[0].get("name") or ""
    q = urllib.parse.urlencode({"readMask": "name,title"})
    locs = http(
        f"{LOCATIONS_TMPL.format(account=account)}?{q}",
        method="GET",
        token=token,
    )
    locations = locs.get("locations") or []
    if not locations:
        raise GbpError(
            "No locations on this Google Business account.",
            status="needs_location",
        )
    chosen = None
    for loc in locations:
        title = str(loc.get("title") or "")
        if "carolina" in title.lower() or "water garden" in title.lower():
            chosen = loc
            break
    if chosen is None:
        if len(locations) == 1:
            chosen = locations[0]
        else:
            titles = [str(x.get("title") or x.get("name")) for x in locations]
            raise GbpError(
                "Several listings — set SOVERYN_GBP_LOCATION to the CWG "
                f"accounts/.../locations/... id. Saw: {titles}",
                status="needs_location",
            )
    name = str(chosen.get("name") or "")
    if not name:
        raise GbpError("Location missing name.", status="needs_location")
    # Business Information API returns locations/{id}; posts API wants
    # accounts/{a}/locations/{id}.
    if name.startswith("locations/") and account:
        name = f"{account}/{name}"
    _save_location(cfg.location_path, name, str(chosen.get("title") or ""))
    return name


def create_local_post(
    *,
    summary: str,
    image_path: str | None = None,
    cfg: GbpConfig | None = None,
    token: str | None = None,
    http: HttpFn | None = None,
) -> dict[str, Any]:
    """Create a STANDARD CWG local post. Photo is optional (public URL not required
    for text). Local files are noted if we cannot attach them yet."""
    config = cfg or load_config()
    if not config.configured:
        return {
            "ok": False,
            "status": "needs_oauth_client",
            "thread_note": (
                "Set SOVERYN_GBP_CLIENT_ID and SOVERYN_GBP_CLIENT_SECRET, "
                "then `python -m soveryn.platform.gbp authorize`."
            ),
        }
    http_fn = http or _default_http
    text = (summary or "").strip()
    if not text:
        return {"ok": False, "status": "error", "message": "empty summary"}
    if len(text) > CAPTION_LIMIT:
        text = text[: CAPTION_LIMIT - 1] + "…"
    try:
        tok = token if token is not None else get_access_token(config)
        location = resolve_location(config, tok, http=http_fn)
        body: dict[str, Any] = {
            "languageCode": "en-US",
            "summary": text,
            "topicType": "STANDARD",
            "callToAction": {
                "actionType": "LEARN_MORE",
                "url": config.cta_url,
            },
        }
        photo_note = ""
        if image_path:
            photo_note = (
                " Text posted. GBP local posts need a public image URL or "
                "media upload — photo was not attached. Drop on the listing "
                "by hand if needed."
            )
        posted = http_fn(
            POSTS_TMPL.format(location=location),
            method="POST",
            token=tok,
            body=body,
        )
        name = posted.get("name") or ""
        return {
            "ok": True,
            "status": "posted",
            "platform": "google_business",
            "brand": "cwg",
            "name": name,
            "thread_note": (
                "Posted to CWG Google Business Profile."
                + photo_note
            ),
        }
    except GbpAuthError as e:
        return {
            "ok": False,
            "status": "needs_login",
            "message": str(e),
            "thread_note": (
                "GBP not authorized. Jon runs "
                "`python -m soveryn.platform.gbp authorize` (Google Cloud "
                "client + access request). I do not type passwords."
            ),
        }
    except GbpError as e:
        return {
            "ok": False,
            "status": e.status,
            "message": str(e),
            "thread_note": str(e),
        }


def gbp_status(*, cfg: GbpConfig | None = None) -> dict[str, Any]:
    config = cfg or load_config()
    inbox = list_inbox_images(DEFAULT_INBOX)
    return {
        "configured": config.configured,
        "authorized": config.authorized,
        "location_set": bool(config.location),
        "cta_url": config.cta_url,
        "inbox_count": len(inbox),
        "authorize": "python -m soveryn.platform.gbp authorize",
    }
