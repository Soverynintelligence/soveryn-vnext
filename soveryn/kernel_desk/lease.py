"""Single-writer lease for a Pi session.

Lease file: <sessions_root>/.leases/<session_id>.json
  {"session_id", "owner": "desk"|"cli", "pid", "pid_start", "acquired_at"}

A lease is live while its pid is alive *and* that pid's kernel start time
still matches (guards against pid reuse). Creation is O_CREAT|O_EXCL so two
writers racing for the same session cannot both win.

CLI use (the staging wrapper calls this before exec'ing soveryn):
  python -m soveryn.kernel_desk.lease acquire --root R --session S --owner cli --pid P
exit 0 = acquired, 3 = held by a live writer.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


class LeaseHeld(RuntimeError):
    def __init__(self, lease: dict):
        super().__init__(f"session {lease.get('session_id')} is held by "
                         f"{lease.get('owner')} pid {lease.get('pid')}")
        self.lease = lease


def session_id_from_arg(arg: str) -> str:
    """Accept a session id or a path to <ts>_<id>.jsonl."""
    name = Path(arg).name
    if name.endswith(".jsonl"):
        name = name[: -len(".jsonl")]
        if "_" in name:
            name = name.split("_", 1)[1]
    return name


def _pid_start(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # field 22 (starttime) — after the ')' that closes comm
    rest = stat.rsplit(")", 1)[1].split()
    return rest[19] if len(rest) > 19 else None


def _lease_path(root: Path, sid: str) -> Path:
    safe = "".join(c for c in sid if c.isalnum() or c in "._-")
    if not safe:
        raise ValueError("bad session id")
    return Path(root) / ".leases" / f"{safe}.json"


def read(root: Path, sid: str) -> dict | None:
    try:
        return json.loads(_lease_path(root, sid).read_text())
    except (OSError, ValueError):
        return None


def is_live(lease: dict | None) -> bool:
    if not lease:
        return False
    try:
        pid = int(lease.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    start = _pid_start(pid)
    return start is not None and start == str(lease.get("pid_start"))


def status(root: Path, sid: str) -> dict:
    lease = read(root, sid)
    live = is_live(lease)
    return {"held": live, "owner": lease.get("owner") if live else None,
            "pid": lease.get("pid") if live else None}


def acquire(root: Path, sid: str, owner: str, pid: int, token: str | None = None) -> dict:
    path = _lease_path(root, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"session_id": sid, "owner": owner, "pid": int(pid),
            "pid_start": _pid_start(int(pid)),
            "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if token:
        body["token"] = token
    for _ in range(2):
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            cur = read(root, sid)
            if is_live(cur):
                if int(cur.get("pid") or 0) == int(pid):
                    return cur
                if token and cur.get("token") and token == cur.get("token"):
                    return cur  # the holder's own child (Desk RPC process)
                raise LeaseHeld(cur)
            try:  # stale: owner gone
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w") as fh:
            json.dump(body, fh)
        return body
    raise LeaseHeld(read(root, sid) or {"session_id": sid})


def transfer(root: Path, sid: str, from_pid: int, to_pid: int) -> dict:
    """Move a lease we hold to another pid (Flask pid -> RPC child pid)."""
    cur = read(root, sid)
    if not cur or int(cur.get("pid") or 0) != int(from_pid):
        raise LeaseHeld(cur or {"session_id": sid})
    cur["pid"] = int(to_pid)
    cur["pid_start"] = _pid_start(int(to_pid))
    tmp = _lease_path(root, sid).with_suffix(".tmp")
    tmp.write_text(json.dumps(cur))
    os.replace(tmp, _lease_path(root, sid))
    return cur


def release(root: Path, sid: str, pid: int | None = None) -> bool:
    cur = read(root, sid)
    if cur is None:
        return False
    if pid is not None and int(cur.get("pid") or 0) != int(pid) and is_live(cur):
        return False
    try:
        _lease_path(root, sid).unlink()
        return True
    except FileNotFoundError:
        return False


def resolve_session_id(root: Path, arg: str) -> str:
    """Full id for a path, full id, or unique partial id (Pi accepts partials)."""
    sid = session_id_from_arg(arg)
    if "/" in arg or arg.endswith(".jsonl"):
        return sid
    matches = {session_id_from_arg(str(p)) for p in Path(root).glob(f"*/*_{sid}*.jsonl")}
    return matches.pop() if len(matches) == 1 else sid


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="kernel_desk.lease")
    ap.add_argument("action", choices=["acquire", "status", "release"])
    ap.add_argument("--root", required=True)
    ap.add_argument("--session", required=True)
    ap.add_argument("--owner", default="cli")
    ap.add_argument("--pid", type=int, default=os.getppid())
    ap.add_argument("--token", default="")
    a = ap.parse_args(argv)
    sid = resolve_session_id(Path(a.root), a.session)
    if a.action == "status":
        print(json.dumps(status(Path(a.root), sid)))
        return 0
    if a.action == "release":
        return 0 if release(Path(a.root), sid, a.pid) else 1
    try:
        acquire(Path(a.root), sid, a.owner, a.pid, token=a.token or None)
    except LeaseHeld as e:
        print(f"soveryn: {e}. Hand it to the CLI from the Desk first "
              f"(or use --fork).", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_main())
    except SystemExit:
        raise
    except Exception as exc:  # never brick the CLI on a lease-helper bug
        print(f"soveryn: lease check skipped ({exc.__class__.__name__}: {exc})", file=sys.stderr)
        raise SystemExit(0)
