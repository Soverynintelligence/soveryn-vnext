"""Discover and isolate SOVERYN plugins.

``SOVERYN_PLUGINS`` allowlist
-----------------------------
The tower needs **no env change** to keep working: unset loads the in-tree
CWG adapter and ignores any pip-installed ``soveryn-cwg``.

========== ============================================= ========================
Value      External ``soveryn.plugins`` entry points     In-tree CWG adapter
========== ============================================= ========================
unset      never loaded (fresh installs / CI fail-safe)  **loaded**
``""``     kill switch — none                            **disabled**
``cwg``    loaded if the entry imports cleanly           fallback if external missing/fails
``foo,cwg`` only allowlisted ids                         only if ``cwg`` is listed and no external ``cwg``
========== ============================================= ========================

One source per plugin id: a successful external ``cwg`` wins and the builtin
is skipped. ``ToolRegistry.register`` raises on duplicate ``(owner, name)``
and has no unregister, so double-loading must be impossible by construction.

Every hook call is wrapped. An exception logs ``plugin=<id> hook=<name>``
and degrades to "no contribution" (same contract as the CWG step-1 guards).
"""
from __future__ import annotations

import importlib.metadata
import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from soveryn.citizens.connectors import (
    CATALOG,
    CORE_ALWAYS_GATED,
    CORE_CATALOG,
    CORE_FOUNDING_GRANTS,
    FOUNDING_GRANTS,
)
from pathlib import Path

from soveryn.plugins.api import PLUGIN_API, BookDef, SoverynPlugin, Worker

logger = logging.getLogger(__name__)

_UNSET = object()
_PLUGINS_ENV = "SOVERYN_PLUGINS"
_BUILTIN_ID = "cwg"

# Sentinel: env var is absent (distinct from empty-string kill switch).
_ENV_UNSET = "__unset__"


@dataclass
class LoadedPlugin:
    id: str
    version: str
    source: str  # "builtin" | "external"
    plugin: Any
    packs: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gated: set[str] = field(default_factory=set)
    auto: set[str] = field(default_factory=set)
    automation_auto: set[str] = field(default_factory=set)
    ungated: set[str] = field(default_factory=set)
    owned_connectors: set[str] = field(default_factory=set)


@dataclass
class PluginRuntime:
    env_key: str
    plugins: list[LoadedPlugin] = field(default_factory=list)
    gated: set[str] = field(default_factory=set)
    auto: set[str] = field(default_factory=set)
    automation_auto: set[str] = field(default_factory=set)


_RUNTIME: PluginRuntime | None = None
_LOCK = threading.Lock()


def _env_key() -> str:
    if _PLUGINS_ENV not in os.environ:
        return _ENV_UNSET
    return os.environ[_PLUGINS_ENV]


def _parse_allowlist() -> tuple[bool, frozenset[str] | None]:
    """Return ``(kill_switch, external_allowlist)``.

    ``external_allowlist`` is ``None`` when the var is unset (no externals).
    An empty frozenset with ``kill_switch=True`` disables builtin too.
    A frozenset of ids is the explicit allowlist (builtin ``cwg`` only if
    ``cwg`` is listed and no external ``cwg`` loaded).
    """
    if _PLUGINS_ENV not in os.environ:
        return False, None
    raw = os.environ[_PLUGINS_ENV]
    if raw.strip() == "":
        return True, frozenset()
    return False, frozenset(p.strip() for p in raw.split(",") if p.strip())


def _external_entry_points() -> list[Any]:
    try:
        eps = importlib.metadata.entry_points(group="soveryn.plugins")
    except Exception:
        logger.exception("plugin=%s hook=%s", "-", "entry_points")
        return []
    return list(eps)


def _call_hook(loaded: LoadedPlugin, name: str, *args: Any, default: Any = None) -> Any:
    try:
        fn = getattr(loaded.plugin, name)
        return fn(*args)
    except Exception:
        logger.exception("plugin=%s hook=%s", loaded.id, name)
        loaded.errors.append(f"hook {name} raised")
        return default


def _as_plugin(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, type):
        obj = obj()
    return obj


