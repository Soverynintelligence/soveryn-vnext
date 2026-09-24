"""Google Business Profile config — CWG listing, OAuth once."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

SCOPE = "https://www.googleapis.com/auth/business.manage"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8766/oauth/gbp/callback"
DEFAULT_CTA = "https://carolinawatergardens.com"
CAPTION_LIMIT = 1500


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


@dataclass(frozen=True)
class GbpConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: Path
    location_path: Path
    location: str
    cta_url: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return self.token_path.is_file()


def load_config() -> GbpConfig:
    root = _data_root() / "gbp"
    loc = _clean(os.environ.get("SOVERYN_GBP_LOCATION"))
    loc_file = root / "location.json"
    if not loc and loc_file.is_file():
        try:
            import json

            loc = str(json.loads(loc_file.read_text(encoding="utf-8")).get("name") or "")
        except (OSError, ValueError):
            loc = ""
    return GbpConfig(
        client_id=_clean(os.environ.get("SOVERYN_GBP_CLIENT_ID")),
        client_secret=_clean(os.environ.get("SOVERYN_GBP_CLIENT_SECRET")),
        redirect_uri=_clean(os.environ.get("SOVERYN_GBP_REDIRECT_URI"))
        or DEFAULT_REDIRECT_URI,
        token_path=root / "tokens.json",
        location_path=loc_file,
        location=loc,
        cta_url=_clean(os.environ.get("SOVERYN_GBP_CTA_URL")) or DEFAULT_CTA,
    )
