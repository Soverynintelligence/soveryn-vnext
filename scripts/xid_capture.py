#!/usr/bin/env python
"""Arm a capture that fires on the next Blackwell Xid and records what led to it.

    python scripts/xid_capture.py                  # run in foreground
    systemctl --user start soveryn-xid-capture     # or as a unit

Since 2026-07-25 the Blackwell (PCI 0000:c1:00) has raised `Xid 8` every one to
three days, each time taking Aetheria's llama-server with it. The driver's own
words are the whole diagnosis so far:

    NVRM: krcWatchdog_IMPL: RC watchdog: GPU is probably locked!
          Notify Timeout Seconds: 7
    NVRM: Xid (PCI:0000:c1:00): 8, pid=..., name=llama-server

That is a *timeout*, not a hardware error — the driver waited 7 seconds for the
card to acknowledge and gave up. Three of the five events we could reconstruct
fired 2, 5 and 6 seconds AFTER the slot released and the server reported all
slots idle, which points at the teardown or power-state transition following a
large-context request rather than at generation itself.

Why capture instead of reproduce: the event occurs on 0.361% of requests — 8 in
2,217 over 13 days, about 1 in 277. A 6-trial synthetic test had a 2.1% chance
of catching it and caught nothing, which is uninformative. Getting to even odds
means ~200 requests and roughly an hour of saturating the card Aetheria runs on.
Waiting is free, and the natural trigger carries everything a synthetic probe
omits: her real system prompt, tool definitions, images through the mmproj, and
concurrent heartbeat/dream traffic.

The value here is the RING BUFFER. `nvidia-smi` run after the Xid describes a
card that has already failed. What nobody has is the ten minutes before — clocks,
power, P-state, and whether a request was in flight. This samples that
continuously and dumps it only when the event fires.

Read-only. It observes and writes a report; it never restarts or reconfigures
anything.
"""
from __future__ import annotations

import collections
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

GPU_UUID = "GPU-946b08b0-e9d3-949b-6eab-b6c5b8a5f5cd"   # the Blackwell
PCI_TAG = "Xid (PCI:0000:c1:00)"
# Backend port is discovered per-sample; see _aetheria_port().
OUT_DIR = Path(os.environ.get("XID_CAPTURE_DIR",
                              Path.home() / "soveryn_vnext" / "data" / "xid_captures"))
SAMPLE_SECONDS = 2.0
RING_MINUTES = 12
RING_LEN = int(RING_MINUTES * 60 / SAMPLE_SECONDS)
ALERT = Path.home() / "soveryn_vnext" / "scripts" / "alert_signal.sh"

# Sampled by the ring. Anything that could plausibly distinguish "idle
# transition" from "still busy" belongs here — the point is to not have to guess
# afterwards which field mattered.
QUERY = ("timestamp,power.draw,clocks.sm,clocks.mem,pstate,temperature.gpu,"
         "utilization.gpu,utilization.memory,memory.used,"
         "pcie.link.gen.current,pcie.link.width.current")

_ring: collections.deque = collections.deque(maxlen=RING_LEN)
_stop = threading.Event()


