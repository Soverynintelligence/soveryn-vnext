"""Frozen core surface a plugin may import (API v1).

External CWG code should import from here, not from ``soveryn.platform.*``.
The in-tree adapter still wraps the original modules directly.
"""
from __future__ import annotations

from pathlib import Path

from soveryn.agents.signal_bridge.client import SignalCliError, send_once
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.config.loader import DEFAULT_DATA_ROOT
from soveryn.paths import SoverynPaths
from soveryn.platform.intake.pdf import ExtractResult, extract_pdf_path
from soveryn.platform.intake.tools import (
    _DEFAULT_ALLOWED_ROOTS,
    _resolve_allowed,
)
from soveryn.platform.intake.turn_files import parse_current_index, pick_current
from soveryn.platform.intake.turn_images import current_turn_images
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec
from soveryn.platform.vision_types import ALLOWED_IMAGE_MIME_PREFIXES
from soveryn.platform.webpush.notify import notify_needs_you, notify_pondwright_lead

# Public aliases for the intake helpers (2b will drop the underscore names).
DEFAULT_ALLOWED_ROOTS = _DEFAULT_ALLOWED_ROOTS
resolve_allowed = _resolve_allowed


def data_root() -> Path:
    """House data directory (``SOVERYN_DATA_ROOT`` / ``SoverynPaths``)."""
    return Path(DEFAULT_DATA_ROOT)


def repo_root() -> Path:
    """vNext checkout root via ``SoverynPaths`` (never the plugin's ``__file__``)."""
    return SoverynPaths.root()


def notify_lead(
    *,
    title: str,
    body: str = "",
    url: str = "/messages",
    tag: str | None = None,
) -> None:
    """Generic phone ping. Prefer this over the PondWright-named helper."""
    notify_needs_you(title=title, body=body, url=url, tag=tag)


__all__ = [
    "ALLOWED_IMAGE_MIME_PREFIXES",
    "DEFAULT_ALLOWED_ROOTS",
    "DEFAULT_DATA_ROOT",
    "ExtractResult",
    "SignalBridgeConfig",
    "SignalCliError",
    "SoverynPaths",
    "ToolArgError",
    "ToolRegistry",
    "ToolSpec",
    "current_turn_images",
    "data_root",
    "extract_pdf_path",
    "notify_lead",
    "notify_needs_you",
    "notify_pondwright_lead",
    "parse_current_index",
    "pick_current",
    "repo_root",
    "resolve_allowed",
    "send_once",
]
