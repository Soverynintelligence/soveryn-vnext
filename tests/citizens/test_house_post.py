"""House Post + Chief of Staff routing."""
from __future__ import annotations

from pathlib import Path

from soveryn.citizens import commissions, post
from soveryn.citizens.census import DESK_DIRS
from soveryn.citizens.duties import seed_founding
from soveryn.citizens.registry import Citizen, connect, register
from soveryn.citizens.runtime import execute_claimed


def _seed(db: Path, work: Path) -> None:
    for cid in ("aetheria", "vett", "scotty"):
        desk = work / cid
        for d in DESK_DIRS:
            (desk / d).mkdir(parents=True, exist_ok=True)
    with connect(db) as conn:
        for cid, name in (
            ("aetheria", "Aetheria"),
            ("vett", "Vett"),
            ("scotty", "Scotty"),
        ):
            register(
                conn,
                Citizen(
                    id=cid,
                    display_name=name,
                    workspace_path=str(work / cid),
                ),
            )
        seed_founding(conn)


def test_send_writes_db_and_inbox(tmp_path: Path):
    db = tmp_path / "c.db"
    work = tmp_path / "desks"
    _seed(db, work)
    with connect(db) as conn:
        pid = post.send(
            conn,
            from_id="vett",
            to_id="aetheria",
            body="Found something in patrol.",
            at="2026-08-14T12:00:00Z",
            kind="report",
            subject="patrol",
        )
        rows = post.list_for(conn, "aetheria", box="inbox")
    assert pid
    assert len(rows) == 1
    assert rows[0]["from_id"] == "vett"
    inbox = list((work / "aetheria" / "inbox").glob("*.md"))
    assert len(inbox) == 1
    assert "Found something" in inbox[0].read_text(encoding="utf-8")


def test_route_via_cos_enqueues_and_directs(tmp_path: Path):
    db = tmp_path / "c.db"
    work = tmp_path / "desks"
    _seed(db, work)
    with connect(db) as conn:
        result = post.route_via_cos(
            conn,
            from_id="aetheria",
            assignee_id="scotty",
            body="Fix the unit that is failing.",
            at="2026-08-14T12:01:00Z",
            subject="repair",
        )
        assert result["assignee_id"] == "scotty"
        cid = result["commission_id"]
        row = commissions.get(conn, cid)
        assert row is not None
        assert row["state"] == "queued"
        assert row["citizen_id"] == "scotty"
        directives = [
            r for r in post.list_for(conn, "scotty", box="inbox") if r["kind"] == "directive"
        ]
        assert len(directives) == 1
        assert cid in directives[0]["body"]


def test_commission_done_reports_to_cos(tmp_path: Path):
    db = tmp_path / "c.db"
    work = tmp_path / "desks"
    _seed(db, work)
    with connect(db) as conn:
        cid = commissions.enqueue(
            conn, "vett", "Look up one fact.", at="2026-08-14T12:02:00Z"
        )
        claimed = commissions.claim(
            conn, "vett", worker="test", at="2026-08-14T12:02:01Z"
        )
        assert claimed is not None
        assert claimed["id"] == cid

    def process(citizen_id: str, body: str, commission_id: str) -> str:
        return "The fact is forty-two."

    execute_claimed(db, claimed, process_fn=process, at="2026-08-14T12:02:02Z")

    with connect(db) as conn:
        reports = [
            r
            for r in post.list_for(conn, "aetheria", box="inbox")
            if r["kind"] == "report"
        ]
        assert reports
        assert "forty-two" in reports[0]["body"]
        assert reports[0]["from_id"] == "vett"
