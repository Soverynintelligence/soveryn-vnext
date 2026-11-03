"""Own Pi RPC children for Desk threads and fan their events out to SSE.

One child per open thread: `~/bin/soveryn --mode rpc --session <path>` (or
`--session-id <id>` for a new thread), so the Desk runs the same wrapper,
GLM profile, extensions and tool policy as the CLI.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

from soveryn.kernel_desk import lease
from soveryn.paths import SoverynPaths

logger = logging.getLogger(__name__)

_RING = 4000


def sessions_root() -> Path:
    raw = os.environ.get("KDESK_SESSIONS_ROOT", "").strip()
    return Path(raw) if raw else SoverynPaths.root() / "config" / "soveryn-cli" / "sessions"


def desk_cwd() -> Path:
    raw = os.environ.get("KDESK_CWD", "").strip()
    # Jon 2026-11-03: the Desk's Kernel works in the repo (never commits/pushes).
    return Path(raw) if raw else SoverynPaths.root()


def soveryn_bin() -> str:
    return os.environ.get("KDESK_SOVERYN_BIN", "").strip() or str(Path.home() / "bin" / "soveryn")


def find_session_file(sid: str) -> Path | None:
    root = sessions_root()
    if not root.is_dir():
        return None
    for p in root.glob(f"*/*_{sid}.jsonl"):
        return p
    return None


def list_sessions(limit: int = 30) -> list[dict]:
    root = sessions_root()
    files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for p in files[:limit]:
        sid = lease.session_id_from_arg(str(p))
        head, preview, n = {}, "", 0
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if i == 0:
                        head = rec
                    if rec.get("type") == "message":
                        n += 1
                        m = rec.get("message") or {}
                        if not preview and m.get("role") == "user":
                            preview = _text_of(m)[:120]
        except OSError:
            continue
        out.append({"id": sid, "path": str(p), "cwd": head.get("cwd"),
                    "started": head.get("timestamp"), "messages": n,
                    "mtime": p.stat().st_mtime, "preview": preview,
                    "lease": lease.status(root, sid)})
    return out


def _text_of(msg: dict) -> str:
    c = msg.get("content")
    if isinstance(c, str):
        return c
    parts = []
    for b in c or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text") or "")
    return "".join(parts)


def read_history(sid: str, limit: int = 200) -> list[dict]:
    p = find_session_file(sid)
    if p is None:
        return []
    rows = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "message":
                continue
            m = rec.get("message") or {}
            role = m.get("role")
            if role not in ("user", "assistant", "toolResult"):
                continue
            tools = [b.get("name") for b in (m.get("content") or [])
                     if isinstance(b, dict) and b.get("type") == "toolCall"]
            text = _text_of(m)
            if role == "toolResult":
                text = text[:400]
            rows.append({"role": role, "text": text, "tools": tools,
                         "at": rec.get("timestamp")})
    return rows[-limit:]


class DeskThread:
    def __init__(self, sid: str, proc: subprocess.Popen):
        self.sid = sid
        self.proc = proc
        self.seq = 0
        self.ring: deque = deque(maxlen=_RING)
        self.subs: set[queue.Queue] = set()
        self.lock = threading.Lock()
        self.wlock = threading.Lock()
        self.ids = 0
        threading.Thread(target=self._read_stdout, daemon=True, name=f"kdesk-out-{sid}").start()
        threading.Thread(target=self._read_stderr, daemon=True, name=f"kdesk-err-{sid}").start()

    def _publish(self, rec: dict) -> None:
        with self.lock:
            self.seq += 1
            item = (self.seq, rec)
            self.ring.append(item)
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except queue.Full:
                pass

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(65536) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:  # strict LF framing (rpc.md)
                line, buf = buf.split(b"\n", 1)
                line = line.rstrip(b"\r")
                if not line:
                    continue
                try:
                    rec = json.loads(line.decode("utf-8"))
                except ValueError:
                    continue
                self._publish(rec)
        self._publish({"type": "desk_exit", "code": self.proc.wait()})

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            logger.info("kdesk[%s] %s", self.sid, raw.decode("utf-8", "replace").rstrip())

    def alive(self) -> bool:
        return self.proc.poll() is None

    def send(self, cmd: dict) -> str:
        with self.wlock:
            self.ids += 1
            cid = cmd.get("id") or f"desk-{self.ids}"
            cmd = dict(cmd, id=cid)
            assert self.proc.stdin is not None
            self.proc.stdin.write((json.dumps(cmd) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
            return cid

    def subscribe(self, since: int = 0) -> tuple[queue.Queue, list]:
        q: queue.Queue = queue.Queue(maxsize=_RING)
        with self.lock:
            backlog = [it for it in self.ring if it[0] > since]
            self.subs.add(q)
        return q, backlog

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.subs.discard(q)


class DeskManager:
    def __init__(self):
        self.threads: dict[str, DeskThread] = {}
        self.lock = threading.Lock()

    def get(self, sid: str) -> DeskThread | None:
        t = self.threads.get(sid)
        return t if t and t.alive() else None

    def open(self, sid: str | None = None) -> DeskThread:
        root = sessions_root()
        with self.lock:
            if sid and self.get(sid):
                return self.threads[sid]
            if sid:
                path = find_session_file(sid)
                if path is None:
                    raise FileNotFoundError(sid)
                args = ["--session", str(path)]
            else:
                sid = "desk-" + time.strftime("%Y%m%d-%H%M%S")
                args = ["--session-id", sid]
            token = secrets.token_hex(16)
            lease.acquire(root, sid, "desk", os.getpid(), token=token)  # raises LeaseHeld
            cwd = desk_cwd()
            cwd.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["SOVERYN_ROOT"] = str(SoverynPaths.root())
            # lets the soveryn wrapper's lease check recognise its own holder
            env["SOVERYN_LEASE_TOKEN"] = token
            try:
                proc = subprocess.Popen(
                    [soveryn_bin(), "--mode", "rpc", *args],
                    cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    start_new_session=True,
                )
            except Exception:
                lease.release(root, sid, os.getpid())
                raise
            # the child's pid owns the lease from here on; it dies -> lease stale
            lease.transfer(root, sid, os.getpid(), proc.pid)
            t = DeskThread(sid, proc)
            self.threads[sid] = t
            return t

    def release(self, sid: str, timeout: float = 15.0) -> dict:
        t = self.threads.pop(sid, None)
        if t is not None and t.alive():
            try:
                t.send({"type": "abort"})
            except Exception:
                pass
            try:
                assert t.proc.stdin is not None
                t.proc.stdin.close()  # orderly shutdown (rpc.md)
            except Exception:
                pass
            try:
                t.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                t.proc.terminate()
                t.proc.wait(timeout=5)
        root = sessions_root()
        cur = lease.read(root, sid)
        if cur and cur.get("owner") == "desk":
            lease.release(root, sid)
        path = find_session_file(sid)
        return {"released": True, "session_id": sid, "path": str(path) if path else None,
                "resume": resume_command(sid)}


def resume_command(sid: str) -> str:
    """Plain `soveryn --session <path>`; the wrapper enforces the lease."""
    path = find_session_file(sid)
    target = str(path) if path else sid
    wrapper = os.environ.get("KDESK_CLI_WRAPPER", "").strip()
    if wrapper:  # staging: point at the staging tree explicitly
        return f"SOVERYN_ROOT={SoverynPaths.root()} {wrapper} --session {target}"
    return f"soveryn --session {target}"


MANAGER = DeskManager()
