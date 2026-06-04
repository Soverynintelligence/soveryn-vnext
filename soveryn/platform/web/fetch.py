"""URL fetch + main-content extraction via trafilatura.

Two protections wrap the fetch:
  1. Scheme whitelist (http/https only)
  2. SSRF guard — resolve the hostname and reject any address in
     loopback, private, link-local, multicast, or reserved ranges.
     A model can be socially-engineered into hitting `http://localhost/`
     or an internal 10.x service; this guard makes that infeasible
     regardless of the model's compliance.

Trafilatura's `extract()` pulls the article body and title out of the
HTML, dropping navbars / footers / ads. Output is capped to max_chars
so a single fetched page can't blow Aetheria's context budget.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

try:
    import trafilatura  # type: ignore
except ImportError as e:  # pragma: no cover — surface clearly at import time
    raise ImportError(
        "trafilatura is required for soveryn.platform.web.fetch. "
        "Install it with `pip install trafilatura` in the soveryn env."
    ) from e


ALLOWED_SCHEMES = frozenset({"http", "https"})
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_CHARS = 8000
MAX_BYTES = 1_048_576  # 1 MB hard cap on response body
USER_AGENT = "soveryn-vnext/0 (+local; sovereign research agent)"


class FetchError(RuntimeError):
    """Raised when the fetch fails for any reason other than SSRF."""


class SSRFError(FetchError):
    """Raised when the requested URL resolves to a forbidden address."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    title: str
    content: str
    truncated: bool


def fetch_and_extract(
    url: str,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    user_agent: str | None = None,
) -> FetchedPage:
    """Fetch `url`, extract main content via trafilatura, return FetchedPage.

    Order of checks:
      1. URL well-formedness + scheme whitelist
      2. SSRF guard on resolved address(es)
      3. HTTP GET with timeout and byte cap
      4. trafilatura.extract on the response body

    `user_agent`: optional override. Tool factories pass an agent-specific
    UA so external services see which sovereign agent is fetching. None
    falls back to the generic USER_AGENT.
    """
    if not isinstance(url, str) or not url.strip():
        raise FetchError("url must be a non-empty string")
    if max_chars <= 0:
        raise FetchError("max_chars must be positive")

    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise FetchError(
            f"scheme {parsed.scheme!r} not allowed (only http/https)"
        )
    host = parsed.hostname
    if not host:
        raise FetchError("url has no hostname")

    _guard_against_ssrf(host)

    req = urllib.request.Request(
        url.strip(),
        headers={
            "User-Agent": user_agent or USER_AGENT,
            "Accept": "text/html,*/*",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_BYTES + 1)
            status = resp.status
            final_url = resp.geturl()
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}: {e.reason}") from e
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        raise FetchError(f"unreachable: {e}") from e

    if not (200 <= status < 300):
        raise FetchError(f"non-2xx status: {status}")
    truncated_bytes = len(body) > MAX_BYTES
    if truncated_bytes:
        body = body[:MAX_BYTES]

    # If a redirect chain landed on a private/loopback address, refuse.
    # The initial guard only checked the URL-as-given.
    final_host = urllib.parse.urlparse(final_url).hostname
    if final_host and final_host != host:
        _guard_against_ssrf(final_host)

    extracted = trafilatura.extract(
        body,
        include_comments=False,
        include_tables=False,
        with_metadata=True,
        output_format="json",
    )
    title = ""
    content = ""
    if extracted:
        import json as _json
        try:
            meta = _json.loads(extracted)
            title = str(meta.get("title") or "").strip()
            content = str(meta.get("text") or meta.get("raw_text") or "").strip()
        except (_json.JSONDecodeError, TypeError):
            content = str(extracted).strip()

    # Fallback: if trafilatura couldn't extract anything, surface that
    # honestly rather than returning an empty page silently.
    if not content:
        raise FetchError(
            "trafilatura found no readable content "
            "(page may be JS-rendered, paywalled, or non-article)"
        )

    truncated = truncated_bytes or len(content) > max_chars
    if len(content) > max_chars:
        content = content[:max_chars]

    return FetchedPage(
        url=final_url,
        title=title,
        content=content,
        truncated=truncated,
    )


def _guard_against_ssrf(host: str) -> None:
    """Resolve `host` via getaddrinfo and reject if any resolved address
    sits in a private/loopback/link-local/multicast/reserved range.

    We check ALL resolved addresses (IPv4 + IPv6) — a hostname that
    resolves to one public and one private address is still blocked.
    """
    # If the host is a literal IP, ipaddress.ip_address parses it; otherwise
    # getaddrinfo gives us the resolved set.
    addresses: list[str] = []
    try:
        ip = ipaddress.ip_address(host)
        addresses = [str(ip)]
    except ValueError:
        try:
            for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
                if fam == socket.AF_INET:
                    addresses.append(sockaddr[0])
                elif fam == socket.AF_INET6:
                    addresses.append(sockaddr[0])
        except socket.gaierror as e:
            raise SSRFError(f"could not resolve host {host!r}: {e}") from e
    if not addresses:
        raise SSRFError(f"no addresses resolved for {host!r}")
    for addr in addresses:
        try:
            ip_obj = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip_obj.is_loopback
            or ip_obj.is_private
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            raise SSRFError(
                f"refusing to fetch — {host!r} resolves to forbidden address {addr}"
            )
