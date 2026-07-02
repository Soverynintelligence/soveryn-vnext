"""Pure failure classification for the tuner — the correctness heart.

Every failure class is decided here from captured signals (stderr, whether the
server listened, whether generation produced tokens, the output text, and a
hardware-fault flag). No GPU needed to test it. Detection ORDER matters:
hardware_error is checked before oom/load_failed because a faulted card can
masquerade as either.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Measurement:
    status: str                      # ok|oom|load_failed|hung|garbage|hardware_error
    tok_s: float | None = None
    peak_vram: dict[int, int] = field(default_factory=dict)
    detail: str = ""


@dataclass
class RunOutcome:
    listened: bool
    exit_code: int | None
    stderr: str
    generated_tokens: int
    output_text: str
    gpu_faulted: bool = False


# Signal strings — grounded in real incidents from this project.
_HARDWARE = ("has fallen off the bus", "an illegal memory access",
             "unspecified launch failure", "device-side assert", "xid",
             "uncorrectable ecc", "ecc error")
_OOM = ("cudamalloc failed: out of memory", "failed to allocate", "out of memory")
_LOAD_FAILED = ("cuda driver version is insufficient", "failed to load model",
                "error while handling argument", "unknown value for", "unknown argument")


def is_degenerate(text: str) -> bool:
    """v1 garbage heuristic: empty, single-token loop, or tiny-vocabulary loop.

    Deliberately conservative to avoid false positives (a subtly-wrong-but-fluent
    answer is NOT caught here — full quality-regression detection is deferred).
    """
    t = text.strip()
    if not t:
        return True
    toks = t.split()
    if len(toks) >= 6:
        top = max(set(toks), key=toks.count)
        if toks.count(top) / len(toks) > 0.6:
            return True
        if len(set(toks)) <= max(2, len(toks) // 5):
            return True
    return False


def classify(o: RunOutcome) -> tuple[str, str]:
    """Return (status, detail). Order: hardware -> oom -> load_failed -> ok/garbage -> hung."""
    s = (o.stderr or "").lower()

    def _hit(sigs):
        return next((x for x in sigs if x in s), None)

    # 1. hardware first — a faulted card masquerades as oom/load_failed
    if o.gpu_faulted:
        return "hardware_error", "gpu_faulted flag set"
    if (h := _hit(_HARDWARE)):
        return "hardware_error", f"hardware signal: {h!r}"
    # 2. clean out-of-memory
    if (h := _hit(_OOM)):
        return "oom", f"oom signal: {h!r}"
    # 3. bad config / env / args
    if (h := _hit(_LOAD_FAILED)):
        return "load_failed", f"load-failure signal: {h!r}"
    # 4. did it actually generate?
    if o.listened and o.generated_tokens > 0:
        if is_degenerate(o.output_text):
            return "garbage", "degenerate/empty output"
        return "ok", "clean run"
    # listened but produced nothing, or never listened without a known error -> hung
    return "hung", "no healthy generation (timed out at load or during gen)"
