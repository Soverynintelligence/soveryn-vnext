"""Ares findings surface — dedup + grouping, offline with a temp bus."""
import json
import sqlite3
from soveryn.app.routes.api_ares import read_active_findings


def _bus(tmp_path, rows):
    """rows: list of (payload_dict_or_str, created_at). Builds an ares_bus.sqlite3."""
    db = tmp_path / "ares_bus.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_type TEXT NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL)")
    for payload, created in rows:
        pj = payload if isinstance(payload, str) else json.dumps(payload)
        conn.execute(
            "INSERT INTO events (event_type, payload, actor, created_at) VALUES (?,?,?,?)",
            ("anomaly.detected", pj, "ares", created))
    conn.commit()
    conn.close()
    return str(db)


def _f(key, sev, status, ftype="network.x", ev="ev"):
    return {"id": key, "severity": sev, "status": status, "finding_type": ftype, "evidence": ev}


def test_cleared_latest_is_excluded(tmp_path):
    p = _bus(tmp_path, [
        (_f("k1", "warning", "active"), "2026-07-03T01:00:00+00:00"),
        (_f("k1", "warning", "cleared"), "2026-07-03T02:00:00+00:00"),
    ])
    out = read_active_findings(p)
    assert out["findings"] == []
    assert out["counts"]["warning"] == 0


def test_active_latest_included_counted_and_emergency_first(tmp_path):
    p = _bus(tmp_path, [
        (_f("k1", "warning", "cleared"), "2026-07-03T01:00:00+00:00"),
        (_f("k1", "warning", "active"), "2026-07-03T02:00:00+00:00"),
        (_f("k2", "emergency", "active"), "2026-07-03T03:00:00+00:00"),
    ])
    out = read_active_findings(p)
    assert {f["key"] for f in out["findings"]} == {"k1", "k2"}
    assert out["counts"] == {"emergency": 1, "critical": 0, "warning": 1}
    assert out["findings"][0]["severity"] == "emergency"    # emergency sorts first


def test_missing_db_returns_empty(tmp_path):
    out = read_active_findings(str(tmp_path / "nope.sqlite3"))
    assert out["findings"] == [] and out["counts"] == {"emergency": 0, "critical": 0, "warning": 0}


def test_malformed_and_unknown_severity_rows_skipped(tmp_path):
    p = _bus(tmp_path, [
        ("not-a-json-object", "2026-07-03T01:00:00+00:00"),                    # non-dict payload
        (_f("k3", "bogus", "active"), "2026-07-03T02:00:00+00:00"),            # unknown severity
        (_f("k4", "critical", "active"), "2026-07-03T03:00:00+00:00"),         # good
    ])
    out = read_active_findings(p)
    assert [f["key"] for f in out["findings"]] == ["k4"]
    assert out["counts"]["critical"] == 1
