"""measure(candidate) -> Measurement — the orchestration primitive.

Launches ONE candidate config on real hardware, runs a fixed prompt, and feeds
the outcome to the pure classifier. Teardown is GUARANTEED but BOUNDED: poll for
VRAM release up to TEARDOWN_TIMEOUT, then warn + return (never hang) — the next
measurement's precondition refuses a still-contaminated device.

The `launcher` seam is injectable so the orchestration is unit-tested with a
fake handle (no GPU). The real subprocess/pynvml handle below is exercised only
by the real-rig self-test (tests/test_tuner_measure_rig.py).
"""
from __future__ import annotations
import json
import logging
import os
import socket
import subprocess
import threading
import time
import urllib.request

from soveryn.platform.tuner.candidate import Candidate, to_llama_server_args
from soveryn.platform.tuner.result import RunOutcome, Measurement, classify

log = logging.getLogger(__name__)

FIXED_PROMPT = "In one short sentence: what is the capital of France?"
_BACKEND_BINARY = {
    "cuda": os.path.expanduser("~/llama.cpp_head/build/bin/llama-server"),
}


def _resolve_binary(backend: str) -> str:
    """Map a candidate's backend to its llama-server binary. No silent fallback."""
    try:
        return _BACKEND_BINARY[backend]
    except KeyError:
        raise ValueError(
            f"unknown backend {backend!r}; known: {sorted(_BACKEND_BINARY)}"
        )


_CUDA_COMPAT = ("/home/jon-deoliveira/miniconda3/envs/cuda131/cuda-compat:"
                "/home/jon-deoliveira/miniconda3/envs/cuda131/lib")


def _cuda_compat_env() -> dict:
    env = dict(os.environ)
    prior = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = _CUDA_COMPAT + (":" + prior if prior else "")
    return env


def measure(candidate: Candidate, *, devices: list[int], port: int = 8199,
            load_timeout: float = 300, gen_timeout: float = 60,
            teardown_timeout: float = 30, launcher=None) -> Measurement:
    launcher = launcher or _real_launcher
    args = to_llama_server_args(candidate, host="127.0.0.1", port=port)
    binary = _resolve_binary(candidate.backend)
    h = launcher(binary, args, _cuda_compat_env())
    try:
        listened = h.wait_listen(load_timeout)
        n_tokens, out_text, tok_s, peak = 0, "", 0.0, {}
        if listened:
            n_tokens, out_text, tok_s = h.benchmark(FIXED_PROMPT, gen_timeout)
            peak = h.peak_vram(devices)
        outcome = RunOutcome(listened=listened, exit_code=None, stderr=h.stderr,
                             generated_tokens=n_tokens, output_text=out_text,
                             gpu_faulted=h.gpu_faulted())
        status, detail = classify(outcome)
        return Measurement(status=status, detail=detail,
                           tok_s=(tok_s if status == "ok" else None), peak_vram=peak)
    finally:
        h.kill()
        if not h.wait_vram_released(devices, teardown_timeout):
            log.warning("TEARDOWN_TIMEOUT: VRAM not released on %s within %ss — returning; "
                        "next precondition will refuse contaminated state", devices, teardown_timeout)


class _RealHandle:
    """Real llama-server subprocess + pynvml telemetry. Hardened by the rig self-test."""

    def __init__(self, binary, args, env, port):
        import pynvml
        self._nvml = pynvml
        pynvml.nvmlInit()
        self._port = port
        self._peak: dict[int, int] = {}
        self._baseline = self._read_vram()
        self._stderr_buf: list[str] = []
        self._sampling = True
        self._proc = subprocess.Popen(
            [binary] + args, env=env,
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read_stderr, daemon=True).start()
        threading.Thread(target=self._sample_vram, daemon=True).start()

    def _read_vram(self) -> dict[int, int]:
        out = {}
        try:
            for i in range(self._nvml.nvmlDeviceGetCount()):
                h = self._nvml.nvmlDeviceGetHandleByIndex(i)
                out[i] = self._nvml.nvmlDeviceGetMemoryInfo(h).used // (1024 * 1024)
        except Exception:
            pass
        return out

    def _read_stderr(self):
        for line in self._proc.stderr:
            self._stderr_buf.append(line)
            if len(self._stderr_buf) > 2000:
                self._stderr_buf.pop(0)

    def _sample_vram(self):
        while self._sampling:
            for d, used in self._read_vram().items():
                self._peak[d] = max(self._peak.get(d, 0), used)
            time.sleep(0.5)

    @property
    def stderr(self) -> str:
        return "".join(self._stderr_buf)

    def wait_listen(self, timeout):
        # Poll the HTTP port, NOT a stderr log string: the log message changed
        # across llama.cpp versions ("server is listening" -> "listening on http")
        # and grepping it silently mis-detects newer builds as hung. The open port
        # is the version-agnostic readiness signal.
        t0 = time.time()
        while time.time() - t0 < timeout:
            if _port_open("127.0.0.1", self._port):
                return True
            if self._proc.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def benchmark(self, prompt, timeout):
        body = json.dumps({"model": "tuner",
                           "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 64, "temperature": 0.0}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{self._port}/v1/chat/completions",
            data=body, headers={"Content-Type": "application/json"})
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.load(r)
        except Exception:
            return (0, "", 0.0)          # no healthy generation -> classified hung
        dt = max(time.time() - t0, 1e-6)
        text = (d.get("choices", [{}])[0].get("message", {}).get("content") or "")
        n = d.get("usage", {}).get("completion_tokens", len(text.split()))
        return (n, text, (n / dt if n else 0.0))

    def peak_vram(self, devices):
        return {d: self._peak.get(d, 0) for d in devices}

    def gpu_faulted(self):
        try:
            for i in range(self._nvml.nvmlDeviceGetCount()):
                h = self._nvml.nvmlDeviceGetHandleByIndex(i)
                ue = self._nvml.nvmlDeviceGetTotalEccErrors(
                    h, self._nvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
                    self._nvml.NVML_VOLATILE_ECC)
                if ue and ue > 0:
                    return True
        except Exception:
            pass
        return False

    def kill(self):
        self._sampling = False
        try:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass

    def wait_vram_released(self, devices, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                now = self._read_vram()
                if all(now.get(d, 0) <= self._baseline.get(d, 0) + 300 for d in devices):
                    return True
            except Exception:
                return True   # can't verify -> don't hang
            time.sleep(1)
        return False


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if a TCP connection to host:port succeeds — a version-agnostic
    'server is ready' signal (no dependence on a specific stderr log message)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _real_launcher(binary, args, env):
    port = int(args[args.index("--port") + 1])
    return _RealHandle(binary, args, env, port)
