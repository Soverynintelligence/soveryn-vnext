"""HTTP client for https://api.botdirectory.ai (no API key)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_BASE = "https://api.botdirectory.ai"
DEFAULT_TIMEOUT = 20.0
USER_AGENT = "SOVERYN-vNext/1 (+local; botdirectory browse; contact: jdeoliveira@soverynintelligence.com)"
MAX_LIMIT = 50


class BotDirectoryError(RuntimeError):
    """Raised when the directory cannot be reached or returns bad data."""


@dataclass(frozen=True)
class BotSummary:
    slug: str
    name: str
    category: str
    integrations: tuple[str, ...]
    prompt: str
    contributor: str
    detail_url: str
    source_url: str | None
    added_at: str | None

    def as_dict(self, *, include_prompt: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "integrations": list(self.integrations),
            "contributor": self.contributor,
            "detail_url": self.detail_url,
            "source_url": self.source_url,
            "added_at": self.added_at,
            "prompt_chars": len(self.prompt),
        }
        if include_prompt:
            out["prompt"] = self.prompt
        else:
            # Short preview so list results don't blow context.
            preview = self.prompt.strip().replace("\n", " ")
            out["prompt_preview"] = (preview[:220] + "…") if len(preview) > 220 else preview
        return out


def _http_get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        raise BotDirectoryError(f"HTTP {e.code} from botdirectory: {body}") from e
    except urllib.error.URLError as e:
        raise BotDirectoryError(f"botdirectory unreachable: {e.reason}") from e
    except TimeoutError as e:
        raise BotDirectoryError("botdirectory request timed out") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BotDirectoryError(f"botdirectory returned non-JSON: {e}") from e
    if not isinstance(data, dict):
        raise BotDirectoryError("botdirectory payload was not an object")
    return data


def _parse_bot(raw: dict[str, Any]) -> BotSummary | None:
    slug = str(raw.get("slug") or "").strip()
    name = str(raw.get("name") or "").strip()
    prompt = str(raw.get("prompt") or "")
    if not slug or not name or not prompt.strip():
        return None
    integrations = raw.get("integrations") or []
    if not isinstance(integrations, list):
        integrations = []
    return BotSummary(
        slug=slug,
        name=name,
        category=str(raw.get("category") or "").strip() or "Uncategorized",
        integrations=tuple(str(x) for x in integrations if x),
        prompt=prompt,
        contributor=str(raw.get("contributor") or "").strip(),
        detail_url=str(raw.get("detailUrl") or f"https://botdirectory.ai/bots/{slug}/"),
        source_url=(str(raw["sourceUrl"]) if raw.get("sourceUrl") else None),
        added_at=(str(raw["addedAt"]) if raw.get("addedAt") else None),
    )


def search_bots(
    *,
    q: str | None = None,
    category: str | None = None,
    integration: str | None = None,
    limit: int = 10,
    page: int = 1,
    sort: str = "newest",
    base_url: str = DEFAULT_BASE,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Search/browse the public catalog. Prompts returned as previews only."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    page = max(1, int(page))
    sort = sort if sort in ("newest", "name") else "newest"
    params: dict[str, str] = {
        "limit": str(limit),
        "page": str(page),
        "sort": sort,
    }
    if q and q.strip():
        params["q"] = q.strip()
    if category and category.strip():
        params["category"] = category.strip()
    if integration and integration.strip():
        params["integration"] = integration.strip()
    url = f"{base_url.rstrip('/')}/api/bots?{urllib.parse.urlencode(params)}"
    data = _http_get(url, timeout=timeout)
    bots_raw = data.get("bots") or []
    if not isinstance(bots_raw, list):
        raise BotDirectoryError("botdirectory.bots was not a list")
    bots = []
    for item in bots_raw:
        if isinstance(item, dict):
            parsed = _parse_bot(item)
            if parsed:
                bots.append(parsed.as_dict(include_prompt=False))
    return {
        "ok": True,
        "count": len(bots),
        "page": page,
        "limit": limit,
        "filters": {"q": q, "category": category, "integration": integration, "sort": sort},
        "bots": bots,
        "note": (
            "Prompts are previews only. Use import_bot_charter(slug=…) to save a "
            "full charter locally. Imports are NEVER auto-scheduled."
        ),
    }


def fetch_bot(
    slug: str,
    *,
    base_url: str = DEFAULT_BASE,
    timeout: float = DEFAULT_TIMEOUT,
) -> BotSummary:
    """Fetch one bot by slug (full prompt).

    Public API has no single-bot route; try search, then walk cursor pages.
    """
    slug = (slug or "").strip().lower()
    if not slug:
        raise BotDirectoryError("slug must be non-empty")

    def _scan(items: list[Any]) -> BotSummary | None:
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = _parse_bot(item)
            if parsed and parsed.slug == slug:
                return parsed
        return None

    # 1) Text — often enough when slug tokens appear in the prompt/name.
    data = _http_get(
        f"{base_url.rstrip('/')}/api/bots?{urllib.parse.urlencode({'q': slug, 'limit': '50'})}",
        timeout=timeout,
    )
    found = _scan(data.get("bots") or [])
    if found:
        return found

    # 2) Cursor walk (append-safe catalog sync). Cap pages to bound cost.
    cursor = "start"
    for _ in range(30):
        page = _http_get(
            f"{base_url.rstrip('/')}/api/bots?{urllib.parse.urlencode({'cursor': cursor, 'limit': '100'})}",
            timeout=timeout,
        )
        found = _scan(page.get("bots") or [])
        if found:
            return found
        sync = page.get("sync") or {}
        if not sync.get("hasMore") or not sync.get("nextCursor"):
            break
        cursor = str(sync["nextCursor"])

    raise BotDirectoryError(f"no bot with slug {slug!r}")
