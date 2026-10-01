"""A resolution nobody can recall is not a resolution.

Archive and promote both wrote their nodes with `embedding = NULL`. The board
could still list them, but semantic recall could never reach them — 25 Lessons
Learned sat unreachable for exactly that reason.

That is not a cosmetic gap. The Graph-Native substrate was dispatched at least
seven times between 3 and 13 August; the blueprint stayed `status: Open` and
every rejection landed somewhere recall could not see. Archiving is the act
that is supposed to turn a closed decision into memory, and it was the one
write guaranteed not to become memory.

So these tests pin the write, not the ranking: the row must carry both
embedding formats when an embedder is present — and archiving must still
succeed when it isn't.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import CoordBoard, CoordStatus
from soveryn.platform.lattice.legacy import LatticeStore

DIM = 8


@pytest.fixture
def lattice_path(tmp_path):
    db_path = tmp_path / "test_lattice.db"
    LatticeStore(db_path)          # init schema (idempotent)
    return db_path


def _fake_embed(text: str) -> tuple[float, ...]:
    """Deterministic stand-in — no HTTP, and distinct per text."""
    return tuple(float((hash(text) >> (i * 3)) % 17) + 1.0 for i in range(DIM))


@pytest.fixture
def store(lattice_path):
    return CoordinationStore(lattice_path, embed_fn=_fake_embed)


def _row(path, node_id):
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        return con.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    finally:
        con.close()


def _open_node(store, content="Rebuild the substrate as a graph"):
    return store.create_node(
        board=CoordBoard.BLUEPRINT,
        owner="aetheria",
        content=content,
        notify=False,
    )


# ── the defect ──────────────────────────────────────────────────────────────

def test_an_archived_lesson_is_written_with_an_embedding(store, lattice_path):
    node = _open_node(store)
    archived = store.archive_node(
        node.id,
        lesson_learned_content="Declined: 701 edges would be lost to the new key.",
        acting_agent="jon",
    )
    lesson = _row(lattice_path, archived.archived_lesson_id)
    assert lesson["embedding"] is not None, (
        "the lesson was written unembedded — semantic recall cannot reach it"
    )
    assert len(json.loads(lesson["embedding"])) == DIM


def test_the_lesson_carries_the_float32_blob_too(store, lattice_path):
    """JSON alone leaves the row on the slow decode path recall moved off."""
    node = _open_node(store)
    archived = store.archive_node(
        node.id, lesson_learned_content="Declined on principle.", acting_agent="jon",
    )
    lesson = _row(lattice_path, archived.archived_lesson_id)
    assert lesson["embedding_f32"] is not None
    assert len(lesson["embedding_f32"]) == DIM * 4


def test_the_two_formats_agree(store, lattice_path):
    """If they disagree, recall's answer depends on which column it read."""
    from soveryn.platform.lattice.legacy import _decode_embedding_blob

    node = _open_node(store)
    archived = store.archive_node(
        node.id, lesson_learned_content="Superseded by the format change.",
        acting_agent="jon",
    )
    lesson = _row(lattice_path, archived.archived_lesson_id)
    text = json.loads(lesson["embedding"])
    blob = _decode_embedding_blob(lesson["embedding_f32"])
    assert blob == pytest.approx(text, abs=1e-6)


def test_promote_embeds_both_the_target_and_the_lesson(store, lattice_path):
    """Promote writes two nodes; both were NULL, and both are recalled."""
    node = _open_node(store)
    _source, promoted = store.promote_node(
        node.id,
        target_board=CoordBoard.FRICTION,
        new_content="The Forensic Shadow depends on a substrate that was declined.",
        acting_agent="aetheria",
    )
    target = _row(lattice_path, promoted.id)
    assert target["embedding"] is not None
    assert target["embedding_f32"] is not None

    source = store.get_node(node.id)
    lesson = _row(lattice_path, source.archived_lesson_id)
    assert lesson["embedding"] is not None
    assert lesson["embedding_f32"] is not None


# ── and the invariant that outranks it ──────────────────────────────────────

def test_archiving_still_works_with_no_embedder_at_all(lattice_path):
    """Tests wire no embedder, and prod's embeddings server can be down.

    A lost archive is unrecoverable; an unembedded row is not — the same
    backfill that rescued the original 25 will find it.
    """
    store = CoordinationStore(lattice_path)          # embed_fn=None
    node = _open_node(store)
    archived = store.archive_node(
        node.id, lesson_learned_content="Declined.", acting_agent="jon",
    )
    assert archived.status is CoordStatus.ARCHIVED
    assert _row(lattice_path, archived.archived_lesson_id)["embedding"] is None


def test_an_embedder_that_raises_does_not_block_the_archive(lattice_path):
    def explode(text):
        raise RuntimeError("embeddings server unreachable")

    store = CoordinationStore(lattice_path, embed_fn=explode)
    node = _open_node(store)
    archived = store.archive_node(
        node.id, lesson_learned_content="Declined.", acting_agent="jon",
    )
    assert archived.status is CoordStatus.ARCHIVED


def test_a_lesson_that_fails_to_embed_leaves_neither_column_half_written(
    lattice_path,
):
    """Half a vector is worse than none: it would score against real ones."""
    def explode(text):
        raise RuntimeError("truncated response")

    store = CoordinationStore(lattice_path, embed_fn=explode)
    node = _open_node(store)
    archived = store.archive_node(
        node.id, lesson_learned_content="Declined.", acting_agent="jon",
    )
    lesson = _row(lattice_path, archived.archived_lesson_id)
    assert lesson["embedding"] is None
    assert lesson["embedding_f32"] is None
