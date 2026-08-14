"""SOVERYN vNext — Lattice graph adapter (nodes only this commit).

Path-injected SQLite store mirroring production lattice.db nodes table.
Edges, dream_log, contradiction_flags deferred to later commits.

Embeddings are stored as TEXT (JSON-encoded list[float]) — same format as
production. Generation goes through soveryn.inference.llama_server_client.embed()
so vNext has exactly one embedding code path.

Layer is validated on WRITE against {private, global, library}; reads accept
anything (production has legacy 'lattice' values).
"""

from __future__ import annotations
import json
import logging
import math
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from soveryn.platform.lattice.types import Entry, Region


# Layer constants — write-side enum
LAYER_PRIVATE = "private"
LAYER_GLOBAL = "global"
LAYER_LIBRARY = "library"
LAYER_DREAM = "dream"
WRITE_LAYERS: frozenset[str] = frozenset({LAYER_PRIVATE, LAYER_GLOBAL, LAYER_LIBRARY})

# Intensity tiers (parallel to production)
INTENSITY_DEFAULT = 0.3
INTENSITY_SIGNIFICANT = 0.7
INTENSITY_CORE = 1.0

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0
DEFAULT_KEYWORD_LIMIT = 20
DEFAULT_EMBED_LIMIT = 10
DEFAULT_EMBED_THRESHOLD = 0.70


class LatticeError(Exception):
    """Validation / state errors raised by the Lattice adapter."""


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    layer: str
    agent: str
    content: str
    intensity: float
    salience: float
    access_count: int
    tags: tuple[str, ...]
    created_at: str
    updated_at: str
    embedding: tuple[float, ...] | None
    intent: str | None
    provenance: dict | None


def region_for_node(node: Node) -> Region:
    """Best-effort region mapping for legacy flat lattice rows.

    The current DB has `type` and `layer`, not the final region taxonomy. This
    mapping intentionally stays conservative until Aetheria revises regions.
    """
    node_type = node.type.lower().strip()
    if node_type in {"identity", "self", "persona", "soul"}:
        return Region.IDENTITY
    if node_type in {"procedure", "skill", "howto", "tool"}:
        return Region.PROCEDURAL
    if node_type in {"event", "conversation", "journal", "episode"}:
        return Region.EPISODIC
    if node_type in {"mood", "affect", "salience"}:
        return Region.AFFECTIVE
    if node.layer == LAYER_LIBRARY or node_type in {"fact", "concept", "library"}:
        return Region.SEMANTIC
    return Region.UNKNOWN


def entry_from_node(node: Node) -> Entry:
    """Convert a legacy lattice node into a platform evidence object."""
    metadata = {
        "legacy_type": node.type,
        "layer": node.layer,
        "agent": node.agent,
        "salience": node.salience,
        "intensity": node.intensity,
        "access_count": node.access_count,
        "tags": list(node.tags),
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }
    if node.intent is not None:
        metadata["intent"] = node.intent
    if node.provenance is not None:
        metadata["provenance"] = node.provenance
    return Entry(
        id=node.id,
        content=node.content,
        region=region_for_node(node),
        source="legacy_lattice",
        metadata=metadata,
        private=node.layer == LAYER_PRIVATE,
    )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,
    type         TEXT NOT NULL,
    layer        TEXT NOT NULL DEFAULT 'lattice',
    agent        TEXT NOT NULL,
    content      TEXT NOT NULL,
    intensity    REAL NOT NULL DEFAULT 0.3,
    salience     REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    tags         TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    embedding    TEXT DEFAULT NULL,
    intent       TEXT,
    provenance   TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_nodes_agent    ON nodes(agent);
