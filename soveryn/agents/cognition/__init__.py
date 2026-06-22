"""Cognition pipeline — domain types and lattice store for manner-reflection.

Part of the Continuous Cognition build (spec:
docs/superpowers/specs/2026-06-22-continuous-cognition-design.md).

This package is agent-parameterised: it is not hard-coded to Aetheria. Vett
can adopt it with config, not a rewrite.

Public surface:
  CandidateObservation   — pre-gate observation from the reflection pipeline
  ReflectionMemory       — persisted, evidence-backed reflection
  NoteVersion            — a single version of the sense-of-us note
  CognitionWriteError    — raised when the isolation guard blocks a write
  CognitionStore         — lattice-backed store; composes over the nodes table
"""

from soveryn.agents.cognition.types import (
    CandidateObservation,
    CognitionWriteError,
    NoteVersion,
    ReflectionMemory,
)
from soveryn.agents.cognition.store import CognitionStore

__all__ = [
    "CandidateObservation",
    "CognitionWriteError",
    "CognitionStore",
    "NoteVersion",
    "ReflectionMemory",
]
