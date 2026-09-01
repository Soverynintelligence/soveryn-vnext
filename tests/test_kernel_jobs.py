"""Kernel child jobs — list / stop (keep partial) / steer (stop + follow-up)."""
from __future__ import annotations

import threading

from soveryn.platform.kernel_jobs import KernelJobStore


class _FakeProc:
    def __init__(self, pid: int, *, block: bool):
        self.pid = pid
        self.returncode = None
        self._killed = False
        self._block = block
        self._gate = threading.Event()

    def communicate(self, timeout=None):
        if self._block and not self._killed:
            self._gate.wait(timeout if timeout else 30)
        if self._killed:
            self.returncode = -15
            return ("partial patch on seats.py\n", "")
        self.returncode = 0
        return ("done seats.py\n", "")


def _store(*, block: bool = False):
    procs: list[_FakeProc] = []
    killed: list[tuple[int, int]] = []

    def popen(cmd, **kwargs):
        p = _FakeProc(pid=5000 + len(procs), block=block)
        procs.append(p)
        return p

    def killpg(pgid, sig):
        killed.append((pgid, sig))
        for p in procs:
            p._killed = True
            p._gate.set()

    store = KernelJobStore(
        popen_fn=popen, killpg_fn=killpg, getpgid_fn=lambda pid: pid
    )
    return store, procs, killed


def test_spawn_wait_succeeds():
    store, _procs, _killed = _store()
    job = store.spawn(
        kind="aider",
        prompt="fix seats",
        repo="/tmp/house",
        cmd=["soveryn-aider", "--message", "fix seats"],
        cwd="/tmp/house",
        env={},
        timeout_s=30,
    )
    snap = store.wait(job.id)
    assert snap["ok"] is True
    assert snap["status"] == "succeeded"
    assert "done" in snap["output"]


def test_stop_keeps_partial_output():
    store, procs, killed = _store(block=True)
    job = store.spawn(
        kind="opencode",
        prompt="rewrite the world",
        repo="/tmp/house",
        cmd=["soveryn-opencode", "run", "--auto", "x"],
        cwd="/tmp/house",
        env={},
        timeout_s=30,
    )
    out = store.stop(job.id)
    assert out["ok"] is True
    assert out["status"] == "stopped"
    assert "partial" in out["output"]
    assert killed


def test_list_running_then_empty_after_stop():
    store, _procs, _killed = _store(block=True)
    job = store.spawn(
        kind="aider",
        prompt="x",
        repo="/tmp/house",
        cmd=["aider"],
        cwd="/tmp/house",
        env={},
        timeout_s=30,
    )
    running = store.list_jobs(running_only=True)
    assert any(r["id"] == job.id for r in running)
    store.stop(job.id)
    assert store.list_jobs(running_only=True) == []
    assert any(r["id"] == job.id for r in store.list_jobs())


def test_steer_stops_and_spawns_follow_up():
    store, _procs, _killed = _store(block=True)
    job = store.spawn(
        kind="aider",
        prompt="add clamp",
        repo="/tmp/house",
        cmd=["aider"],
        cwd="/tmp/house",
        env={},
        timeout_s=30,
    )

    def spawn_fn(*, kind, prompt, repo, follow_of):
        return store.spawn(
            kind=kind,
            prompt=prompt,
            repo=repo,
            cmd=["aider"],
            cwd=repo,
            env={},
            timeout_s=30,
            follow_of=follow_of,
        )

    out = store.steer(job.id, "don't rewrite the file, patch only", spawn_fn=spawn_fn)
    assert out["ok"] is True
    assert out["follow_up"]["follow_of"] == job.id
    assert "patch only" in out["follow_up"]["prompt"] or True
    # prompt is truncated in snapshot to 240 chars — check store
    follow = store._jobs[out["follow_up"]["id"]]
    assert "Don't revert" in follow.prompt or "Do not revert" in follow.prompt
    assert "patch only" in follow.prompt
