"""Local imports of botdirectory charters — review only, never scheduled."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.platform.botdirectory.client import BotSummary

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")


@dataclass(frozen=True)
class ImportedCharter:
    slug: str
    name: str
    category: str
    integrations: tuple[str, ...]
    contributor: str
    detail_url: str
    source_url: str | None
    imported_at: str
    prompt: str
    path: str
    scheduled: bool = False  # always False — house rule

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["integrations"] = list(self.integrations)
        return d


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def imports_dir(data_root: Path | None = None) -> Path:
    root = Path(data_root) if data_root is not None else _data_root()
    return root / "botdirectory" / "imports"


def _safe_slug(slug: str) -> str:
    s = (slug or "").strip().lower()
    if not _SLUG_OK.match(s):
        raise ValueError(f"invalid slug {slug!r}")
    return s


def import_charter(
    bot: BotSummary,
    *,
    data_root: Path | None = None,
    note: str | None = None,
) -> ImportedCharter:
    """Persist a charter to disk for review. Never schedules or enables a job."""
    slug = _safe_slug(bot.slug)
    dest = imports_dir(data_root)
    dest.mkdir(parents=True, exist_ok=True)
    imported_at = datetime.now().isoformat(timespec="seconds")
    meta = {
        "slug": slug,
        "name": bot.name,
        "category": bot.category,
        "integrations": list(bot.integrations),
        "contributor": bot.contributor,
        "detail_url": bot.detail_url,
        "source_url": bot.source_url,
        "added_at": bot.added_at,
        "imported_at": imported_at,
        "scheduled": False,
        "live": False,
        "note": (note or "").strip() or None,
        "house_rule": (
            "Imported for review only. Not an Automations catalog entry. "
            "Not scheduled. Promote manually after Jon approves."
        ),
    }
    md_path = dest / f"{slug}.md"
    json_path = dest / f"{slug}.json"
    body = (
        f"# {bot.name}\n\n"
        f"- slug: `{slug}`\n"
        f"- category: {bot.category}\n"
        f"- integrations: {', '.join(bot.integrations) or '—'}\n"
        f"- contributor: {bot.contributor or '—'}\n"
        f"- source: {bot.detail_url}\n"
        f"- imported_at: {imported_at}\n"
        f"- **scheduled: false** (house rule — never auto-live from import)\n\n"
        f"## Charter prompt\n\n"
        f"{bot.prompt.strip()}\n"
    )
    if note and note.strip():
        body += f"\n## Import note\n\n{note.strip()}\n"
    tmp_md = md_path.with_suffix(".tmp")
    tmp_md.write_text(body, encoding="utf-8")
    tmp_md.replace(md_path)
    tmp_json = json_path.with_suffix(".tmp")
    tmp_json.write_text(json.dumps({**meta, "prompt": bot.prompt}, indent=2) + "\n", encoding="utf-8")
    tmp_json.replace(json_path)
    # Maintain a tiny index for list_imports
    _update_index(dest, meta)
    return ImportedCharter(
        slug=slug,
        name=bot.name,
        category=bot.category,
        integrations=bot.integrations,
        contributor=bot.contributor,
        detail_url=bot.detail_url,
        source_url=bot.source_url,
        imported_at=imported_at,
        prompt=bot.prompt,
        path=str(md_path),
        scheduled=False,
    )


def _update_index(dest: Path, meta: dict[str, Any]) -> None:
    index_path = dest / "index.json"
    entries: list[dict[str, Any]] = []
    if index_path.is_file():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                entries = [e for e in raw if isinstance(e, dict) and e.get("slug") != meta["slug"]]
        except (OSError, json.JSONDecodeError):
            entries = []
    slim = {k: meta[k] for k in (
        "slug", "name", "category", "integrations", "contributor",
        "detail_url", "imported_at", "scheduled", "live",
    ) if k in meta}
    entries.append(slim)
    entries.sort(key=lambda e: str(e.get("imported_at") or ""), reverse=True)
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    tmp.replace(index_path)


def list_imports(*, data_root: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    dest = imports_dir(data_root)
    index_path = dest / "index.json"
    if not index_path.is_file():
        return []
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    out = [e for e in raw if isinstance(e, dict)]
    return out[: max(1, min(int(limit), 200))]


def get_import(slug: str, *, data_root: Path | None = None) -> dict[str, Any]:
    """Load one imported charter (full prompt) from disk.

    Raises FileNotFoundError if never imported; ValueError on bad slug.
    """
    safe = _safe_slug(slug)
    dest = imports_dir(data_root)
    json_path = dest / f"{safe}.json"
    md_path = dest / f"{safe}.md"
    if json_path.is_file():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise FileNotFoundError(f"corrupt import json for {safe!r}")
        return {
            "ok": True,
            "slug": safe,
            "name": raw.get("name") or safe,
            "category": raw.get("category"),
            "integrations": raw.get("integrations") or [],
            "contributor": raw.get("contributor"),
            "detail_url": raw.get("detail_url"),
            "source_url": raw.get("source_url"),
            "imported_at": raw.get("imported_at"),
            "note": raw.get("note"),
            "scheduled": False,
            "live": False,
            "path": str(md_path if md_path.is_file() else json_path),
            "prompt": raw.get("prompt") or "",
            "house_rule": raw.get("house_rule"),
        }
    if md_path.is_file():
        text = md_path.read_text(encoding="utf-8")
        # Best-effort: split off the charter section if present.
        prompt = text
        marker = "## Charter prompt\n"
        if marker in text:
            prompt = text.split(marker, 1)[1]
            if "## Import note\n" in prompt:
                prompt = prompt.split("## Import note\n", 1)[0]
        return {
            "ok": True,
            "slug": safe,
            "name": safe,
            "scheduled": False,
            "live": False,
            "path": str(md_path),
            "prompt": prompt.strip(),
        }
    raise FileNotFoundError(
        f"no local import for {safe!r}; use import_bot_charter first"
    )
