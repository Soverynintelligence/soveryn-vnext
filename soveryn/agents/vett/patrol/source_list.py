"""Patrol source list — YAML loader + per-source state in vett_patrol_state.

The YAML is read-only config (committed in repo). Per-source state lives
in the lattice DB so it survives restarts and tests can isolate it.

Schema (validated on load):
  - url:              required str (http/https)
  - kind:             required str, one of {"html", "rss", "atom"}
  - domain:           required str (short tag like "funding_uk")
  - visit_every_hours: required positive int
  - keywords:         optional list[str]

Bad YAML → PatrolSourceError raised at load (loud failure, daemon won't
silently start with corrupted config).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


PATROL_SOURCES_DEFAULT_PATH = (
    Path.home() / "soveryn_vnext" / "data" / "vett_patrol_sources.yaml"
)

_ALLOWED_KINDS = frozenset({"html", "rss", "atom"})


class PatrolSourceError(ValueError):
    """YAML failed schema validation."""


@dataclass(frozen=True)
class PatrolSource:
    url: str
    kind: str
    domain: str
    visit_every_hours: int
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceState:
    """Dynamic per-source state from vett_patrol_state."""
    source_url: str
    last_visited_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    visit_count: int


@dataclass(frozen=True)
class SourceList:
    """Loaded source list + the path it came from (for diagnostics)."""
    path: Path
    sources: tuple[PatrolSource, ...]

    def __iter__(self):
        return iter(self.sources)

    def __len__(self) -> int:
        return len(self.sources)

    def __bool__(self) -> bool:
        return bool(self.sources)


def load_source_list(path: Path | None = None) -> SourceList:
    """Parse + validate the patrol source YAML. Raises PatrolSourceError on
    any structural problem so the daemon refuses to start with bad config."""
    target = Path(path) if path is not None else PATROL_SOURCES_DEFAULT_PATH
    if not target.is_file():
        raise PatrolSourceError(f"source list not found at {target}")
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise PatrolSourceError(f"YAML parse failed at {target}: {e}") from e
    if raw is None:
        return SourceList(path=target, sources=())
    if not isinstance(raw, list):
        raise PatrolSourceError(
            f"top-level YAML must be a list of sources, got {type(raw).__name__}"
        )
    sources: list[PatrolSource] = []
    for i, entry in enumerate(raw):
        sources.append(_parse_entry(entry, index=i, path=target))
    # Defend against duplicate URLs — they'd break the state-table join key.
    seen: set[str] = set()
    for s in sources:
        if s.url in seen:
            raise PatrolSourceError(f"duplicate url in source list: {s.url!r}")
        seen.add(s.url)
    return SourceList(path=target, sources=tuple(sources))


def _parse_entry(entry: Any, *, index: int, path: Path) -> PatrolSource:
    if not isinstance(entry, dict):
        raise PatrolSourceError(
            f"source[{index}] in {path} must be a mapping, got {type(entry).__name__}"
        )
    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        raise PatrolSourceError(f"source[{index}].url missing or not a string")
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise PatrolSourceError(
            f"source[{index}].url must be http(s); got {url!r}"
        )
    kind = entry.get("kind")
    if kind not in _ALLOWED_KINDS:
        raise PatrolSourceError(
            f"source[{index}].kind {kind!r} not in {sorted(_ALLOWED_KINDS)}"
        )
    domain = entry.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        raise PatrolSourceError(f"source[{index}].domain missing or not a string")
    visit_every_hours = entry.get("visit_every_hours")
    if not isinstance(visit_every_hours, int) or isinstance(visit_every_hours, bool):
        raise PatrolSourceError(
            f"source[{index}].visit_every_hours must be an integer"
        )
    if visit_every_hours <= 0:
        raise PatrolSourceError(
            f"source[{index}].visit_every_hours must be > 0"
        )
    keywords_raw = entry.get("keywords", [])
    if keywords_raw is None:
        keywords_raw = []
    if not isinstance(keywords_raw, list):
        raise PatrolSourceError(
            f"source[{index}].keywords must be a list or omitted"
        )
    keywords: list[str] = []
    for j, k in enumerate(keywords_raw):
        if not isinstance(k, str):
            raise PatrolSourceError(
                f"source[{index}].keywords[{j}] must be a string"
            )
        keywords.append(k.strip())
    extras = set(entry.keys()) - {
        "url", "kind", "domain", "visit_every_hours", "keywords",
    }
    if extras:
        raise PatrolSourceError(
            f"source[{index}] has unknown fields: {sorted(extras)}"
        )
    return PatrolSource(
        url=url,
        kind=kind,
        domain=domain.strip(),
        visit_every_hours=visit_every_hours,
        keywords=tuple(keywords),
    )


# ─── Per-source state in vett_patrol_state ──────────────────────────────────

def read_patrol_state(
    db_path: Path,
    urls: Iterable[str] | None = None,
) -> dict[str, SourceState]:
    """Return {url -> SourceState} for the given urls (or all rows if None).
    Missing rows in vett_patrol_state become a SourceState with all-None
    timestamps — Vett has never visited that source.
    """
    target_urls: list[str] | None = None
    if urls is not None:
        target_urls = list(urls)
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        if target_urls is None:
            rows = con.execute(
                "SELECT source_url, last_visited_at, last_error_at, last_error, "
                "visit_count FROM vett_patrol_state"
            ).fetchall()
        else:
            if not target_urls:
                return {}
            placeholders = ",".join("?" for _ in target_urls)
            rows = con.execute(
                f"SELECT source_url, last_visited_at, last_error_at, last_error, "
                f"visit_count FROM vett_patrol_state WHERE source_url IN ({placeholders})",
                target_urls,
            ).fetchall()
    result: dict[str, SourceState] = {}
    for r in rows:
        result[r["source_url"]] = SourceState(
            source_url=r["source_url"],
            last_visited_at=_iso_or_none(r["last_visited_at"]),
            last_error_at=_iso_or_none(r["last_error_at"]),
            last_error=r["last_error"],
            visit_count=int(r["visit_count"] or 0),
        )
    # Fill missing URLs with empty state objects so the caller has a uniform map.
    if target_urls is not None:
        for url in target_urls:
            if url not in result:
                result[url] = SourceState(
                    source_url=url,
                    last_visited_at=None,
                    last_error_at=None,
                    last_error=None,
                    visit_count=0,
                )
    return result


def mark_source_visited(
    db_path: Path, url: str, *, when: datetime | None = None,
) -> None:
    """Update last_visited_at + bump visit_count. Clears last_error_at and
    last_error since a successful visit invalidates the prior error state.
    """
    ts = (when or datetime.now()).isoformat()
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO vett_patrol_state "
            "(source_url, last_visited_at, last_error_at, last_error, visit_count) "
            "VALUES (?, ?, NULL, NULL, 1) "
            "ON CONFLICT(source_url) DO UPDATE SET "
            "last_visited_at = excluded.last_visited_at, "
            "last_error_at = NULL, "
            "last_error = NULL, "
            "visit_count = visit_count + 1",
            (url, ts),
        )


def mark_source_error(
    db_path: Path, url: str, message: str, *, when: datetime | None = None,
) -> None:
    """Record an error against a source without bumping visit_count."""
    ts = (when or datetime.now()).isoformat()
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO vett_patrol_state "
            "(source_url, last_visited_at, last_error_at, last_error, visit_count) "
            "VALUES (?, NULL, ?, ?, 0) "
            "ON CONFLICT(source_url) DO UPDATE SET "
            "last_error_at = excluded.last_error_at, "
            "last_error = excluded.last_error",
            (url, ts, message[:500]),
        )


def _iso_or_none(raw: Any) -> datetime | None:
    if raw is None or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