def _plugin_version(plugin: Any, *, source: str) -> str:
    version = getattr(plugin, "version", None)
    if version:
        return str(version)
    if source == "builtin":
        return "builtin"
    return str(getattr(plugin, "api_version", PLUGIN_API))


def _restore_core_catalog() -> None:
    CATALOG.clear()
    CATALOG.update(CORE_CATALOG)
    FOUNDING_GRANTS.clear()
    FOUNDING_GRANTS.update({k: tuple(v) for k, v in CORE_FOUNDING_GRANTS.items()})


def _sanitize_sets(loaded: LoadedPlugin) -> None:
    overlap_auto = loaded.auto & CORE_ALWAYS_GATED
    for name in sorted(overlap_auto):
        logger.error(
            "plugin=%s hook=auto_approve_tools dropped CORE_ALWAYS_GATED tool=%s",
            loaded.id,
            name,
        )
        loaded.errors.append(f"dropped auto-approve of CORE_ALWAYS_GATED {name}")
        loaded.auto.discard(name)
    overlap_aa = loaded.automation_auto & CORE_ALWAYS_GATED
    for name in sorted(overlap_aa):
        logger.error(
            "plugin=%s hook=automation_auto_approve_tools dropped CORE_ALWAYS_GATED tool=%s",
            loaded.id,
            name,
        )
        loaded.errors.append(
            f"dropped automation auto-approve of CORE_ALWAYS_GATED {name}"
        )
        loaded.automation_auto.discard(name)
    overlap_ungated = loaded.ungated & CORE_ALWAYS_GATED
    for name in sorted(overlap_ungated):
        logger.error(
            "plugin=%s hook=ungated_tools dropped CORE_ALWAYS_GATED tool=%s",
            loaded.id,
            name,
        )
        loaded.errors.append(f"dropped ungated CORE_ALWAYS_GATED {name}")
        loaded.ungated.discard(name)
        loaded.gated.add(name)

    declared = set(loaded.tools)
    for name in sorted(declared):
        hits = sum(
            (
                name in loaded.gated,
                name in loaded.auto,
                name in loaded.ungated,
            )
        )
        if hits != 1:
            logger.warning(
                "plugin=%s tool=%s not declared in exactly one of "
                "gated/auto_approve/ungated; treating as gated",
                loaded.id,
                name,
            )
            loaded.auto.discard(name)
            loaded.ungated.discard(name)
            loaded.gated.add(name)


def _fill_sets_from_plugin(loaded: LoadedPlugin) -> None:
    gated = _call_hook(loaded, "gated_tools", default=frozenset()) or frozenset()
    auto = _call_hook(loaded, "auto_approve_tools", default=frozenset()) or frozenset()
    ungated = _call_hook(loaded, "ungated_tools", default=frozenset()) or frozenset()
    auto_auto = (
        _call_hook(loaded, "automation_auto_approve_tools", default=frozenset())
        or frozenset()
    )
    loaded.gated = set(gated)
    loaded.auto = set(auto)
    loaded.ungated = set(ungated)
    loaded.automation_auto = set(auto_auto)

    connectors = _call_hook(loaded, "connectors", default=()) or ()
    tools: list[str] = []
    packs: list[str] = []
    for defn in connectors:
        cid = getattr(defn, "id", None)
        if not cid:
            continue
        if cid in CATALOG:
            logger.error(
                "plugin=%s hook=connectors skipped connector=%s "
                "(id already in core catalog)",
                loaded.id,
                cid,
            )
            loaded.errors.append(f"connector {cid} collides with core catalog")
            continue
        CATALOG[cid] = defn
        loaded.owned_connectors.add(cid)
        packs.append(cid)
        for tool in getattr(defn, "tools", ()) or ():
            tools.append(str(tool))
    loaded.packs = packs
    # unique, stable
    loaded.tools = sorted(set(tools))

    grants = _call_hook(loaded, "default_grants", default={}) or {}
    for citizen, packs_for in grants.items():
        existing = list(FOUNDING_GRANTS.get(citizen, ()))
        for pack_id in packs_for or ():
            if pack_id not in existing:
                existing.append(pack_id)
        FOUNDING_GRANTS[citizen] = tuple(existing)

    _sanitize_sets(loaded)


