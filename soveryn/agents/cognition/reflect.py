"""Manner-reflection pipeline for the continuous-cognition system.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "manner-reflection pipeline", "worth-keeping gate", "scope fence"

## What this module does

`reflect()` takes a window of recent conversation turns, a prior sense-of-us
note (what the cognition system already knows about communicating with this
user), and an injected inference callable, and returns a list of
CandidateObservation objects for the worth-keeping gate to route.

The observations are about HOW to communicate with the user — manner, tone,
pacing — not what to believe about them.  Anything that reaches toward values
or identity is tagged scope="value" or scope="unsure" by the model; the gate
then surfaces those to Jon rather than integrating them autonomously.

## chat_fn contract

    chat_fn(system: str, user: str) -> str

A pure callable that accepts a system prompt and a user prompt and returns the
model's raw text response.  In production this is wired to the cognition
instance (:8091).  In tests it is a fake that returns canned JSON.

The function must be synchronous.  Streaming is not used here — the reflection
pass produces a bounded output (a JSON array) and is not latency-sensitive from
the user's perspective.

## Scope fence (load-bearing)

The prompt bakes in the scope fence from the spec:
  - manner  → how to communicate (eligible for autonomous self-application)
  - value   → what to believe about the user or oneself (surface to Jon)
  - unsure  → conservative default; treated as value-reaching

Jon-originated evidence rule: citations must come from the USER's words and
reactions, not from the agent's own outputs.  The prompt instructs the model
on this; the gate enforces it deterministically via jon_originated.

## Graceful degradation

A bad model response (malformed JSON, missing fields, wrong type) never raises.
Bad items are skipped; the function returns whatever well-formed observations
were recoverable, or [] if none were.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

from soveryn.agents.cognition.types import CandidateObservation, Turn

log = logging.getLogger(__name__)

# ─── Type alias for the injected inference callable ─────────────────────────

ChatFn = Callable[[str, str], str]
"""chat_fn(system: str, user: str) -> str — returns raw model text."""


# ─── Prompt assembly ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are the reflective cognition layer for {agent}.

Your task: review the conversation turns below and identify candidate \
observations about HOW to communicate with this user — tone, length, pacing, \
when to ask questions versus just act, how much to check in, how to open and \
close exchanges.

SCOPE FENCE — classify every observation into exactly one scope:
  "manner"  — about how to communicate; eligible for autonomous self-application.
  "value"   — reaching toward what to believe about the user or about yourself,
               or generalising a manner across relationships. Surface to the user,
               never silently self-edit.
  "unsure"  — conservative default when you cannot confidently classify.
               Treated as value-reaching; will be surfaced, never integrated.
  When in doubt, use "unsure". The gate defaults to "surface" for anything
  that is not clearly "manner".

JON-ORIGINATED EVIDENCE RULE:
  "jon_originated" must be true ONLY when the evidence is the USER's own words
  or reactions — what they said, how they reacted, what they corrected.
  It must be false when your evidence is drawn from the agent's own outputs.
  The agent's behaviour cannot be evidence for a manner change.

WHAT IS ALREADY KNOWN (prior sense-of-us note — do not repeat these):
{prior_note}

OUTPUT FORMAT — return a JSON array and nothing else:
[
  {{
    "text": "<observation in one or two sentences>",
    "scope": "manner" | "value" | "unsure",
    "citations": ["<turn_id>", ...],
    "jon_originated": true | false
  }}
]

Rules:
  - Only include observations backed by at least one cited turn_id.
  - Do not invent citations; only cite turn_ids that appear in the conversation.
  - If you have no observations, return an empty array: []
  - Do not include any text outside the JSON array.
"""

_USER_PROMPT = """\
Agent: {agent}

Conversation turns:
{turns_text}

Emit your JSON array of candidate observations now.
"""


def _format_turns(turns: list[Turn]) -> str:
    lines = []
    for t in turns:
        lines.append(f"[{t.turn_id}] {t.role}: {t.content}")
    return "\n".join(lines)


def _build_prompts(agent: str, turns: list[Turn], prior_note: str) -> tuple[str, str]:
    system = _SYSTEM_PROMPT.format(
        agent=agent,
        prior_note=prior_note if prior_note.strip() else "(none)",
    )
    user = _USER_PROMPT.format(
        agent=agent,
        turns_text=_format_turns(turns),
    )
    return system, user


# ─── Item parsing ─────────────────────────────────────────────────────────────

def _parse_item(item: object) -> CandidateObservation | None:
    """Parse one raw item from the model's JSON array.

    Returns a CandidateObservation on success, None if the item is malformed
    or missing any required field.
    """
    if not isinstance(item, dict):
        log.debug("reflect: skipping non-dict item: %r", item)
        return None

    try:
        text: str = item["text"]
        scope: str = item["scope"]
        citations_raw: list = item["citations"]
        jon_originated: bool = item["jon_originated"]
    except KeyError as exc:
        log.debug("reflect: skipping item missing field %s: %r", exc, item)
        return None

    if not isinstance(text, str):
        log.debug("reflect: skipping item with non-str text: %r", item)
        return None
    if not isinstance(scope, str):
        log.debug("reflect: skipping item with non-str scope: %r", item)
        return None
    if not isinstance(citations_raw, list):
        log.debug("reflect: skipping item with non-list citations: %r", item)
        return None
    if not isinstance(jon_originated, bool):
        log.debug("reflect: skipping item with non-bool jon_originated: %r", item)
        return None

    citations: tuple[str, ...] = tuple(str(c) for c in citations_raw)
    return CandidateObservation(
        text=text,
        scope=scope,
        citations=citations,
        jon_originated=jon_originated,
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def reflect(
    agent: str,
    turns: list[Turn],
    prior_note: str,
    chat_fn: ChatFn,
) -> list[CandidateObservation]:
    """Run the reflection pass and return candidate observations.

    Parameters
    ----------
    agent:
        The agent name ("aetheria", "vett", …).  Baked into the prompt so
        the model knows whose voice/context it is reasoning about.
    turns:
        Recent conversation turns to reflect on.  Empty list → returns []
        immediately without calling chat_fn.
    prior_note:
        The current sense-of-us note (what is already known).  The model is
        instructed not to repeat observations already present here.
    chat_fn:
        Injected inference callable with signature
            chat_fn(system: str, user: str) -> str
        In production: the cognition-instance HTTP client (:8091).
        In tests: a fake returning canned JSON.

    Returns
    -------
    list[CandidateObservation]
        Parsed candidate observations.  Malformed items are skipped, not
        raised.  Returns [] if no observations or on complete parse failure.
    """
    if not turns:
        return []

    system, user = _build_prompts(agent, turns, prior_note)

    try:
        raw = chat_fn(system, user)
    except Exception:
        log.exception("reflect: chat_fn raised; returning []")
        return []

    if not raw or not raw.strip():
        log.debug("reflect: empty response from chat_fn; returning []")
        return []

    # Strip markdown code fences that LLMs commonly emit around JSON
    # (```json ... ``` or ``` ... ```), then fall through to json.loads.
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Drop the opening fence line (```json or ```)
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        # Drop the closing ``` if present
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
        raw = stripped

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("reflect: JSON decode failed; returning []. raw=%r", raw[:200])
        return []

    if not isinstance(parsed, list):
        log.debug("reflect: top-level value is not a list; returning []. type=%s", type(parsed))
        return []

    results: list[CandidateObservation] = []
    for item in parsed:
        obs = _parse_item(item)
        if obs is not None:
            results.append(obs)

    return results