def _sample_gpu() -> dict | None:
    try:
        r = subprocess.run(
            ["nvidia-smi", f"--id={GPU_UUID}", f"--query-gpu={QUERY}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
    except Exception as exc:
        # A failed probe is recorded AS a failed probe. It must never look like
        # a healthy sample with zeroes in it.
        return {"probe_error": f"{type(exc).__name__}: {exc}"}
    if r.returncode != 0:
        return {"probe_error": f"nvidia-smi rc={r.returncode}: {r.stderr.strip()[:160]}"}
    keys = QUERY.split(",")
    vals = [v.strip() for v in r.stdout.strip().split(",")]
    if len(vals) != len(keys):
        return {"probe_error": f"unexpected field count {len(vals)} != {len(keys)}"}
    return dict(zip(keys, vals))


def _aetheria_port() -> int | None:
    """Find the port Aetheria's backend is on, right now.

    The router spawns her llama-server on a port it picks at load time, so this
    changes on every restart — and this capture exists precisely because she
    restarts every day or two. A hardcoded port would go stale on the first
    event we care about and silently sample nothing.
    """
    try:
        out = subprocess.run(["ps", "-eo", "args"], capture_output=True,
                             text=True, timeout=6).stdout
    except Exception:
        return None
    for line in out.splitlines():
        if "llama-server" not in line or "--alias aetheria" not in line:
            continue
        parts = line.split()
        if "--port" in parts:
            try:
                return int(parts[parts.index("--port") + 1])
            except (ValueError, IndexError):
                return None
    return None


def _sample_slots() -> dict:
    """Was a request in flight? llama.cpp exposes /slots on the BACKEND port."""
    port = _aetheria_port()
    if port is None:
        # Her backend is not running. That is itself a finding, and it must not
        # be recorded as "no slots busy".
        return {"slots_error": "aetheria llama-server not found in process list"}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/slots", timeout=3) as r:
            data = json.loads(r.read())
    except Exception as exc:
        return {"slots_error": f"port {port}: {type(exc).__name__}: {str(exc)[:80]}"}
    if not isinstance(data, list):
        return {"slots_raw": str(data)[:200]}
    return {
        "n_slots": len(data),
        "busy": sum(1 for s in data if s.get("is_processing")),
        "detail": [{"id": s.get("id"), "processing": s.get("is_processing"),
                    "n_past": s.get("n_past"), "n_ctx": s.get("n_ctx")}
                   for s in data[:4]],
    }


def _sampler() -> None:
    while not _stop.is_set():
        _ring.append({"t": datetime.now().isoformat(timespec="milliseconds"),
                      "gpu": _sample_gpu(), "slots": _sample_slots()})
        _stop.wait(SAMPLE_SECONDS)


def _journal(unit_args: list[str], since: str, until: str | None = None) -> str:
    cmd = ["journalctl", *unit_args, "--since", since, "--no-pager"]
    if until:
        cmd += ["--until", until]
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=45).stdout
    except Exception as exc:
        return f"<journal read failed: {type(exc).__name__}: {exc}>"


def _capture(trigger_line: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"xid-{stamp}.json"

    # Snapshot the ring FIRST — every second spent collecting anything else is a
    # second of post-failure state contaminating the picture.
    ring = list(_ring)

    report = {
        "captured_at": datetime.now().isoformat(),
        "trigger_line": trigger_line.strip(),
        "ring": {
            "samples": len(ring),
            "covers_minutes": RING_MINUTES,
            "sample_interval_s": SAMPLE_SECONDS,
            "data": ring,
        },
        "post_event": {
            "gpu": _sample_gpu(),
            "slots": _sample_slots(),
        },
        "nvidia_smi_full": subprocess.run(
            ["nvidia-smi", "-q", f"--id={GPU_UUID}"],
            capture_output=True, text=True).stdout[:20000],
        "kernel_log": _journal(["-k"], "-15 min"),
        "llama_log": _journal(["--user"], "-15 min"),
        "processes": subprocess.run(
            ["ps", "-eo", "pid,etime,rss,pcpu,cmd", "--sort=-rss"],
            capture_output=True, text=True).stdout[:6000],
        "loadavg": Path("/proc/loadavg").read_text().strip(),
    }
    path.write_text(json.dumps(report, indent=2))
    return path


def _notify(path: Path) -> None:
    if not ALERT.exists() or not os.access(ALERT, os.X_OK):
        return
    try:
        subprocess.run([str(ALERT),
                        f"Blackwell Xid captured — {path.name}. "
                        f"Ring buffer holds the {RING_MINUTES} min before it."],
                       timeout=30)
    except Exception:
        pass  # a failed alert must not take down the capture


def main() -> int:
    if not shutil.which("nvidia-smi"):
        print("nvidia-smi not found — cannot arm", file=sys.stderr)
        return 2

    threading.Thread(target=_sampler, daemon=True).start()
    print(f"armed: watching for {PCI_TAG}")
    print(f"  ring {RING_MINUTES} min @ {SAMPLE_SECONDS}s = {RING_LEN} samples")
    print(f"  captures -> {OUT_DIR}")
    sys.stdout.flush()

    # Follow the kernel log from NOW. `-n0` so arming does not re-fire on the
    # eight events already in the journal.
    proc = subprocess.Popen(["journalctl", "-k", "-f", "-n0", "--no-pager"],
                            stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if PCI_TAG not in line:
                continue
            # Let the ring pick up a few post-event samples before dumping, so
            # the report shows the transition rather than stopping at it.
            time.sleep(SAMPLE_SECONDS * 3)
            path = _capture(line)
            print(f"CAPTURED {path}")
            sys.stdout.flush()
            _notify(path)
    except KeyboardInterrupt:
        pass
    finally:
        _stop.set()
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