def _load_external(
    *,
    allowlist: frozenset[str],
    seen: set[str],
) -> list[LoadedPlugin]:
    out: list[LoadedPlugin] = []
    for ep in _external_entry_points():
        name = getattr(ep, "name", "") or ""
        if name not in allowlist:
            continue
        if name in seen:
            logger.error(
                "plugin=%s hook=entry_points skipped duplicate id (one source rule)",
                name,
            )
            continue
        try:
            obj = _as_plugin(ep.load())
        except Exception:
            logger.exception("plugin=%s hook=load", name)
            continue
        if obj is None:
            logger.error("plugin=%s hook=load returned empty", name)
            continue
        pid = str(getattr(obj, "id", "") or name)
        api_ver = getattr(obj, "api_version", None)
        try:
            api_ok = int(api_ver) == PLUGIN_API
        except (TypeError, ValueError):
            api_ok = False
        if not api_ok:
            logger.error(
                "plugin=%s hook=load refused api_version=%r (need %s)",
                pid,
                api_ver,
                PLUGIN_API,
            )
            continue
        loaded = LoadedPlugin(
            id=pid,
            version=_plugin_version(obj, source="external"),
            source="external",
            plugin=obj,
        )
        _fill_sets_from_plugin(loaded)
        seen.add(pid)
        out.append(loaded)
    return out


def _load_builtin(seen: set[str]) -> LoadedPlugin | None:
    if _BUILTIN_ID in seen:
        return None
    try:
        from soveryn.plugins.builtin_cwg import BuiltinCwgPlugin

        obj: SoverynPlugin = BuiltinCwgPlugin()
    except Exception:
        logger.exception("plugin=%s hook=load", _BUILTIN_ID)
        return None
    loaded = LoadedPlugin(
        id=_BUILTIN_ID,
        version=_plugin_version(obj, source="builtin"),
        source="builtin",
        plugin=obj,
    )
    _fill_sets_from_plugin(loaded)
    seen.add(_BUILTIN_ID)
    return loaded


def _rebuild_runtime() -> PluginRuntime:
    _restore_core_catalog()
    kill, allowlist = _parse_allowlist()
    runtime = PluginRuntime(env_key=_env_key())
    if kill:
        logger.info(
            "plugins boot: (none) [SOVERYN_PLUGINS kill switch — "
            "empty string disables externals and the builtin CWG adapter]"
        )
        return runtime

    seen: set[str] = set()
    if allowlist is not None:
        runtime.plugins.extend(_load_external(allowlist=allowlist, seen=seen))
        # Builtin CWG only when `cwg` is allowlisted and no external won.
        if _BUILTIN_ID in allowlist and _BUILTIN_ID not in seen:
            builtin = _load_builtin(seen)
            if builtin is not None:
                runtime.plugins.append(builtin)
    else:
        # Unset: no externals; builtin stays so the tower needs no env change.
        builtin = _load_builtin(seen)
        if builtin is not None:
            runtime.plugins.append(builtin)

    for loaded in runtime.plugins:
        runtime.gated.update(loaded.gated)
        runtime.auto.update(loaded.auto)
        runtime.automation_auto.update(loaded.automation_auto)

    if runtime.plugins:
        summary = "; ".join(
            f"{p.id} source={p.source} version={p.version} "
            f"tools={len(p.tools)} errors={len(p.errors)}"
            for p in runtime.plugins
        )
    else:
        summary = "(none)"
    logger.info("plugins boot: %s", summary)
    return runtime


def reset_plugins() -> None:
    """Drop cached plugins and restore the core catalog (tests / env flips)."""
    global _RUNTIME
    with _LOCK:
        _RUNTIME = None
        _restore_core_catalog()
        try:
            from soveryn.platform.ledgers.registry import reset_plugin_books

            reset_plugin_books()
        except Exception:
            logger.exception("plugin=%s hook=%s", "-", "reset_plugin_books")


def ensure_loaded() -> PluginRuntime:
    """Load plugins once per ``SOVERYN_PLUGINS`` value; reload when it changes."""
    global _RUNTIME
    key = _env_key()
    with _LOCK:
        if _RUNTIME is None or _RUNTIME.env_key != key:
            _RUNTIME = _rebuild_runtime()
        return _RUNTIME