CREATE INDEX IF NOT EXISTS idx_nodes_layer    ON nodes(layer);
CREATE INDEX IF NOT EXISTS idx_nodes_type     ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_salience ON nodes(salience DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_created  ON nodes(created_at DESC);

-- Cross-reference instrumentation for Coordination Boards (Phase-1 substrate
-- for Phase-2 weight back-computation). Logs every time an agent reads or
-- references a coord node. Source/referenced ids are TEXT (UUIDs) and do NOT
-- carry FK constraints on purpose — coord nodes get archived/cleared but
-- references should outlive the original target as historical signal.
CREATE TABLE IF NOT EXISTS coord_references (
    id                  TEXT PRIMARY KEY,
    source_node_id      TEXT NOT NULL,
    referenced_node_id  TEXT NOT NULL,
    source_agent        TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coord_refs_source     ON coord_references(source_node_id);
CREATE INDEX IF NOT EXISTS idx_coord_refs_referenced ON coord_references(referenced_node_id);
CREATE INDEX IF NOT EXISTS idx_coord_refs_agent      ON coord_references(source_agent);

-- Phase E: coord webhook event log. Every CoordEvent emitted by the
-- CoordinationStore lands here for audit. triggered_agents is filled by
-- the worker after routing decides who got the event (or 'ERROR: ...'
-- on dispatch failure).
CREATE TABLE IF NOT EXISTS coord_event_log (
    id                TEXT PRIMARY KEY,
    kind              TEXT NOT NULL,
    node_id           TEXT NOT NULL,
    actor_agent       TEXT NOT NULL,
    chain_depth       INTEGER NOT NULL DEFAULT 0,
    parent_event_id   TEXT,
    payload_json      TEXT,
    triggered_agents  TEXT,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coord_event_log_created ON coord_event_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_coord_event_log_node    ON coord_event_log(node_id);
CREATE INDEX IF NOT EXISTS idx_coord_event_log_actor   ON coord_event_log(actor_agent);

-- Heartbeat daemon audit log. Every tick — eligible or skipped, success or
-- failure, live or dry-run — writes one row. See
-- docs/superpowers/specs/2026-06-02-heartbeat.md for design rationale and
-- the design rules informed by old-SOVERYN heartbeat damage.
CREATE TABLE IF NOT EXISTS heartbeat_log (
    id                TEXT PRIMARY KEY,
    triggered_at      TEXT NOT NULL,
    completed_at      TEXT,
    eligible          INTEGER NOT NULL,           -- 0 or 1
    skip_reason       TEXT,                       -- 'backoff' | 'quiet_hours' | 'disabled' | 'interval' | NULL
    action_taken      INTEGER,                    -- 0/1; NULL if skipped or errored
    tool_call_count   INTEGER,
    response_length   INTEGER,
    error             TEXT,
    dry_run           INTEGER NOT NULL DEFAULT 0,
    -- 2026-06-15 (Coordination Blackout arc close): set 1 when the tick's
    -- response carried a [SURFACE] marker and the daemon successfully
    -- posted the content into Aetheria's primary chat thread. 0 for skipped,
    -- errored, dry-run, [NO_OP], or surface-post-failed ticks. Backfilled
    -- as 0 on pre-existing rows by the daemon's idempotent ALTER TABLE.
    surfaced_to_chat  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_heartbeat_log_triggered ON heartbeat_log(triggered_at DESC);

-- Vett patrol daemon audit log. Mirrors heartbeat_log shape. One row per
-- tick (eligible OR skipped, live OR dry-run). See
-- docs/superpowers/specs/2026-06-02-vett-patrol.md.
CREATE TABLE IF NOT EXISTS vett_patrol_log (
    id                TEXT PRIMARY KEY,
    triggered_at      TEXT NOT NULL,
    completed_at      TEXT,
    eligible          INTEGER NOT NULL,           -- 0 or 1
    skip_reason       TEXT,                       -- 'disabled' | 'interval' | 'backoff' | 'quiet_hours' | 'no_sources' | NULL
    sources_visited   INTEGER,                    -- fetched at least once during the patrol
    signals_posted    INTEGER,                    -- coord nodes created on Signal board
    response_length   INTEGER,
    error             TEXT,
    dry_run           INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_vett_patrol_log_triggered ON vett_patrol_log(triggered_at DESC);

-- Per-source state for Vett's patrol. The YAML source-list is read-only
-- config (committed in repo); this table tracks the dynamic state Vett
-- mutates as he visits sources. URL is the join key because the YAML
-- supports re-ordering / inserting without breaking identity.
CREATE TABLE IF NOT EXISTS vett_patrol_state (
    source_url        TEXT PRIMARY KEY,
    last_visited_at   TEXT,
    last_error_at     TEXT,
    last_error        TEXT,
    visit_count       INTEGER NOT NULL DEFAULT 0
);

-- Signal bridge audit log. Every inbound (accepted OR dropped), every
-- outbound attempt (successful OR retried OR failed). The bridge daemon
-- writes here on every event so a replay of the full conversation is
-- possible even if conversations_vnext.db diverges. See
-- docs/superpowers/specs/2026-06-04-signal-bridge.md.
CREATE TABLE IF NOT EXISTS signal_log (
    id                TEXT PRIMARY KEY,
    direction         TEXT NOT NULL,                  -- 'inbound' | 'outbound' | 'dropped'
    sender_e164       TEXT,                            -- who sent it (null on outbound)
    recipient_e164    TEXT,                            -- who receives it (null on inbound to bot)
    body_head         TEXT,                            -- first ~200 chars
    attachment_count  INTEGER NOT NULL DEFAULT 0,
    error             TEXT,                            -- null on success
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_log_created ON signal_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_log_direction ON signal_log(direction);

-- Lattice edges (associations between nodes). Mirrors production schema verbatim.
-- No provenance column — production table has none; writeback uses reinforced_at.
CREATE TABLE IF NOT EXISTS edges (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    relationship        TEXT NOT NULL,
    strength            REAL NOT NULL DEFAULT 0.5,
    bidirectional       INTEGER NOT NULL DEFAULT 1,
    archived            INTEGER NOT NULL DEFAULT 0,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    reinforced_at       TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_edges_archived ON edges(archived);
CREATE INDEX IF NOT EXISTS idx_edges_rel      ON edges(relationship);
CREATE INDEX IF NOT EXISTS idx_edges_source   ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target   ON edges(target_id);

-- Contradiction flags. Written by the dream daemon's Pass-2 parser; one row per
-- [node:ID] adjacency pair flagged as a potential contradiction. Mirrors
-- production schema verbatim (from 2026-06-01 legacy consolidation).
CREATE TABLE IF NOT EXISTS contradiction_flags (
    id               TEXT PRIMARY KEY,
    edge_id          TEXT NOT NULL,
    node_a_id        TEXT NOT NULL,
    node_b_id        TEXT NOT NULL,
    flagged_at       TEXT NOT NULL,
    reviewed         INTEGER NOT NULL DEFAULT 0,
    resolution       TEXT,
    confidence_delta REAL DEFAULT 0.0,
    last_monitored   TEXT
);

CREATE INDEX IF NOT EXISTS idx_contradiction_flags_node_a ON contradiction_flags(node_a_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_flags_node_b ON contradiction_flags(node_b_id);
CREATE INDEX IF NOT EXISTS idx_contradiction_flags_flagged ON contradiction_flags(flagged_at DESC);

-- Dream daemon audit log. One row per tick (eligible OR skipped, live OR dry-run).
-- Mirrors heartbeat_log / vett_patrol_log shape. dry_run=1 rows are written during
-- the bake period so the audit shape is identical to live. See
-- docs/superpowers/specs/2026-06-05-dream-daemon-design.md.
CREATE TABLE IF NOT EXISTS dream_log (
    id                      TEXT PRIMARY KEY,
    trigger                 TEXT NOT NULL,
    agent                   TEXT NOT NULL,
    nodes_read              INTEGER DEFAULT 0,
    edges_created           INTEGER DEFAULT 0,
    nodes_merged            INTEGER DEFAULT 0,
    contradictions_flagged  INTEGER DEFAULT 0,
    summary                 TEXT,
    ran_at                  TEXT NOT NULL,
    loop_health             REAL DEFAULT NULL,
    dry_run                 INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_dream_log_ran_at ON dream_log(ran_at DESC);
CREATE INDEX IF NOT EXISTS idx_dream_log_agent  ON dream_log(agent);

-- Representation daemon supersede audit log. One row per conclusion that
-- explicitly supersedes an older conclusion node. Written by writeback.py
-- write_conclusions when supersedes mapping is non-empty. Purely additive —
-- no FK constraints so archived nodes don't break the audit trail.
CREATE TABLE IF NOT EXISTS representation_log (
    id               TEXT PRIMARY KEY,
    old_id           TEXT,
    new_id           TEXT NOT NULL,
    old_content_head TEXT,
    new_content_head TEXT NOT NULL,
    driving_premises TEXT NOT NULL,   -- JSON list of premise tokens
    confidence_from  TEXT,
    confidence_to    TEXT NOT NULL,
    run_id           TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_representation_log_created ON representation_log(created_at DESC);
"""


def _row_to_node(row: sqlite3.Row) -> Node:
    tags_raw = row["tags"]
    embedding_raw = row["embedding"]
    provenance_raw = row["provenance"]
    return Node(
        id=row["id"],
        type=row["type"],
        layer=row["layer"],
        agent=row["agent"],
        content=row["content"],
        intensity=float(row["intensity"]),
        salience=float(row["salience"]),
        access_count=int(row["access_count"]),
        tags=_safe_parse_tags(tags_raw),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        embedding=_safe_parse_embedding(embedding_raw),
        intent=row["intent"],
        provenance=_safe_parse_provenance(provenance_raw),
    )


def _safe_parse_embedding(raw: str | None) -> tuple[float, ...] | None:
    """Parse JSON-encoded embedding. Returns None on missing/malformed —
    callers (e.g. find_nodes_by_embedding) treat None as 'skip this row'.
    Production data can have corrupt or truncated JSON; the adapter
    tolerates it rather than crashing recall (Jon constraint 7)."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    try:
        return tuple(float(x) for x in parsed)
    except (TypeError, ValueError):
        return None


def _safe_parse_tags(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(x) for x in parsed)


def _safe_parse_provenance(raw: str | None) -> dict | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class LatticeStore:
    """SQLite-backed Lattice. Path-injected; no module state."""

    def __init__(self, db_path: Path, timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA_SQL)
            # Idempotent column-add for dream_log.dry_run. Pre-existing legacy
            # DBs (9,608 rows migrated 2026-06-01) won't have this column yet.
            existing_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(dream_log)").fetchall()
            }
            if "dry_run" not in existing_cols:
                conn.execute(
                    "ALTER TABLE dream_log ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0"
                )
            # Idempotent column-add for heartbeat_log.surfaced_to_chat (added
            # 2026-06-15 with Aetheria-decides chat routing). Same pattern as
            # dream_log.dry_run above. The heartbeat daemon also runs this
            # migration on its own startup so the column lands whether vnext
            # or the daemon comes up first.
            hb_cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(heartbeat_log)").fetchall()
            }
            if "surfaced_to_chat" not in hb_cols:
                conn.execute(
                    "ALTER TABLE heartbeat_log "
                    "ADD COLUMN surfaced_to_chat INTEGER NOT NULL DEFAULT 0"
                )

    # ─── Public API ──────────────────────────────────────────────────────────

    def write_node(
        self,
        agent: str,
        content: str,
        *,
        node_type: str = "fact",
        layer: str = LAYER_PRIVATE,
        intensity: float = INTENSITY_DEFAULT,
        tags: tuple[str, ...] | None = None,
        embedding: tuple[float, ...] | None = None,
        intent: str | None = None,
        provenance: dict | None = None,
        on_overflow: str = "raise",
    ) -> str:
        """Write a node. Returns node id. Validates layer on write (Jon constraint 4).

        Memory Grades (2026-08-11): content is capped by node type via
        ``content_caps.clamp_content``. Default ``on_overflow='raise'`` for
        interactive/tool writers (model rewrites shorter). Daemons pass
        ``on_overflow='clamp'`` after their own distill so a long pulse cannot
        fail the tick.
        """
        if layer not in WRITE_LAYERS:
            raise LatticeError(
                f"layer={layer!r} not in {sorted(WRITE_LAYERS)}; "
                "legacy values are read-only"
            )
        if not (0.0 <= intensity <= 1.0):
            raise LatticeError(f"intensity={intensity} must be in [0.0, 1.0]")
        if on_overflow not in ("raise", "clamp"):
            raise LatticeError(
                f"on_overflow={on_overflow!r} must be 'raise' or 'clamp'"
            )

        from soveryn.platform.lattice.content_caps import (
            ContentOverflowError,
            clamp_content,
        )
        try:
            content = clamp_content(
                node_type, content if content is not None else "",
                on_overflow=on_overflow,  # type: ignore[arg-type]
            )
        except ContentOverflowError as exc:
            raise LatticeError(str(exc)) from exc

        node_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        tags_json = json.dumps(list(tags or ()))
        embedding_json = json.dumps(list(embedding)) if embedding is not None else None
        provenance_json = json.dumps(provenance) if provenance is not None else None
        # salience seeded equal to intensity at write time (read-only thereafter for now)
        salience = round(intensity, 4)

        with self._conn() as conn:
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, "
                "access_count, tags, created_at, updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
                (node_id, node_type, layer, agent, content, intensity, salience,
                 tags_json, now, now, embedding_json, intent, provenance_json),
            )
        return node_id

    def get_node(self, node_id: str) -> Node | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return _row_to_node(row) if row else None

    def iter_nodes(self, *, agent: str | None = None, include_library: bool = True) -> tuple[Node, ...]:
        """Read-only full export for migration/audit callers."""

        sql = "SELECT * FROM nodes"
        params: list[str] = []
        where: list[str] = []
        if agent is not None:
            where.append("agent = ?")
            params.append(agent)
        if not include_library:
            where.append("layer != ?")
            params.append(LAYER_LIBRARY)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at ASC, id ASC"

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return tuple(_row_to_node(row) for row in rows)

    def find_nodes_by_keywords(
        self,
        agent: str,
        query: str,
        *,
        limit: int = DEFAULT_KEYWORD_LIMIT,
        include_global: bool = True,
    ) -> tuple[Node, ...]:
        """Case-insensitive LIKE over content/tags. Ordered salience DESC, updated_at DESC.

        Returns this agent's private/legacy rows + (optionally) global rows.
        Library rows excluded (use find_nodes_by_embedding with layer_filter='library').
        """
        like = f"%{query.lower()}%"
        with self._conn() as conn:
            if include_global:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE ((agent = ? AND layer != ?) OR layer = ?) "
                    "  AND layer != ? "
                    "  AND (LOWER(content) LIKE ? OR LOWER(IFNULL(tags, '')) LIKE ?) "
                    "ORDER BY salience DESC, updated_at DESC LIMIT ?",
                    (agent, LAYER_GLOBAL, LAYER_GLOBAL, LAYER_LIBRARY, like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE agent = ? AND layer != ? AND layer != ? "
                    "  AND (LOWER(content) LIKE ? OR LOWER(IFNULL(tags, '')) LIKE ?) "
                    "ORDER BY salience DESC, updated_at DESC LIMIT ?",
                    (agent, LAYER_GLOBAL, LAYER_LIBRARY, like, like, limit),
                ).fetchall()
        return tuple(_row_to_node(r) for r in rows)

    def find_nodes_by_embedding(
        self,
        agent: str,
        embedding: tuple[float, ...],
        *,
        limit: int = DEFAULT_EMBED_LIMIT,
        threshold: float = DEFAULT_EMBED_THRESHOLD,
        layer_filter: str | None = None,
        include_historical: bool = False,
    ) -> tuple[tuple[Node, float], ...]:
        """Cosine-similarity search. Returns ((node, score), ...) ordered score DESC.

        - Rows with NULL embedding are skipped (Jon constraint 7).
        - `layer_filter=None` → this agent's private/legacy + global, library excluded.
        - `layer_filter='library'` → ONLY library rows (RAG path).
        - `layer_filter` other → that layer only.
        - `include_historical=False` (default) excludes rows tagged
          `historical_snapshot` so current-state queries don't surface
          archival content (e.g., the April 2026 chronicle chunks). Set
          to `True` to reach back into history deliberately.
        """
        # Tag-side filter: substring match on the JSON tags column is sufficient
        # because tag names are not substrings of each other in this lattice's
        # convention. NULL tags are tolerated via IFNULL.
        historical_filter = (
            "" if include_historical
            else " AND IFNULL(tags, '[]') NOT LIKE '%historical_snapshot%' "
        )
        with self._conn() as conn:
            if layer_filter is None:
                # Visibility (Jon 2026-06-17): an agent recalls its OWN nodes
                # (any layer) PLUS every OTHER agent's nodes EXCEPT their
                # private. The only exclusions are other-agents' private and
                # the dream layer (internal consolidation scratch, never for
                # conversational recall). This replaced the old
                # `(own non-global) OR (anyone's global)` filter, which hid
                # every other agent's coordination/lattice work and excluded
                # library entirely — the cause of the 2026-06-17 FCC miss.
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE embedding IS NOT NULL "
                    "  AND NOT (agent != ? AND layer = ?) "   # other agents' private: hidden
                    "  AND layer != ? "                        # dream: never recalled
                    + historical_filter +
                    "ORDER BY salience DESC LIMIT 2000",
                    (agent, LAYER_PRIVATE, LAYER_DREAM),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes "
                    "WHERE embedding IS NOT NULL AND layer = ? "
                    + historical_filter +
                    "ORDER BY salience DESC LIMIT 2000",
                    (layer_filter,),
                ).fetchall()

        scored: list[tuple[Node, float]] = []
        for r in rows:
            node = _row_to_node(r)
            if node.embedding is None:
                continue
            score = _cosine(embedding, node.embedding)
            if score >= threshold:
                scored.append((node, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return tuple(scored[:limit])


def embed_text(text: str, prompt: str = "document") -> tuple[float, ...]:
    """Convenience: encode a single string via the embeddings server.

    `prompt` selects the Librarian's asymmetric prefix: "document" (default, for
    memories/writes) or "query" (for recall queries). The old nomic server
    ignored it; the Nemotron-8B server uses it. Imports the client lazily so
    importing soveryn.memory.lattice doesn't drag in urllib at module load time.
    """
    from soveryn.inference.llama_server_client import EmbeddingRequest, embed
    resp = embed(EmbeddingRequest(input=(text,), prompt=prompt))
    if not resp.vectors:
        raise LatticeError("embed_text: server returned no vectors")
    return resp.vectors[0]

class LegacyLatticeAdapter:
    """Read-only platform adapter over the current flat LatticeStore.

    The adapter returns platform `Entry` evidence objects. It deliberately does
    not expose write methods; writes remain on the legacy store until the memory
    rewrite phase explicitly designs them.
    """

    def __init__(self, store: LatticeStore) -> None:
        self._store = store

    def fetch(
        self,
        query: str,
        *,
        agent: str,
        limit: int = DEFAULT_KEYWORD_LIMIT,
        include_global: bool = True,
    ) -> tuple[Entry, ...]:
        nodes = self._store.find_nodes_by_keywords(
            agent,
            query,
            limit=limit,
            include_global=include_global,
        )
        return tuple(entry_from_node(node) for node in nodes)


# ─── Direct Agent Communication: forensic-trail edge writer ─────────────────

logger = logging.getLogger(__name__)

_DIRECT_COMM_RELATIONS = {"execute": "direct_command", "query": "direct_query"}


def record_direct_communication_edge(
    *,
    store: "LatticeStore",
    coord_node_id: str,
    sender_agent: str,
    target_agent: str,
    session_id: str,
    mode: str,
    message_head: str = "",
) -> tuple[str, str | None]:
    """Write a forensic record of a direct communication. Returns
    (message_node_id, edge_id). edge_id is None when coord_node_id does not
    resolve to a real lattice node (the anchor edge is skipped, not fabricated).

    Two rows land:
      1. A lattice node (layer=private, type='direct_message') capturing the
         direct-message metadata — sender, target, session id, mode, message
         head. This node IS the lattice's record of the directive having
         happened; the recall system can surface "her recent directives to
         Scotty" via standard node queries.
      2. An edge from that node to the coord node it's anchored to, with
         relationship='direct_command' (execute) or 'direct_query' (query).

    Why the node-then-edge structure: the edges table has FOREIGN KEY
    constraints on source_id and target_id. A naive "session_id as source"
    write fails silently because session ids aren't lattice nodes. The
    integration verification surfaced this on 2026-06-05 — DAC-T8 saw the
    chat round-trip working but zero forensic edges in the lattice. Root
    fix: write a real node, then the edge.

    See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md.
    """
    relationship = _DIRECT_COMM_RELATIONS.get(mode)
    if relationship is None:
        raise ValueError(
            f"mode must be 'execute' or 'query', got {mode!r}"
        )
    content = (
        f"[direct_{mode}] {sender_agent} -> {target_agent}\n"
        f"session: {session_id}\n"
        f"coord: {coord_node_id}\n"
        f"head: {message_head[:200]}"
    )
    provenance = {
        "kind": "direct_message",
        "sender": sender_agent,
        "target": target_agent,
        "session_id": session_id,
        "mode": mode,
        "coord_node_id": coord_node_id,
    }
    message_node_id = store.write_node(
        agent=sender_agent,
        content=content,
        node_type="direct_message",
        layer=LAYER_PRIVATE,
        provenance=provenance,
    )
    now = datetime.now().isoformat()
    with store._conn() as conn:
        # coord_node_id is an LLM-supplied tool argument (direct_message_agent),
        # so it may not resolve to a real lattice node. Anchoring an edge to a
        # non-existent target violates the edges FOREIGN KEY and raises
        # IntegrityError — which is what silently failed every direct-comm
        # forensic write when Aetheria referenced a dangling coord id. The
        # forensic *node* above already captures the directive (with coord_node_id
        # in its provenance); when the anchor isn't a real node, skip the *edge*
        # with a clean warning rather than raising. (source_id is our own
        # just-committed node, so only the anchor can dangle.)
        anchor_exists = (
            conn.execute(
                "SELECT 1 FROM nodes WHERE id = ? LIMIT 1", (coord_node_id,)
            ).fetchone()
            is not None
        )
        if not anchor_exists:
            logger.warning(
                "direct-comm anchor edge skipped: coord_node_id %r is not a lattice "
                "node; forensic node %s persisted with the coord ref in provenance",
                coord_node_id,
                message_node_id,
            )
            return message_node_id, None
        edge_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO edges "
            "(id, source_id, target_id, relationship, strength, bidirectional, "
            "archived, reinforcement_count, reinforced_at, created_at) "
            "VALUES (?, ?, ?, ?, 0.5, 0, 0, 1, ?, ?)",
            (edge_id, message_node_id, coord_node_id, relationship, now, now),
        )
    return message_node_id, edge_id

