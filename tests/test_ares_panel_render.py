"""The command_center template renders an Ares panel inside the twin row,
and /api/ares/findings is reachable through the app."""
import json
import sqlite3


def _seed_bus(tmp_path):
    db = tmp_path / "ares_bus.sqlite3"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT, payload TEXT, actor TEXT, created_at TEXT)")
    conn.execute("INSERT INTO events (event_type,payload,actor,created_at) VALUES (?,?,?,?)",
                 ("anomaly.detected", json.dumps({"id": "k1", "severity": "emergency", "status": "active",
                  "finding_type": "network.public_listener_unallowlisted", "evidence": {"port": 5055}}),
                  "ares", "2026-07-03T03:00:00+00:00"))
    conn.commit(); conn.close()
    return str(db)


def test_command_center_has_ares_panel(app_state):
    # `app_state` is the existing app-test fixture used by tests/test_app_ui_routes.py
    html = app_state.get("/command-center").get_data(as_text=True)

    assert 'ares-panel' in html
    assert 'data-ares-feed' in html
    assert 'pulse-row' in html          # heartbeat + ares wrapped in the twin row


def test_api_ares_findings_endpoint(app_state, tmp_path):
    app_state.application.config["ARES_BUS_PATH"] = _seed_bus(tmp_path)
    resp = app_state.get("/api/ares/findings")
    assert resp.status_code == 200
    data = resp.get_json()
    assert set(data.keys()) >= {"findings", "counts", "generated_at"}
    assert data["counts"]["emergency"] == 1
    assert data["findings"][0]["finding_type"] == "network.public_listener_unallowlisted"
