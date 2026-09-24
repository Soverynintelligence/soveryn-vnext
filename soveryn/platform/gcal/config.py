"""Google Calendar config — CWG calendar for Eve.

Reuses the GBP OAuth client (same Google Cloud project / CWG Google account).
Tokens are stored separately so Calendar consent does not rewrite GBP tokens.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8767/oauth/gcal/callback"
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_CALENDAR = "primary"


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    try:
        from soveryn.config.loader import DEFAULT_DATA_ROOT

        return Path(DEFAULT_DATA_ROOT)
    except Exception:
        return Path.home() / "soveryn_vnext" / "data"


def _clean(raw: str | None) -> str:
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def _load_house_env() -> None:
    """Fill missing os.environ keys from ~/soveryn_vnext/.env.

    Jon's login shells are often (base) in ~ and never `source .env`,
    which made `python -m soveryn.platform.gcal authorize` claim the
    client was unset after he had already saved it.
    """
    path = Path.home() / "soveryn_vnext" / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, val = s.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _clean(val)


@dataclass(frozen=True)
class GcalConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: Path
    calendar_id: str
    timezone: str
    ical_url: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return self.token_path.is_file()

    @property
    def ical_configured(self) -> bool:
        return self.ical_url.startswith("https://")


def load_config() -> GcalConfig:
    _load_house_env()
    root = _data_root() / "gcal"
    client_id = _clean(os.environ.get("SOVERYN_GCAL_CLIENT_ID")) or _clean(
        os.environ.get("SOVERYN_GBP_CLIENT_ID")
    )
    client_secret = _clean(os.environ.get("SOVERYN_GCAL_CLIENT_SECRET")) or _clean(
        os.environ.get("SOVERYN_GBP_CLIENT_SECRET")
    )
    return GcalConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=_clean(os.environ.get("SOVERYN_GCAL_REDIRECT_URI"))
        or DEFAULT_REDIRECT_URI,
        token_path=root / "tokens.json",
        calendar_id=_clean(os.environ.get("SOVERYN_GCAL_CALENDAR_ID"))
        or DEFAULT_CALENDAR,
        timezone=_clean(os.environ.get("SOVERYN_GCAL_TIMEZONE")) or DEFAULT_TIMEZONE,
        ical_url=_clean(os.environ.get("SOVERYN_GCAL_ICAL_URL")),
    )
