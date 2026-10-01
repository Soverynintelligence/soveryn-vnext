"""Canva Connect configuration from env + data root."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_SCOPES: tuple[str, ...] = (
    "design:content:read",
    "design:content:write",
    "design:meta:read",
    "asset:read",
    "asset:write",
    "brandtemplate:content:read",
    "brandtemplate:meta:read",
)

# Local loopback for the OAuth CLI callback listener.
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8765/oauth/canva/callback"

AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
API_BASE = "https://api.canva.com/rest/v1"


@dataclass(frozen=True)
class CanvaConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    token_path: Path
    media_dir: Path
    scopes: tuple[str, ...]
    # Optional brand → brand_template_id map (env JSON or file later).
    brand_templates: dict[str, str]

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def authorized(self) -> bool:
        return self.token_path.is_file()


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    try:
        from soveryn.config.loader import DEFAULT_DATA_ROOT

        return Path(DEFAULT_DATA_ROOT)
    except Exception:
        return Path.home() / "soveryn_vnext" / "data"


def load_brand_templates() -> dict[str, str]:
    """SOVERYN_CANVA_TEMPLATES=hl:ID,soveryn:ID,cwg:ID"""
    raw = (os.environ.get("SOVERYN_CANVA_TEMPLATES") or "").strip()
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        brand, tid = part.split(":", 1)
        brand, tid = brand.strip().lower(), tid.strip()
        if brand and tid:
            out[brand] = tid
    return out


def _clean_secret(raw: str | None) -> str:
    """Strip whitespace and accidental wrapping quotes from env values."""
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        s = s[1:-1].strip()
    return s


def load_config(*, data_root: Path | None = None) -> CanvaConfig:
    root = Path(data_root) if data_root is not None else _data_root()
    canva_dir = root / "canva"
    media = root / "media" / "canva"
    return CanvaConfig(
        client_id=_clean_secret(os.environ.get("SOVERYN_CANVA_CLIENT_ID")),
        client_secret=_clean_secret(os.environ.get("SOVERYN_CANVA_CLIENT_SECRET")),
        redirect_uri=_clean_secret(
            os.environ.get("SOVERYN_CANVA_REDIRECT_URI")
        )
        or DEFAULT_REDIRECT_URI,
        token_path=canva_dir / "tokens.json",
        media_dir=media,
        scopes=DEFAULT_SCOPES,
        brand_templates=load_brand_templates(),
    )
