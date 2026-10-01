"""Shared content budgets for lattice write/read paths.

Canonical location for Memory Grades caps (design 2026-08-11). Lives under
``platform/lattice`` so write_node, dream writeback, and tool render can share
one source of truth without platform importing agents.

See: docs/superpowers/specs/2026-08-11-memory-grades-self-through-memory-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal


# ── Write / storage caps (chars) ─────────────────────────────────────────────

CONTENT_CAPS: dict[str, int] = {
    "fact": 400,
    "lesson_learned": 400,
    "decision": 400,
    "conclusion": 400,
    "trigger_anchor": 200,
    "insight": 600,
    "reflection": 500,
    "identity": 600,
    "library": 800,
    "event": 800,
    "coordination": 1200,
    "x_post": 400,
    "deliberate_share": 800,
    "direct_message": 400,
    "_default": 800,
}

WRITE_HARD_CEILING = 12_000
JOURNAL_MAX_CHARS = 8_000
DREAM_SYNTHESIS_LATTICE_MAX = 600
LIBRARY_PROMOTE_MAX_CHARS = 800

# ── Tool render caps (list mode) ─────────────────────────────────────────────

CHANNEL_B_TOOL_TOP_N = 5
CHANNEL_B_BODY_MAX_CHARS = 400
CHANNEL_A_BODY_MAX_CHARS = 400
DETAIL_MODE_MAX_CHARS = 12_000

OverflowPolicy = Literal["clamp", "raise"]


class ContentOverflowError(ValueError):
    """Raised when content exceeds the type cap and on_overflow='raise'."""

    def __init__(self, node_type: str, length: int, limit: int) -> None:
        self.node_type = node_type
        self.length = length
        self.limit = limit
        super().__init__(
            f"content for type={node_type!r} is {length} chars; "
            f"limit is {limit} (set on_overflow='clamp' to truncate)"
        )


def cap_for_type(node_type: str) -> int:
    """Return the per-type content cap (chars)."""
    key = (node_type or "").strip() or "_default"
    return CONTENT_CAPS.get(key, CONTENT_CAPS["_default"])


def clamp_content(
    node_type: str,
    content: str,
    *,
    on_overflow: OverflowPolicy = "clamp",
    max_chars: int | None = None,
) -> str:
    """Clamp or reject content against the type budget.

    Shared by write_node (PR2) and bypass writers (dream raw INSERT).
    Always enforces WRITE_HARD_CEILING as a backstop after the type cap.
    """
    text = content if content is not None else ""
    limit = max_chars if max_chars is not None else cap_for_type(node_type)
    limit = min(limit, WRITE_HARD_CEILING)

    if len(text) <= limit:
        return text

    if on_overflow == "raise":
        raise ContentOverflowError(node_type or "_default", len(text), limit)

    if limit <= 1:
        return "…" if text else ""
    # Prefer a clean cut; ellipsis marks truncation for readers.
    return text[: limit - 1].rstrip() + "…"


def truncate_body(text: str, max_chars: int) -> tuple[str, bool, int]:
    """Truncate for tool list mode. Returns (body, truncated, original_chars)."""
    original = text if text is not None else ""
    n = len(original)
    if n <= max_chars:
        return original, False, n
    if max_chars <= 1:
        return "…", True, n
    return original[: max_chars - 1].rstrip() + "…", True, n


def resolve_full_text_ref(
    ref: str,
    *,
    data_root: Path | None = None,
) -> str | None:
    """Load archived full text for a provenance full_text_ref.

    Supported schemes:
      - thoughts_log:pulse_id=<uuid>   → data/heartbeat_thoughts.jsonl
      - dream_archive:<run_id>         → data/memory/dream_archive/<run_id>.md
      - journal_archive:<id>           → reserved (returns None until wired)

    Returns None if the ref is empty, unknown, or the archive is missing.
    Callers must treat None as honest miss (detail mode sets full_text_missing).
    """
    if not ref or not str(ref).strip():
        return None

    root = Path(data_root) if data_root is not None else (
        Path.home() / "soveryn_vnext" / "data"
    )
    s = str(ref).strip()

    if s.startswith("thoughts_log:pulse_id="):
        pulse_id = s[len("thoughts_log:pulse_id="):].strip()
        if not pulse_id:
            return None
        log_path = root / "heartbeat_thoughts.jsonl"
        if not log_path.is_file():
            # also accept data/ as already the vnext data root OR parent
            alt = root.parent / "data" / "heartbeat_thoughts.jsonl"
            log_path = alt if alt.is_file() else log_path
        return _read_thoughts_log_note(log_path, pulse_id)

    if s.startswith("dream_archive:"):
        run_id = s[len("dream_archive:"):].strip()
        if not run_id or "/" in run_id or ".." in run_id:
            return None
        path = root / "memory" / "dream_archive" / f"{run_id}.md"
        if not path.is_file():
            alt = root / "dream_archive" / f"{run_id}.md"
            path = alt if alt.is_file() else path
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    if s.startswith("journal_archive:"):
        return None

    return None


def _read_thoughts_log_note(log_path: Path, pulse_id: str) -> str | None:
    if not log_path.is_file():
        return None
    import json

    try:
        with log_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("pulse_id") == pulse_id:
                    note = row.get("note")
                    return note if isinstance(note, str) else None
    except OSError:
        return None
    return None


def dream_archive_path(data_root: Path, dream_run_id: str) -> Path:
    """Canonical path for a dream full-synthesis archive file."""
    return Path(data_root) / "memory" / "dream_archive" / f"{dream_run_id}.md"


def write_dream_archive(
    data_root: Path,
    dream_run_id: str,
    synthesis: str,
    *,
    associations: str = "",
    contradictions: str = "",
) -> Path:
    """Persist full dream synthesis for later resolve_full_text_ref."""
    path = dream_archive_path(data_root, dream_run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Dream archive {dream_run_id}\n\n"
        f"## Synthesis\n\n{(synthesis or '').strip()}\n"
    )
    if associations and associations.strip():
        body += f"\n## Associations\n\n{associations.strip()}\n"
    if contradictions and contradictions.strip():
        body += f"\n## Contradictions\n\n{contradictions.strip()}\n"
    path.write_text(body, encoding="utf-8")
    return path
