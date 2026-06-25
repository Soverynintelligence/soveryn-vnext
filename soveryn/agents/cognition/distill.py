"""Sense-of-us note distillation for the continuous-cognition pipeline.

Spec: docs/superpowers/specs/2026-06-22-continuous-cognition-design.md
      "Consolidation + decay", "ambient not instruction",
      sense-of-us note / bounded rewrite.

## What this module does

`distill()` synthesizes a window of reflection memories into a small,
bounded, sense-of-us note about communicating with a specific user.  It is
called at the end of a deep cognition cycle.  The note is a REWRITE (new
NoteVersion superseding the prior), never an append — keeping it current,
small, and non-brittle.

## Ambient observation rule (load-bearing)

The distill prompt instructs the model to write observations in the
ambient form: **what is noticed, not what to do**.
  Good: "Jon reads hedging as noise."
  Bad:  "Be direct with Jon."  ← instruction, never written

This matches the foreground injection contract: the note sits in the
cache-stable prelude as bare observed data, not a directive, so the agent
assimilates it naturally rather than demonstrating compliance (per the
feedback_ambient_context_not_instruction.md finding).

## Recency / decay semantics

The `memories` list is ordered oldest-first by the caller (consistent with
`CognitionStore.list_reflections()` which returns oldest-first).  The prompt
explicitly states that later memories are more recent and should supersede
contradictions.  Unreinforced observations naturally fall out of the rewrite
because the model synthesizes from the supplied list; entries that are no
longer represented simply do not appear in the new note.

## Empty memories

If `memories` is empty there is nothing to synthesize — writing would
fabricate content, violating the Jon-originated-evidence rule.  `distill()`
returns the current NoteVersion without writing a new one (or returns None
if no note exists).  chat_fn is NOT called.

## chat_fn contract

    chat_fn(system: str, user: str) -> str

Injected callable.  In production: HTTP client to `:8091` (cognition
instance).  In tests: fake returning canned text.  Must be synchronous.

## Size cap

If the model returns more than `max_lines` non-empty lines, the note is
truncated to the first `max_lines` non-empty lines before writing.  Blank
separator lines are preserved between the kept lines but do not count toward
the cap.  This enforces the "never an unbounded growing rulebook" contract.
"""

from __future__ import annotations

import logging
from typing import Callable

from soveryn.agents.cognition.store import CognitionStore
from soveryn.agents.cognition.types import NoteVersion, ReflectionMemory

log = logging.getLogger(__name__)

# ─── Type alias ─────────────────────────────────────────────────────────────

ChatFn = Callable[[str, str], str]
"""chat_fn(system: str, user: str) -> str — returns raw model text."""


# ─── Prompt assembly ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are writing the sense-of-us note for {agent}: a small, bounded record of
what has been noticed about communicating with this user.

AMBIENT OBSERVATION RULE — the only form allowed:
  Write what you have NOTICED, never what to do.
  Correct:   "Jon reads hedging as noise."
  Forbidden: "Be direct with Jon." or "Avoid hedging."
  The note is ambient data, not instruction.

MANNER ONLY — this note covers HOW to communicate:
  tone, length, pacing, when to ask vs. just act, how much to check in,
  how to open and close. Nothing about values, beliefs, or identity.

RECENCY SUPERSEDES — the memories below are ordered oldest first.
  Later entries are more recent and more reinforced. When memories
  contradict, the later one wins. Observations that are no longer
  reinforced simply do not appear in the new note.

SIZE CONSTRAINT — at most {max_lines} non-empty lines. Be concise.
  If you cannot fit everything, keep the most recent and best-evidenced
  observations and drop the rest.

OUTPUT FORMAT:
  Plain text only — one observation per line, no bullets, no headings,
  no markdown formatting, no fences.
  If you have nothing to say, output a single empty line.
"""

_USER_PROMPT = """\
Agent: {agent}

Reflection memories (oldest first — later entries supersede contradictions):
{memories_text}

Write the sense-of-us note now. At most {max_lines} non-empty lines.
Plain text, no fences, no bullets. Ambient observation only.
"""


def _format_memories(memories: list[ReflectionMemory]) -> str:
    lines = []
    for i, m in enumerate(memories, start=1):
        lines.append(f"{i}. [{m.id}] {m.text}")
    return "\n".join(lines)


def _build_prompts(
    agent: str, memories: list[ReflectionMemory], max_lines: int
) -> tuple[str, str]:
    system = _SYSTEM_PROMPT.format(agent=agent, max_lines=max_lines)
    user = _USER_PROMPT.format(
        agent=agent,
        memories_text=_format_memories(memories),
        max_lines=max_lines,
    )
    return system, user


# ─── Fence stripping ──────────────────────────────────────────────────────────

def _strip_fences(raw: str) -> str:
    """Strip markdown code fences if the model wrapped the output.

    Matches the same pattern as reflect.py — handles ``` and ```<lang>.
    """
    stripped = raw.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    return stripped


# ─── Size cap ────────────────────────────────────────────────────────────────

def _enforce_cap(text: str, max_lines: int) -> str:
    """Truncate text so it contains at most max_lines non-empty lines.

    Blank lines are not counted toward the cap.  The function rebuilds
    the output by walking the original lines and stopping once max_lines
    non-empty lines have been collected — preserving the exact text of
    those lines (no trailing whitespace changes beyond what strip() does).
    """
    all_lines = text.splitlines()
    kept: list[str] = []
    non_empty_count = 0
    for line in all_lines:
        if line.strip():
            if non_empty_count >= max_lines:
                break
            non_empty_count += 1
        kept.append(line)
    return "\n".join(kept)


# ─── Public API ──────────────────────────────────────────────────────────────

def distill(
    agent: str,
    memories: list[ReflectionMemory],
    store: CognitionStore,
    chat_fn: ChatFn,
    max_lines: int = 8,
) -> NoteVersion | None:
    """Synthesize reflection memories into a bounded sense-of-us note.

    Parameters
    ----------
    agent:
        The agent name ("aetheria", "vett", …).  Baked into the prompt.
    memories:
        Reflection memories to synthesize, ordered oldest-first.  If empty,
        no write occurs and the current NoteVersion (or None) is returned.
    store:
        CognitionStore to read the current version from and write the new
        version to.
    chat_fn:
        Injected inference callable.  Not called when memories is empty.
    max_lines:
        Maximum number of non-empty lines in the distilled note.  Lines
        beyond this cap are truncated before writing.

    Returns
    -------
    NoteVersion | None
        The newly written NoteVersion, or None if memories was empty (no
        write occurs in that case regardless of whether a prior version exists).
    """
    # Empty memories → nothing to synthesize; skip write entirely.
    if not memories:
        return None

    # Determine the id of the current note version for supersedes linkage.
    supersedes_id: str | None = store.current_note_id()

    # Call the model
    system, user = _build_prompts(agent, memories, max_lines)
    try:
        raw = chat_fn(system, user)
    except Exception:
        log.exception("distill: chat_fn raised; skipping write")
        return None

    if not raw or not raw.strip():
        log.debug("distill: empty response from chat_fn; skipping write")
        return None

    # Strip markdown fences
    content = _strip_fences(raw)

    # Enforce size cap
    content = _enforce_cap(content, max_lines)

    # Write the new note version, superseding the prior if one exists
    note = store.write_note_version(content, supersedes=supersedes_id)
    return note

