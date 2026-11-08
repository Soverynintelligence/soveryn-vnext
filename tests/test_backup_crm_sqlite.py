"""CRM step of scripts/backup_soveryn.sh — WAL-safe snapshot, isolated.

Invokes the production script with --crm-sqlite-only (never the full nightly
job). PATH stubs stand in for curl/ssh; no secrets, no Spark, no :8100.
"""

from __future__ import annotations

import os
import sqlite3
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "backup_soveryn.sh"
DEST_NAME = "pondwright-crm-ops.sqlite"
OLD_TS = "2026-09-30T03:06Z"
NEW_TS = "2026-11-05T15:58Z"


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _seed_wal_db(path: Path, *, wal_only: bool = True) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE leads (id INTEGER PRIMARY KEY, created_at TEXT, note TEXT)"
    )
    conn.execute(
        "INSERT INTO leads(created_at, note) VALUES(?, ?)", (OLD_TS, "checkpointed")
    )
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if wal_only:
        conn.execute(
            "INSERT INTO leads(created_at, note) VALUES(?, ?)", (NEW_TS, "wal-only")
        )
        conn.commit()
    return conn


def _query(db: Path, sql: str) -> str:
    """Default CLI open — applies -wal/-shm if present (use only on a probe copy)."""
    p = subprocess.run(
        ["sqlite3", "-batch", str(db), sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return p.stdout.strip()


def _query_snap(db: Path, sql: str) -> str:
    """Immutable read of a completed snapshot; does not create dest sidecars."""
    uri = f"file:{db.resolve()}?mode=ro&immutable=1"
    p = subprocess.run(
        ["sqlite3", "-batch", uri, sql],
        check=True,
        capture_output=True,
        text=True,
    )
    return p.stdout.strip()


def _remote_tmps() -> set[Path]:
    return set(Path("/tmp").glob("pondwright-crm-ops.*"))


def _install_stubs(bin_dir: Path, spark_home: Path) -> None:
    _write_exec(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${FAIL_CURL:-}" = 1 ]; then exit 1; fi
exit 0
""",
    )
    _write_exec(
        bin_dir / "ssh",
        f"""#!/usr/bin/env bash
set -euo pipefail
log="${{SSH_LOG:-}}"
[ -n "$log" ] && echo "ssh $*" >> "$log"
while [ $# -gt 0 ]; do
  case "$1" in
    -o) shift 2 ;;
    -o*) shift ;;
    -*) shift ;;
    *) break ;;
  esac
