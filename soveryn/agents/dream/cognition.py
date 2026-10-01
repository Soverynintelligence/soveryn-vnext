"""Cognition surface client + three-pass orchestrator.

Low-level: chat_completion() wraps a single OpenAI-compat POST to the
cognition URL.

Orchestrator: run_three_pass() drives the association → contradiction →
synthesis loop per Aetheria's amendment. Writeback fires only after the
loop completes (in the daemon, not here).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from soveryn.agents.dream.prompt import (
    DreamBriefing,
    render_association_pass,
    render_contradiction_pass,
    render_synthesis_pass,
)


class CognitionError(RuntimeError):
    """Cognition surface unreachable / malformed / timed out."""


@dataclass(frozen=True)
class CognitionResult:
    """Output of the three-pass loop. Synthesis is what gets written to the
    dream layer; associations + contradictions are kept for debugging /
    audit / iteration."""
    iterations_completed: int
    associations: str
    contradictions: str
    synthesis: str
    loop_health: float
    error: str | None


def chat_completion(
    *, url: str, messages: list[dict], timeout: int,
) -> str:
    """POST to OpenAI-compat /v1/chat/completions. Return the content string."""
    payload = {
        "messages": messages,
        "model": os.environ.get("SOVERYN_DREAM_COGNITION_MODEL", "cognition"),
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    body = json.dumps(payload).encode()
    full_url = url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        full_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        raise CognitionError(f"HTTP failure: {e}") from e
    except json.JSONDecodeError as e:
        raise CognitionError(f"non-JSON response: {e}") from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise CognitionError(f"unexpected response shape: {e}") from e
    if not isinstance(content, str):
        raise CognitionError(
            f"content was not a string: {type(content).__name__}"
        )
    return content


def run_three_pass(
    *,
    briefing: DreamBriefing,
    cognition_url: str,
    timeout_seconds: int,
    max_internal_iterations: int,
) -> CognitionResult:
    """Run associations → contradictions → synthesis. Best-effort: if a
    later pass fails, use the prior pass's output as the synthesis.

    Returns a CognitionResult with loop_health computed from iterations
    completed and any error encountered.
    """
    associations = ""
    contradictions = ""
    synthesis = ""
    iterations = 0
    error: str | None = None

    # ── Pass 1: Associations
    if max_internal_iterations >= 1:
        try:
            associations = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_association_pass(briefing)}],
                timeout=timeout_seconds,
            )
            iterations = 1
        except CognitionError as e:
            error = f"pass 1 (associations): {e}"
            return CognitionResult(
                iterations_completed=0, associations="", contradictions="",
                synthesis="", loop_health=0.0, error=error,
            )

    # ── Pass 2: Contradictions
    if max_internal_iterations >= 2:
        try:
            contradictions = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_contradiction_pass(
                    briefing, prior_associations=associations,
                )}],
                timeout=timeout_seconds,
            )
            iterations = 2
        except CognitionError as e:
            error = f"pass 2 (contradictions): {e}"
            # Fall back: use pass 1 as the synthesis
            return CognitionResult(
                iterations_completed=1,
                associations=associations,
                contradictions="",
                synthesis=associations,
                loop_health=_compute_loop_health(1, max_internal_iterations),
                error=error,
            )

    # ── Pass 3: Synthesis
    if max_internal_iterations >= 3:
        try:
            synthesis = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_synthesis_pass(
                    briefing,
                    prior_associations=associations,
                    prior_contradictions=contradictions,
                )}],
                timeout=timeout_seconds,
            )
            iterations = 3
        except CognitionError as e:
            error = f"pass 3 (synthesis): {e}"
            # Fall back: use pass 2 output (which built on pass 1)
            return CognitionResult(
                iterations_completed=2,
                associations=associations,
                contradictions=contradictions,
                synthesis=contradictions,
                loop_health=_compute_loop_health(2, max_internal_iterations),
                error=error,
            )

    # If we capped at fewer than 3 internal iterations, synthesis falls back
    # to the latest produced content. iterations is whichever cap hit.
    if iterations < 3:
        synthesis = contradictions or associations

    return CognitionResult(
        iterations_completed=iterations,
        associations=associations,
        contradictions=contradictions,
        synthesis=synthesis,
        loop_health=_compute_loop_health(iterations, max_internal_iterations),
        error=error,
    )


def _compute_loop_health(iterations_completed: int, cap: int) -> float:
    """Linear fraction of the configured cap that we actually finished."""
    if cap <= 0:
        return 0.0
    return min(1.0, iterations_completed / cap)