def plugin_gate_sets() -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    """Return ``(auto_approve, gated, automation_auto_approve)``."""
    rt = ensure_loaded()
    return frozenset(rt.auto), frozenset(rt.gated), frozenset(rt.automation_auto)


def plugin_owns(connector_id: str) -> bool:
    rt = ensure_loaded()
    return any(connector_id in p.owned_connectors for p in rt.plugins)


def plugin_armed(connector_id: str) -> tuple[bool, str] | None:
    rt = ensure_loaded()
    for loaded in rt.plugins:
        if connector_id not in loaded.owned_connectors:
            continue
        result = _call_hook(
            loaded, "armed", connector_id, default=(False, "plugin armed() failed")
        )
        if isinstance(result, tuple) and len(result) == 2:
            return bool(result[0]), str(result[1])
        return False, "plugin armed() returned invalid result"
    return None


def register_plugin_pack(ctx: Any, pack_id: str, owner: str) -> bool:
    """Call the owning plugin's ``register``. True if a plugin claimed ``pack_id``."""
    rt = ensure_loaded()
    for loaded in rt.plugins:
        if pack_id not in loaded.owned_connectors:
            continue
        collecting = _CollectingRegistry(ctx.registry)
        try:
            slim_ctx = replace(ctx, registry=collecting)
        except TypeError:
            ctx.registry = collecting
            slim_ctx = ctx
        _call_hook(loaded, "register", slim_ctx, pack_id, owner)
        extra = [n for n in collecting.names if n not in loaded.tools]
        if extra:
            loaded.tools = sorted(set(loaded.tools) | set(collecting.names))
            for name in extra:
                hits = sum(
                    (
                        name in loaded.gated,
                        name in loaded.auto,
                        name in loaded.ungated,
                    )
                )
                if hits != 1:
                    logger.warning(
                        "plugin=%s tool=%s registered but undeclared; treating as gated",
                        loaded.id,
                        name,
                    )
                    loaded.gated.add(name)
                    rt.gated.add(name)
        return True
    return False


def iter_chat_image_hooks() -> list[Callable[[str, tuple[str, ...]], str | None]]:
    rt = ensure_loaded()
    hooks: list[Callable[[str, tuple[str, ...]], str | None]] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "chat_image_hooks", default=[]) or []
        for hook in found:
            hooks.append(_bound_hook(loaded, "chat_image_hooks", hook))
    return hooks


def start_background_workers(app: Any) -> list[str]:
    """Start plugin ``background_workers``. Lead-watch stays default-ON."""
    rt = ensure_loaded()
    started: list[str] = []
    for loaded in rt.plugins:
        workers = _call_hook(loaded, "background_workers", app, default=[]) or []
        for worker in workers:
            if not isinstance(worker, Worker):
                logger.error(
                    "plugin=%s hook=background_workers skipped non-Worker %r",
                    loaded.id,
                    worker,
                )
                loaded.errors.append("background_workers returned a non-Worker")
                continue
            try:
                threading.Thread(
                    target=worker.target,
                    args=worker.args,
                    kwargs=worker.kwargs or {},
                    daemon=worker.daemon,
                    name=worker.name,
                ).start()
                started.append(worker.name)
            except Exception:
                logger.exception(
                    "plugin=%s hook=background_workers failed to start worker=%s",
                    loaded.id,
                    worker.name,
                )
                loaded.errors.append(f"failed to start {worker.name}")
    return started


def plugin_board_rows() -> list[dict[str, Any]]:
    rt = ensure_loaded()
    return [
        {
            "id": p.id,
            "version": p.version,
            "source": p.source,
            "packs": list(p.packs),
            "tools": list(p.tools),
            "errors": list(p.errors),
        }
        for p in rt.plugins
    ]


def _bound_hook(
    loaded: LoadedPlugin,
    hook_name: str,
    fn: Callable[..., Any],
) -> Callable[..., Any]:
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.exception("plugin=%s hook=%s", loaded.id, hook_name)
            loaded.errors.append(f"hook {hook_name} raised")
            return None

    return wrapped


