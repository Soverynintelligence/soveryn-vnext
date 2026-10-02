"""Plugin API v1 — protocol, no-op base, and shared hook types."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

PLUGIN_API = 1


@dataclass(frozen=True)
class Worker:
    """One background thread a plugin wants started at boot."""

    name: str
    target: Callable[..., Any]
    daemon: bool = True
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SoverynPlugin(Protocol):
    """Contract core loads. Major version is ``PLUGIN_API`` (currently 1)."""

    id: str
    api_version: int

    def connectors(self) -> Iterable[Any]: ...
    def default_grants(self) -> Mapping[str, tuple[str, ...]]: ...
    def armed(self, connector_id: str) -> tuple[bool, str]: ...
    def register(self, ctx: Any, connector_id: str, owner: str) -> None: ...
    def gated_tools(self) -> frozenset[str]: ...
    def auto_approve_tools(self) -> frozenset[str]: ...
    def automation_auto_approve_tools(self) -> frozenset[str]: ...
    def ungated_tools(self) -> frozenset[str]: ...
    def background_workers(self, app: Any) -> list[Worker]: ...
    def chat_image_hooks(
        self,
    ) -> list[Callable[[str, tuple[str, ...]], str | None]]: ...


class PluginBase:
    """No-op defaults. 2a hooks are implemented by the CWG adapter; 2b stay empty."""

    id: str = ""
    api_version: int = PLUGIN_API
    version: str = "0"

    def connectors(self) -> Iterable[Any]:
        return ()

    def default_grants(self) -> Mapping[str, tuple[str, ...]]:
        return {}

    def armed(self, connector_id: str) -> tuple[bool, str]:
        return False, f"plugin {self.id!r} does not own {connector_id!r}"

    def register(self, ctx: Any, connector_id: str, owner: str) -> None:
        return None

    def gated_tools(self) -> frozenset[str]:
        return frozenset()

    def auto_approve_tools(self) -> frozenset[str]:
        return frozenset()

    def automation_auto_approve_tools(self) -> frozenset[str]:
        return frozenset()

    def ungated_tools(self) -> frozenset[str]:
        return frozenset()

    def background_workers(self, app: Any) -> list[Worker]:
        return []

    def chat_image_hooks(
        self,
    ) -> list[Callable[[str, tuple[str, ...]], str | None]]:
        return []

    # ── 2b seams (no-op in 2a) ────────────────────────────────────────────

    def prompt_fragments(self, agent: str) -> str:
        return ""

    def skills_dirs(self) -> Mapping[str, Path]:
        return {}

    def routines_dirs(self) -> list[Path]:
        return []

    def file_away_buckets(self) -> Mapping[str, Path]:
        return {}

    def ledger_books(self) -> list[Any]:
        return []

    def email_identities(self) -> Mapping[str, dict[str, Any]]:
        return {}

    def extra_allowed_roots(self, agent: str) -> list[Path]:
        return []

    def mission_control_glance(self) -> Any | None:
        return None

    def surfaces(self) -> list[Any]:
        return []

    def research_bar(self, desk: str) -> str:
        return ""

    def stale_prefixes(self) -> Mapping[str, int]:
        return {}
