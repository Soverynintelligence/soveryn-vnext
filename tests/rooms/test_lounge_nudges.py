"""Lounge nudge guards: a receipt wall stays quiet, and a missing citizen is a no-op."""
from __future__ import annotations

import json

from soveryn.citizens.registry import Citizen, connect, register
from soveryn.rooms.lounge import notify_lounge


def _citizens(tmp_path, monkeypatch, ids):
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        for cid in ids:
            register(conn, Citizen(id=cid, display_name=cid.title()))
    monkeypatch.setenv("SOVERYN_CITIZENS_DB", str(db))
    return db


def _lounge(tmp_path, events):
    rooms = tmp_path / "rooms"
    rooms.mkdir()
    sid = "lounge-nudges"
    (rooms / "lounge.json").write_text(json.dumps({"session_id": sid}))
    (rooms / f"{sid}.json").write_text(json.dumps({
        "session_id": sid,
        "created_at": "2026-09-30T11:00:00Z",
        "events": events,
    }))


def _commission_ids(db):
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT citizen_id FROM commissions ORDER BY citizen_id"
        ).fetchall()
    return [row["citizen_id"] for row in rows]


def test_receipt_wall_does_not_nudge(tmp_path, monkeypatch):
    """Commission receipts are not chat. Nobody gets a nudge, and nothing is queued."""
    db = _citizens(tmp_path, monkeypatch, ("aetheria", "eve", "forge"))
    _lounge(tmp_path, [
        {
            "at": "2026-09-30T11:00:00Z", "type": "peer_reply", "peer": "eve",
            "brief": "Commission abc — done. Nothing owed.",
            "commission_id": "abc",
        },
        {
            "at": "2026-09-30T11:01:00Z", "type": "wall_note", "from": "forge",
            "text": "Closed. Out.", "commission_id": "abc",
        },
        {"at": "2026-09-30T11:02:00Z", "type": "commission_state", "state": "done"},
    ])

    assert notify_lounge(tmp_path, actor="jon") == {}
    assert _commission_ids(db) == []


def test_chat_wall_nudges_registered_parties_only(tmp_path, monkeypatch):
    """Real notes reach registered citizens. forge has no row, and the actor is skipped."""
    db = _citizens(tmp_path, monkeypatch, ("aetheria", "eve"))
    _lounge(tmp_path, [
        {
            "at": "2026-09-30T11:10:00Z", "type": "wall_note", "from": "jon",
            "text": "anyone around?",
        },
        {
            "at": "2026-09-30T11:11:00Z", "type": "wall_note", "from": "aetheria",
            "text": "here.",
        },
    ])

    nudged = notify_lounge(tmp_path, actor="eve")

    assert set(nudged) == {"aetheria"}
    assert nudged["aetheria"] == 1
    assert "forge" not in nudged
    assert "eve" not in nudged
    assert _commission_ids(db) == ["aetheria"]


def test_temp_lounge_does_not_enqueue_into_the_house_db(tmp_path, monkeypatch):
    """A wall outside the house data root keeps its queue next to itself."""
    monkeypatch.delenv("SOVERYN_CITIZENS_DB", raising=False)
    house = tmp_path / "house"
    house.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: house)
    from soveryn.citizens.registry import Citizen, connect, register

    with connect(tmp_path / "citizens.db") as conn:
        for cid in ("aetheria", "eve"):
            register(conn, Citizen(id=cid, display_name=cid.title()))
    _lounge(tmp_path, [
        {
            "at": "2026-09-30T11:10:00Z", "type": "wall_note", "from": "jon",
            "text": "anyone around?",
        },
    ])

    nudged = notify_lounge(tmp_path, actor="jon")

    assert set(nudged) == {"aetheria", "eve"}
    assert _commission_ids(tmp_path / "citizens.db") == ["aetheria", "eve"]
    assert not (house / "soveryn_vnext" / "data" / "citizens.db").exists()


def _already_told(tmp_path, monkeypatch, unread_by_party):
    monkeypatch.setenv("LOUNGE_NUDGE_COOLDOWN_MIN", "0")
    path = tmp_path / "lounge" / "nudges.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        party: {"at": "2026-09-29T00:00:00+00:00", "unread": n}
        for party, n in unread_by_party.items()
    }))


def test_nudge_receipt_does_not_count_as_new_chat(tmp_path, monkeypatch):
    """A note posted while handling a nudge is not a new reason to nudge."""
    from soveryn.rooms.lounge import nudge_replies, post_note, unread_since

    db = _citizens(tmp_path, monkeypatch, ("aetheria", "eve"))
    _lounge(tmp_path, [
        {
            "at": "2026-09-30T11:10:00Z", "type": "wall_note", "from": "jon",
            "text": "anyone around?",
        },
    ])
    before = unread_since(tmp_path, "aetheria")
    _already_told(tmp_path, monkeypatch, {"aetheria": before, "eve": before})
    with nudge_replies():
        post_note(tmp_path, from_party="eve", text="Read. Nothing owed. Out.")
    assert unread_since(tmp_path, "aetheria") == before
    assert _commission_ids(db) == []


def test_finishing_a_lounge_nudge_does_not_queue_another_job(tmp_path, monkeypatch):
    from soveryn.citizens import commissions
    from soveryn.citizens.registry import Citizen, connect, register
    from soveryn.citizens.runtime import execute_claimed
    from soveryn.rooms.lounge import post_note, unread_since

    monkeypatch.delenv("SOVERYN_CITIZENS_DB", raising=False)
    db = tmp_path / "citizens.db"
    with connect(db) as conn:
        register(conn, Citizen(
            id="forge", display_name="Forge", workspace_path=str(tmp_path / "forge"),
        ))
        register(conn, Citizen(
            id="aetheria", display_name="Aetheria",
            workspace_path=str(tmp_path / "aetheria"),
        ))
        commissions.enqueue(
            conn,
            "forge",
            "Lounge nudge: eve is in the room — 3 unread note(s) on the wall. (auto-nudge)",
            at="2026-09-30T12:00:00Z",
        )
        claimed = commissions.claim(
            conn, "forge", worker="test", at="2026-09-30T12:00:01Z",
        )
    assert claimed is not None
    _lounge(tmp_path, [
        {
            "at": "2026-09-30T11:10:00Z", "type": "wall_note", "from": "jon",
            "text": "anyone around?",
        },
    ])
    _already_told(
        tmp_path, monkeypatch,
        {"aetheria": unread_since(tmp_path, "aetheria")},
    )

    def process(citizen_id, body, commission_id):
        post_note(tmp_path, from_party="forge", text="Read. Nothing owed. Out.")
        return "Read. Nothing owed."

    execute_claimed(
        db, claimed, process_fn=process, at="2026-09-30T12:00:02Z", data_root=tmp_path,
    )

    with connect(db) as conn:
        rows = conn.execute(
            "SELECT citizen_id, state, body FROM commissions ORDER BY created_at"
        ).fetchall()
    assert [(r["citizen_id"], r["state"]) for r in rows] == [("forge", "done")]
    assert "[COS_RELAY]" not in rows[0]["body"]
    room = json.loads((tmp_path / "rooms" / "lounge-nudges.json").read_text())
    assert room["events"][-1]["nudge_reply"] is True
