"""Kernel desk: single-writer lease + operator-local/CSRF guard (cc-redesign)."""
import os
import subprocess
import sys

import pytest

from soveryn.kernel_desk import lease


def test_lease_blocks_second_writer_and_frees_on_exit(tmp_path):
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lease.acquire(tmp_path, "t1", "desk", holder.pid)
        with pytest.raises(lease.LeaseHeld):
            lease.acquire(tmp_path, "t1", "cli", os.getpid())
        assert lease.status(tmp_path, "t1")["owner"] == "desk"
    finally:
        holder.kill(); holder.wait()
    # holder gone -> lease is stale -> next writer wins
    lease.acquire(tmp_path, "t1", "cli", os.getpid())
    assert lease.status(tmp_path, "t1")["owner"] == "cli"


def test_session_id_from_path():
    assert lease.session_id_from_arg("/x/2026-11-03T15-23-00-427Z_desk-1.jsonl") == "desk-1"
    assert lease.session_id_from_arg("desk-1") == "desk-1"


def test_cli_lease_helper_exit_codes(tmp_path):
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lease.acquire(tmp_path, "t2", "desk", holder.pid)
        r = subprocess.run([sys.executable, "-m", "soveryn.kernel_desk.lease", "acquire",
                            "--root", str(tmp_path), "--session", "t2", "--pid", str(os.getpid())],
                           capture_output=True, text=True)
        assert r.returncode == 3 and "held by desk" in r.stderr
    finally:
        holder.kill(); holder.wait()


def test_kernel_routes_refuse_public_edge_and_missing_csrf(app_state):
    assert app_state.get("/api/kernel/threads", headers={"X-Soveryn-Edge": "public"}).status_code == 403
    assert app_state.post("/api/kernel/threads").status_code == 403
    tok = app_state.get("/api/kernel/csrf").get_json()["token"]
    r = app_state.post("/api/kernel/threads", headers={"X-Kernel-CSRF": tok, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_holder_token_lets_desk_child_through(tmp_path):
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lease.acquire(tmp_path, "t3", "desk", holder.pid, token="abc")
        # the Desk's own RPC child presents the token -> allowed, lease unchanged
        assert lease.acquire(tmp_path, "t3", "cli", os.getpid(), token="abc")["owner"] == "desk"
        with pytest.raises(lease.LeaseHeld):
            lease.acquire(tmp_path, "t3", "cli", os.getpid(), token="wrong")
    finally:
        holder.kill(); holder.wait()


def test_partial_id_resolves(tmp_path):
    d = tmp_path / "--x--"; d.mkdir()
    (d / "2026-11-03T00-00-00-000Z_01a19d68-41d9-70e1.jsonl").write_text("{}\n")
    assert lease.resolve_session_id(tmp_path, "01a19d68") == "01a19d68-41d9-70e1"