done
if [ "${{FAIL_SSH:-}}" = 1 ]; then exit 1; fi
if [ "${{SSH_GARBAGE:-}}" = 1 ]; then printf 'this is not a sqlite database\\n'; exit 0; fi
host="$1"; shift
export HOME={spark_home.as_posix()!r}
exec "$@"
""",
    )


@pytest.fixture
def crm_env(tmp_path: Path):
    spark_home = tmp_path / "spark-home"
    dest_dir = tmp_path / "mirror"
    dest_dir.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _install_stubs(bin_dir, spark_home)
    live = spark_home / "pondwright-cwg-ops" / "data" / "ops.sqlite"
    writer = _seed_wal_db(live)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_SPARK_HOME"] = str(spark_home)
    env["SSH_LOG"] = str(tmp_path / "ssh.log")
    env.pop("FAIL_CURL", None)
    env.pop("FAIL_SSH", None)
    env.pop("SSH_GARBAGE", None)
    yield {
        "env": env,
        "dest_dir": dest_dir,
        "live": live,
        "writer": writer,
        "spark_home": spark_home,
        "ssh_log": Path(env["SSH_LOG"]),
        "tmp_path": tmp_path,
    }
    writer.close()


def _run(dest_dir: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--crm-sqlite-only", str(dest_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_script_bash_n():
    p = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_production_block_uses_readonly_backup_not_cat():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("backup_pondwright_crm_ops()")
    end = text.index('if [ "${1:-}" = "--crm-sqlite-only" ]')
    crm = text[start:end]
    assert "sqlite3 -batch -readonly" in crm
    assert ".backup" in crm
    assert "mode=ro&immutable=1" in crm
    assert "mktemp -p" in crm
    assert "mktemp /tmp/pondwright-crm-ops.XXXXXX" in crm
    assert "cat ~/pondwright-cwg-ops/data/ops.sqlite" not in text
    assert "alert_signal" not in crm
    assert "pondwright-crm-ops.sqlite.part" not in text


def test_crm_only_does_not_start_full_nightly(crm_env):
    backups_before = (
        {p.name for p in (REPO / "backups").iterdir()}
        if (REPO / "backups").exists()
        else set()
    )
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0, result.stderr
    assert "starting backup of" not in result.stdout
    backups_after = (
        {p.name for p in (REPO / "backups").iterdir()}
        if (REPO / "backups").exists()
        else set()
    )
    assert backups_after == backups_before


def test_wal_recent_row_captured_and_cat_would_miss(crm_env):
    live = crm_env["live"]
    before_main = live.stat()
    wal = Path(str(live) + "-wal")
    before_wal = wal.stat() if wal.exists() else None

    raw_dir = crm_env["tmp_path"] / "raw-cat"
    raw_dir.mkdir()
    raw = raw_dir / "ops.sqlite"
    raw.write_bytes(live.read_bytes())
    assert _query_snap(raw, "SELECT count(*), max(created_at) FROM leads;") == f"1|{OLD_TS}"

    before_tmps = _remote_tmps()
    result = _run(crm_env["dest_dir"], crm_env["env"])
    dest = crm_env["dest_dir"] / DEST_NAME
    assert result.returncode == 0, result.stderr + result.stdout
    assert "✓ docs-ops/pondwright-crm-ops.sqlite" in result.stdout
    assert dest.is_file()
    assert _query_snap(dest, "SELECT count(*), max(created_at) FROM leads;") == f"2|{NEW_TS}"
    assert _query_snap(dest, "PRAGMA integrity_check;") == "ok"
    assert not (crm_env["dest_dir"] / f"{DEST_NAME}-wal").exists()
    assert not (crm_env["dest_dir"] / f"{DEST_NAME}-shm").exists()
    leftover = {p for p in _remote_tmps() if p not in before_tmps}
    assert leftover == set()
    assert live.stat().st_size == before_main.st_size
    assert live.stat().st_mtime_ns == before_main.st_mtime_ns
    if before_wal is not None:
        assert wal.exists()
        assert wal.stat().st_size == before_wal.st_size
        assert wal.stat().st_mtime_ns == before_wal.st_mtime_ns
    scratch = list(crm_env["dest_dir"].glob(".pondwright-crm-ops.*"))
    assert scratch == []


def test_ssh_failure_preserves_prior_mirror(crm_env):
    dest = crm_env["dest_dir"] / DEST_NAME
    dest.write_bytes(b"LAST-GOOD-SNAPSHOT")
    unrelated = crm_env["dest_dir"] / "keep-me.txt"
    unrelated.write_text("tax books")
    crm_env["env"]["FAIL_SSH"] = "1"
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0
    assert "non-fatal, flagged" in result.stdout
    assert dest.read_bytes() == b"LAST-GOOD-SNAPSHOT"
    assert unrelated.read_text() == "tax books"
    scratch = list(crm_env["dest_dir"].glob(".pondwright-crm-ops.*"))
    assert scratch == []


def test_integrity_failure_preserves_prior_mirror(crm_env):
    dest = crm_env["dest_dir"] / DEST_NAME
    dest.write_bytes(b"LAST-GOOD-SNAPSHOT")
    crm_env["env"]["SSH_GARBAGE"] = "1"
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0
    assert "non-fatal, flagged" in result.stdout
    assert dest.read_bytes() == b"LAST-GOOD-SNAPSHOT"


def test_backup_failure_cleans_remote_tmp_and_preserves_dest(crm_env):
    dest = crm_env["dest_dir"] / DEST_NAME
    dest.write_bytes(b"LAST-GOOD-SNAPSHOT")
    crm_env["writer"].close()
    crm_env["live"].write_bytes(b"not-a-database")
    wal = Path(str(crm_env["live"]) + "-wal")
    shm = Path(str(crm_env["live"]) + "-shm")
    if wal.exists():
        wal.unlink()
    if shm.exists():
        shm.unlink()
    before_tmps = _remote_tmps()
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0
    assert "non-fatal, flagged" in result.stdout
    assert dest.read_bytes() == b"LAST-GOOD-SNAPSHOT"
    leftover = {p for p in _remote_tmps() if p not in before_tmps}
    assert leftover == set()


def test_stale_dest_wal_not_applied_after_replace(crm_env):
    dest_dir = crm_env["dest_dir"]
    dest = dest_dir / DEST_NAME
    unrelated = dest_dir / "notes.txt"
    bak = dest_dir / f"{DEST_NAME}.bak"
    unrelated.write_text("leave me")
    bak.write_text("not a journal")

    stale = dest_dir / "stale-src.sqlite"
    stale_conn = sqlite3.connect(str(stale))
    stale_conn.execute("PRAGMA journal_mode=WAL")
    stale_conn.execute(
        "CREATE TABLE leads (id INTEGER PRIMARY KEY, created_at TEXT, note TEXT)"
    )
    stale_conn.execute(
        "INSERT INTO leads(created_at, note) VALUES('stale-main','from-main')"
    )
    stale_conn.commit()
    stale_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    stale_conn.execute(
        "INSERT INTO leads(created_at, note) VALUES('stale-wal','from-wal')"
    )
    stale_conn.commit()
    dest.write_bytes(stale.read_bytes())
    Path(str(dest) + "-wal").write_bytes(Path(str(stale) + "-wal").read_bytes())
    Path(str(dest) + "-shm").write_bytes(Path(str(stale) + "-shm").read_bytes())
    stale_conn.close()
    # Probe copy: opening dest itself would checkpoint/delete the journals
    # we need the production install to uncouple.
    probe = dest_dir / "probe.sqlite"
    probe.write_bytes(dest.read_bytes())
    Path(str(probe) + "-wal").write_bytes(Path(str(dest) + "-wal").read_bytes())
    Path(str(probe) + "-shm").write_bytes(Path(str(dest) + "-shm").read_bytes())
    assert "from-wal" in _query(probe, "SELECT group_concat(note) FROM leads;")

    result = _run(dest_dir, crm_env["env"])
    assert result.returncode == 0, result.stdout
    assert "✓" in result.stdout
    notes = _query_snap(dest, "SELECT group_concat(note) FROM leads;")
    assert notes == "checkpointed,wal-only"
    assert _query_snap(dest, "SELECT count(*), max(created_at) FROM leads;") == f"2|{NEW_TS}"
    assert not Path(str(dest) + "-wal").exists()
    assert not Path(str(dest) + "-shm").exists()
    assert unrelated.read_text() == "leave me"
    assert bak.read_text() == "not a journal"


def test_empty_leftover_sidecars_uncoupled(crm_env):
    dest = crm_env["dest_dir"] / DEST_NAME
    old = crm_env["tmp_path"] / "old-only.sqlite"
    old_conn = _seed_wal_db(old, wal_only=False)
    old_conn.close()
    subprocess.run(
        ["sqlite3", "-batch", "-readonly", str(old), f".backup '{dest}'"],
        check=True,
        capture_output=True,
        text=True,
    )
    Path(str(dest) + "-wal").write_bytes(b"")
    Path(str(dest) + "-shm").write_bytes(b"\x00" * 32768)
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0
    assert _query_snap(dest, "SELECT count(*), max(created_at) FROM leads;") == f"2|{NEW_TS}"
    assert not Path(str(dest) + "-wal").exists()
    assert not Path(str(dest) + "-shm").exists()


def test_health_skip_does_not_ssh_or_touch_dest(crm_env):
    dest = crm_env["dest_dir"] / DEST_NAME
    dest.write_bytes(b"LAST-GOOD-SNAPSHOT")
    crm_env["env"]["FAIL_CURL"] = "1"
    result = _run(crm_env["dest_dir"], crm_env["env"])
    assert result.returncode == 0
    assert result.stdout == ""
    assert dest.read_bytes() == b"LAST-GOOD-SNAPSHOT"
    assert not crm_env["ssh_log"].exists()


def test_usage_without_dest_dir():
    p = subprocess.run(
        ["bash", str(SCRIPT), "--crm-sqlite-only"],
        capture_output=True,
        text=True,
    )
    assert p.returncode == 2
    assert "usage:" in p.stderr
