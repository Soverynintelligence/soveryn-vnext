"""Smoke tests for the Vett harness port (phase 1).

These tests assert the SOVERYN harness package directory is importable.
Integration-seam tests (against the vendored harness, the lattice, and
the live router) land in Task 12.
"""
from __future__ import annotations
import importlib


def test_package_importable():
    """The SOVERYN harness package directory is importable.

    This is a structural floor — catches syntax errors in __init__.py
    and confirms the package path resolves. It does NOT exercise any
    integration seam; those are tested in Task 12.
    """
    mod = importlib.import_module("soveryn.agents.vett.harness")
    assert mod is not None
