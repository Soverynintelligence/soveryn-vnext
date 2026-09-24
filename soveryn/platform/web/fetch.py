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

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass

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
_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


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
      2. SSRF guard on resolved address(es), then connect to that address
      3. Same check on every redirect, before the next connection
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

    headers = {
        "User-Agent": user_agent or USER_AGENT,
        "Accept": "text/html,*/*",
    }
    try:
        final_url, body = _fetch_checked(url.strip(), timeout=timeout, headers=headers)
    except SSRFError:
        raise
    except (http.client.HTTPException, socket.timeout, TimeoutError, OSError) as e:
        raise FetchError(f"unreachable: {e}") from e

    truncated_bytes = len(body) > MAX_BYTES
    if truncated_bytes:
        body = body[:MAX_BYTES]

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


def _fetch_checked(url: str, *, timeout: float, headers: dict[str, str]) -> tuple[str, bytes]:
    """GET url, following redirects only after each hop passes the SSRF guard.

    The connection is pinned to the address the guard approved, so a name
    that changes answer between the check and the dial cannot land on a
    private address.
    """
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        parsed = urllib.parse.urlparse(current)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise FetchError(
                f"scheme {parsed.scheme!r} not allowed (only http/https)"
            )
        host = parsed.hostname
        if not host:
            raise FetchError("url has no hostname")
        ip = _public_ip(host)
        status, resp_headers, body = _open_pinned(
            current, ip, timeout=timeout, headers=headers,
        )
        if 200 <= status < 300:
            return current, body
        if status in _REDIRECT_STATUSES:
            loc = _header(resp_headers, "Location")
            if not loc:
                raise FetchError(f"redirect {status} with no Location")
            current = urllib.parse.urljoin(current, loc)
            continue
        raise FetchError(f"non-2xx status: {status}")
    raise FetchError(f"more than {_MAX_REDIRECTS} redirects")


def _header(headers: list[tuple[str, str]], name: str) -> str:
    want = name.lower()
    for key, value in headers:
        if key.lower() == want:
            return value
    return ""


def _open_pinned(
    url: str,
    ip: str,
    *,
    timeout: float,
    headers: dict[str, str],
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Connect to `ip` while presenting the URL's hostname (Host and SNI)."""
    parsed = urllib.parse.urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    hostname = parsed.hostname or ""
    conn_host = f"[{hostname}]" if ":" in hostname else hostname
    conn: http.client.HTTPConnection
    if parsed.scheme == "https":
        conn = _PinnedHTTPS(
            conn_host, port, pin=ip, timeout=timeout,
            context=ssl.create_default_context(), sni=hostname,
        )
    else:
        conn = _PinnedHTTP(conn_host, port, pin=ip, timeout=timeout)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read(MAX_BYTES + 1)
        return resp.status, list(resp.getheaders()), body
    finally:
        conn.close()


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, *, pin: str, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._pin = pin

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pin, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(
        self, host: str, port: int, *, pin: str, timeout: float,
        context: ssl.SSLContext, sni: str,
    ):
        super().__init__(host, port, timeout=timeout, context=context)
        self._pin = pin
        self._sni = sni

    def connect(self) -> None:
        raw = socket.create_connection((self._pin, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self._sni)


def _resolved_addresses(host: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses: list[str] = []
        try:
            for fam, _, _, _, sockaddr in socket.getaddrinfo(host, None):
                if fam == socket.AF_INET:
                    addresses.append(sockaddr[0])
                elif fam == socket.AF_INET6:
                    addresses.append(sockaddr[0])
        except socket.gaierror as e:
            raise SSRFError(f"could not resolve host {host!r}: {e}") from e
        return addresses


def _forbidden(addr: str) -> bool:
    try:
        ip_obj = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return bool(
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def _public_ip(host: str) -> str:
    """One approved address from a single lookup.

    Raises if any resolved address is forbidden. The caller connects to
    the returned address and does not look the name up again.
    """
    addresses = _resolved_addresses(host)
    if not addresses:
        raise SSRFError(f"no addresses resolved for {host!r}")
    for addr in addresses:
        if _forbidden(addr):
            raise SSRFError(
                f"refusing to fetch — {host!r} resolves to forbidden address {addr}"
            )
    return addresses[0]


def _guard_against_ssrf(host: str) -> None:
    """Resolve `host` via getaddrinfo and reject if any resolved address
    sits in a private/loopback/link-local/multicast/reserved range.

    We check ALL resolved addresses (IPv4 + IPv6) — a hostname that
    resolves to one public and one private address is still blocked.
    """
    _public_ip(host)