def plugin_prompt_fragments(agent: str) -> str:
    rt = ensure_loaded()
    parts: list[str] = []
    for loaded in rt.plugins:
        text = _call_hook(loaded, "prompt_fragments", agent, default="") or ""
        if text:
            parts.append(str(text))
    return "".join(parts)


def plugin_skills_dirs() -> dict[str, Path]:
    rt = ensure_loaded()
    out: dict[str, Path] = {}
    for loaded in rt.plugins:
        mapping = _call_hook(loaded, "skills_dirs", default={}) or {}
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            out[str(key)] = Path(value)
    return out


def plugin_routines_dirs() -> list[Path]:
    rt = ensure_loaded()
    out: list[Path] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "routines_dirs", default=[]) or []
        for item in found:
            out.append(Path(item))
    return out


def plugin_file_away_buckets() -> dict[str, Path]:
    rt = ensure_loaded()
    out: dict[str, Path] = {}
    for loaded in rt.plugins:
        mapping = _call_hook(loaded, "file_away_buckets", default={}) or {}
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            out[str(key)] = Path(value)
    return out


def plugin_file_away_bucket_help() -> dict[str, str]:
    rt = ensure_loaded()
    out: dict[str, str] = {}
    for loaded in rt.plugins:
        mapping = _call_hook(loaded, "file_away_bucket_help", default={}) or {}
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            out[str(key)] = str(value)
    return out


def plugin_ledger_books() -> list[BookDef]:
    rt = ensure_loaded()
    out: list[BookDef] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "ledger_books", default=[]) or []
        for book in found:
            if isinstance(book, BookDef):
                out.append(book)
    return out


def plugin_email_identities() -> dict[str, dict[str, Any]]:
    rt = ensure_loaded()
    out: dict[str, dict[str, Any]] = {}
    for loaded in rt.plugins:
        mapping = _call_hook(loaded, "email_identities", default={}) or {}
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            if isinstance(value, dict):
                out[str(key)] = dict(value)
    return out


def plugin_extra_allowed_roots(agent: str) -> list[Path]:
    rt = ensure_loaded()
    out: list[Path] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "extra_allowed_roots", agent, default=[]) or []
        for item in found:
            out.append(Path(item))
    return out


def plugin_mission_control_glance() -> Any | None:
    rt = ensure_loaded()
    for loaded in rt.plugins:
        glance = _call_hook(loaded, "mission_control_glance", default=None)
        if glance is not None:
            return glance
    return None


def plugin_surfaces() -> list[Any]:
    rt = ensure_loaded()
    out: list[Any] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "surfaces", default=[]) or []
        out.extend(list(found))
    return out


def plugin_research_bar(desk: str) -> str:
    rt = ensure_loaded()
    parts: list[str] = []
    for loaded in rt.plugins:
        text = _call_hook(loaded, "research_bar", desk, default="") or ""
        if text:
            parts.append(str(text))
    return "".join(parts)


def plugin_accept_house_source(source: str, desk: str) -> bool:
    rt = ensure_loaded()
    for loaded in rt.plugins:
        hit = _call_hook(
            loaded, "accept_house_source", source, desk, default=False
        )
        if hit:
            return True
    return False


def plugin_stale_prefixes() -> dict[str, int]:
    rt = ensure_loaded()
    out: dict[str, int] = {}
    for loaded in rt.plugins:
        mapping = _call_hook(loaded, "stale_prefixes", default={}) or {}
        if not isinstance(mapping, Mapping):
            continue
        for key, value in mapping.items():
            try:
                out[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    return out


def plugin_stale_pins() -> list[Any]:
    rt = ensure_loaded()
    out: list[Any] = []
    for loaded in rt.plugins:
        found = _call_hook(loaded, "stale_pins", default=[]) or []
        out.extend(list(found))
    return out


def plugin_advertise_lane() -> str:
    rt = ensure_loaded()
    for loaded in rt.plugins:
        text = _call_hook(loaded, "advertise_lane", default="") or ""
        if text:
            return str(text)
    return ""


class _CollectingRegistry:
    """Proxy that records ``ToolSpec.name`` values as they register."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.names: list[str] = []

    def register(self, spec: Any) -> Any:
        name = getattr(spec, "name", None)
        if name:
            self.names.append(str(name))
        return self._inner.register(spec)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)
