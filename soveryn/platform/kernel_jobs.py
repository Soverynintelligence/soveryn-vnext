"""Live Kernel Aider/OpenCode children — list, steer, stop, keep the partial.

Hermes ``delegate_task`` list/steer/stop, house-shaped: kids are
``soveryn-aider`` / ``soveryn-opencode`` process groups. Stop keeps the
working tree. Steer stops then respawns with the correction. Aetheria can
stop a runaway while Kernel's turn is still blocked on communicate().
"""
from __future__ import annotations

import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

MAX_OUTPUT_CHARS = 8000
MAX_STEER_CHARS = 4000
TERMINAL_KEEP_S = 3600
MAX_JOBS = 40

PopenFn = Callable[..., Any]
KillpgFn = Callable[[int, int], None]
GetpgidFn = Callable[[int], int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ChildJob:
    id: str
    kind: str
    prompt: str
    repo: str
    cmd: list[str]
    started_at: str
    status: str = "running"
    pid: int | None = None
    pgid: int | None = None
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    steer_log: list[str] = field(default_factory=list)
    finished_at: str | None = None
    follow_of: str | None = None


class KernelJobStore:
    def __init__(
        self,
        *,
        popen_fn: PopenFn | None = None,
        killpg_fn: KillpgFn | None = None,
        getpgid_fn: GetpgidFn | None = None,
    ) -> None:
        import subprocess

        self._popen = popen_fn or subprocess.Popen
        self._killpg = killpg_fn or os.killpg
        self._getpgid = getpgid_fn or os.getpgid
        self._lock = threading.Lock()
        self._jobs: dict[str, ChildJob] = {}
        self._procs: dict[str, Any] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop: set[str] = set()

    def snapshot(self, job: ChildJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "kind": job.kind,
            "prompt": job.prompt[:240],
            "repo": job.repo,
            "status": job.status,
            "pid": job.pid,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "exit_code": job.exit_code,
            "error": job.error,
            "output": job.output[-MAX_OUTPUT_CHARS:],
            "steer_log": list(job.steer_log),
            "follow_of": job.follow_of,
        }

    def spawn(
        self,
        *,
        kind: str,
        prompt: str,
        repo: str,
        cmd: list[str],
        cwd: str,
        env: dict[str, str],
        timeout_s: int,
        follow_of: str | None = None,
    ) -> ChildJob:
        self._gc()
        job = ChildJob(
            id=str(uuid.uuid4()),
            kind=kind,
            prompt=prompt,
            repo=repo,
            cmd=cmd,
            started_at=_utc_now(),
            follow_of=follow_of,
        )
        import subprocess

        proc = self._popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
            env=env,
            start_new_session=True,
            text=True,
        )
        job.pid = int(getattr(proc, "pid", 0) or 0) or None
        try:
            job.pgid = self._getpgid(int(proc.pid))
        except OSError:
            job.pgid = job.pid
        with self._lock:
            self._jobs[job.id] = job
            self._procs[job.id] = proc
        t = threading.Thread(
            target=self._wait, args=(job.id, timeout_s), daemon=True, name=f"kjob-{job.id[:8]}"
        )
        with self._lock:
            self._threads[job.id] = t
        t.start()
        return job

    def wait(self, job_id: str, *, timeout: float | None = None) -> dict[str, Any]:
        t = self._threads.get(job_id)
        if t is not None:
            t.join(timeout)
        job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "error": "unknown job"}
        snap = self.snapshot(job)
        snap["ok"] = job.status == "succeeded"
        return snap

    def list_jobs(self, *, running_only: bool = False) -> list[dict[str, Any]]:
        self._gc()
        with self._lock:
            jobs = list(self._jobs.values())
        if running_only:
            jobs = [j for j in jobs if j.status == "running"]
        jobs.sort(key=lambda j: j.started_at, reverse=True)
        return [self.snapshot(j) for j in jobs]

    def stop(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "error": "unknown job", "id": job_id}
        if job.status != "running":
            snap = self.snapshot(job)
            snap["ok"] = True
            snap["already"] = True
            return snap
        with self._lock:
            self._stop.add(job_id)
        pgid = job.pgid
        if pgid:
            try:
                self._killpg(pgid, signal.SIGTERM)
            except OSError:
                pass
        t = self._threads.get(job_id)
        if t is not None:
            t.join(8)
        if job.status == "running" and pgid:
            try:
                self._killpg(pgid, signal.SIGKILL)
            except OSError:
                pass
            if t is not None:
                t.join(3)
        if job.status == "running":
            job.status = "stopped"
            job.finished_at = _utc_now()
            job.error = job.error or "stopped"
        snap = self.snapshot(job)
        snap["ok"] = True
        snap["partial"] = True
        return snap

    def steer(
        self,
        job_id: str,
        message: str,
        *,
        spawn_fn: Callable[..., ChildJob],
    ) -> dict[str, Any]:
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "steer message is empty"}
        if len(text) > MAX_STEER_CHARS:
            return {"ok": False, "error": f"steer exceeds {MAX_STEER_CHARS} characters"}
        job = self._jobs.get(job_id)
        if job is None:
            return {"ok": False, "error": "unknown job", "id": job_id}
        stopped = self.stop(job_id) if job.status == "running" else self.snapshot(job)
        job.steer_log.append(text)
        follow_prompt = (
            f"{job.prompt.rstrip()}\n\n"
            "---\n"
            "Previous run was interrupted or finished with partial edits. "
            "Keep whatever is already on disk. Do not revert. Also:\n"
            f"{text}\n"
        )
        follow = spawn_fn(
            kind=job.kind,
            prompt=follow_prompt,
            repo=job.repo,
            follow_of=job.id,
        )
        return {
            "ok": True,
            "stopped": stopped,
            "follow_up": self.snapshot(follow),
        }

    def _wait(self, job_id: str, timeout_s: int) -> None:
        proc = self._procs.get(job_id)
        job = self._jobs.get(job_id)
        if proc is None or job is None:
            return
        out = ""
        try:
            blob, _ = proc.communicate(timeout=timeout_s)
            out = blob or ""
        except Exception as exc:
            timed_out = type(exc).__name__ == "TimeoutExpired"
            if timed_out and job.pgid:
                try:
                    self._killpg(job.pgid, signal.SIGTERM)
                except OSError:
                    pass
                try:
                    blob, _ = proc.communicate(timeout=8)
                    out = blob or ""
                except Exception:
                    out = ""
                job.error = f"timed out after {timeout_s}s"
            else:
                job.error = f"{type(exc).__name__}: {exc}"
            try:
                out = getattr(exc, "stdout", None) or out
            except Exception:
                pass
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        job.output = (out or "")[-MAX_OUTPUT_CHARS:]
        job.exit_code = getattr(proc, "returncode", None)
        job.finished_at = _utc_now()
        if job_id in self._stop or job.status == "stopped":
            job.status = "stopped"
            if not job.error:
                job.error = "stopped"
        elif job.error and "timed out" in job.error:
            job.status = "failed"
        elif job.exit_code == 0:
            job.status = "succeeded"
        else:
            job.status = "failed"
            if not job.error:
                job.error = f"exit {job.exit_code}"

    def _gc(self) -> None:
        now = time.time()
        with self._lock:
            drop = []
            for jid, job in self._jobs.items():
                if job.status == "running":
                    continue
                if not job.finished_at:
                    drop.append(jid)
                    continue
                try:
                    fin = datetime.strptime(job.finished_at, "%Y-%m-%dT%H:%M:%SZ")
                    age = now - fin.replace(tzinfo=timezone.utc).timestamp()
                except ValueError:
                    age = TERMINAL_KEEP_S + 1
                if age > TERMINAL_KEEP_S:
                    drop.append(jid)
            overflow = max(0, len(self._jobs) - MAX_JOBS)
            if overflow:
                terminal = sorted(
                    (j for j in self._jobs.values() if j.status != "running"),
                    key=lambda j: j.finished_at or "",
                )
                drop.extend(j.id for j in terminal[:overflow])
            for jid in dict.fromkeys(drop):
                self._jobs.pop(jid, None)
                self._procs.pop(jid, None)
                self._threads.pop(jid, None)
                self._stop.discard(jid)


_STORE: KernelJobStore | None = None
_STORE_LOCK = threading.Lock()


def get_store() -> KernelJobStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = KernelJobStore()
        return _STORE


def reset_store_for_tests(store: KernelJobStore | None = None) -> KernelJobStore:
    global _STORE
    with _STORE_LOCK:
        _STORE = store if store is not None else KernelJobStore()
        return _STORE
