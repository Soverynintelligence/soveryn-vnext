"""Smoke tests for the Vett harness port (phase 1).

These tests assert the SOVERYN harness package loads and its
integration seams hold. They DO NOT exercise the vendored harness
itself — that comes in later tasks.
"""
from __future__ import annotations
import importlib


def test_package_importable():
    """The SOVERYN harness package can be imported from a fresh interpreter."""
    mod = importlib.import_module("soveryn.agents.vett.harness")
    assert mod is not None
