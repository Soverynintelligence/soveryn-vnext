# Vett Harness-1 Port — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone CLI runner that executes the Harness-1 retrieval orchestration on Vett's existing model and SOVERYN's lattice, with bounded turns and full trajectory audit, so we can measure architectural lift on representative SOVERYN tasks against Vett-current.

**Architecture:** Vendor `pat-jj/harness-1/harness/` into `soveryn/agents/vett/harness/vendor/`. The vendored harness exposes an `Agent` runtime that wraps an `InferenceModel` (LLM client) and tool handlers. Two SOVERYN shims plug in: an inference-model subclass targeting our llama-server router at `:8090` model=`vett-scotty`; lattice-backed tool handlers for `fan_out_search` / `search_corpus` / `read_doc`. CLI runner enforces turn budget, persists trajectories to JSON, and logs failure-mode telemetry. No Vett product surface is wired; eval-only.

**Tech Stack:** Python 3.11+, pytest, httpx, openai (pip), pydantic, vendored `harness/` package (Apache 2.0), SOVERYN's existing lattice module (`soveryn.memory.lattice`), llama-server protocol (OpenAI-compat chat completions).

**Integration depth caveat:** Harness was trained on gpt-oss-20b + openai_harmony format. Vett is Qwen3.6-27B served via llama-server's OpenAI-compat layer. This plan uses the chat-completions inference model class to avoid token-level coupling with gpt-oss-20b's tokenizer. Two **blocker tasks** verify assumptions against the live codebase before implementation code is written: Task 3 verifies Vett accepts the harness's chat-completions message shape; Task 5 verifies the lattice/embed API signatures and import paths the handler code will use. If either blocker fails, downstream tasks pause until resolved — no hidden fixes inside dependent tasks.

**Linked spec:** `docs/superpowers/specs/2026-06-11-vett-harness-port-design.md`

---

### Task 1: Bootstrap branch + package skeleton

**Files:**
- Create: `soveryn/agents/vett/harness/__init__.py`
- Create: `soveryn/agents/vett/harness/vendor/.gitkeep`
- Create: `LICENSES/harness-1-APACHE-2.0`
- Create: `LICENSES/harness-1-NOTICE`
- Test: `tests/test_vett_harness_smoke.py`

- [ ] **Step 1: Preflight + cut a branch**

Run preflight to confirm the working tree is in a state we can branch from cleanly:
```bash
cd ~/soveryn_vnext
git status --short
```

Expected: at most the harmless untracked `data/memory/`, `data/router-presets.ini`, `data/templates_legacy/`, `data/voice/`, and `docs/superpowers/specs/2026-06-11-cross-rail-active-context-design.md`. **STOP** if any of the following appear and were not deliberately staged by you:
- `M soveryn/agents/loop.py` (Codex's in-flight work — wait for that to land first)
- `M tests/test_agent_loop_history_budget.py` (same)
- Any other modified file under `soveryn/` that you didn't put there

If the working tree is dirty in unexpected ways, escalate to Jon before continuing. Do NOT stash or discard.

If preflight is clean, cut the branch:
```bash
git checkout main
git pull --ff-only
git checkout -b vett-harness-phase1
```

- [ ] **Step 2: Write the failing smoke test asserting the package imports**

Create `tests/test_vett_harness_smoke.py`:
```python
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
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_smoke.py::test_package_importable -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness'`

- [ ] **Step 4: Create the package skeleton**

Create `soveryn/agents/vett/harness/__init__.py`:
```python
"""SOVERYN Vett — Harness-1 port (phase 1, eval-only).

Vendored harness code lives under `vendor/` with its upstream
Apache 2.0 LICENSE and NOTICE preserved at `LICENSES/`. SOVERYN
shims (inference model, lattice tool handlers, CLI runner) live
alongside this __init__.

This package is NOT wired into Vett's normal task surface in
phase 1. See `docs/superpowers/specs/2026-06-11-vett-harness-port-design.md`.
"""
```

Create `soveryn/agents/vett/harness/vendor/.gitkeep`:
```
# Placeholder. Task 2 vendors the upstream harness/ Python module here.
```

- [ ] **Step 5: Write the license + notice**

Fetch the Apache 2.0 license text from `https://www.apache.org/licenses/LICENSE-2.0.txt` and save it to `LICENSES/harness-1-APACHE-2.0`.

Create `LICENSES/harness-1-NOTICE`:
```
Harness-1
Copyright 2026 The Harness-1 Authors (Pengcheng Jiang et al.)
Original source: https://github.com/pat-jj/harness-1

This product includes software vendored from the Harness-1 project,
distributed under the Apache License, Version 2.0. The original
source is preserved verbatim under
`soveryn/agents/vett/harness/vendor/`.

SOVERYN-side modifications (not part of upstream Harness-1):
- `soveryn/agents/vett/harness/llm_client.py` — chat-completions
  inference model targeting llama-server router at :8090 (replaces
  the upstream Modal/Tinker/OpenAI client defaults).
- `soveryn/agents/vett/harness/lattice_tools.py` — tool handlers
  for fan_out_search/search_corpus/read_doc backed by SOVERYN's
  Synapse lattice (replaces the upstream Chroma corpus backend).
- `soveryn/agents/vett/harness/run_eval.py` — standalone CLI runner
  with turn budget, trajectory JSON persistence, and failure-mode
  telemetry.

No modifications were made to files under
`soveryn/agents/vett/harness/vendor/`.
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_vett_harness_smoke.py::test_package_importable -v`
Expected: PASS, 1 passed in <1s

- [ ] **Step 7: Commit**

```bash
git add soveryn/agents/vett/harness/__init__.py \
        soveryn/agents/vett/harness/vendor/.gitkeep \
        LICENSES/harness-1-APACHE-2.0 \
        LICENSES/harness-1-NOTICE \
        tests/test_vett_harness_smoke.py
git commit -m "feat(vett-harness): bootstrap package skeleton + Apache 2.0 attribution"
```

---

### Task 2: Vendor the upstream harness/ code

**Vendor compatibility seam (added after Task 2 first attempt surfaced three blockers):**

Three structural facts about upstream Harness-1 only become visible after the code is copied:

- **Upstream assumes the top-level package name `harness`** for absolute imports like `from harness.tools import X`. When vendored under a nested path (`soveryn.agents.vett.harness.vendor.*`), those imports fail. We provide a `sys.modules` alias so the upstream cross-references resolve to our vendored copy.
- **Upstream imports the optional Tinker (Thinking Machines) backend at module import time.** SOVERYN does not use the Tinker backend in phase 1 — we target llama-server via the OpenAI-compatible chat-completions path. To avoid pulling in the cloud SDK as a runtime dependency, we provide a **fail-closed stub** `tinker` module: imports succeed (so non-Tinker code paths stay importable), but any attempt to actually instantiate or call a Tinker class raises a clear `RuntimeError` directing the caller to `SoverynVettInferenceModel`. The stub must cover `tinker.SamplingClient`, `tinker.ServiceClient`, `tinker.TrainingClient`, AND a `tinker.types` submodule (with `SamplingParams`, `ModelInput`, `SampleResponse`) — because `agent.py` uses class-body annotations like `tinker.types.SamplingParams` evaluated at module load (no `from __future__ import annotations` upstream).
- **Upstream `agent.py` also imports `from datagen.search_dataset import SearchDataset, get_dataset` at module top.** `datagen` is a sibling upstream package SOVERYN does not vendor in phase 1 (it's training-data scaffolding, out of scope for the eval-only port). Same fail-closed stub treatment as `tinker`: `datagen.search_dataset` submodule with `SearchDataset` (failing class), `get_dataset` (failing callable), `DATASET_REGISTRY = {}`.

All three pieces live in **`soveryn/agents/vett/harness/_vendor_compat.py`** (one explicit function, `install_vendor_compat()`) and are invoked from the parent `__init__.py` BEFORE any vendor module is imported. `vendor/` files remain byte-identical to upstream. The NOTICE gains a paragraph documenting this runtime compatibility layer.

**Files:**
- Create: `soveryn/agents/vett/harness/_vendor_compat.py` (SOVERYN compatibility shim; NOT part of upstream)
- Create: `soveryn/agents/vett/harness/vendor/__init__.py`
- Create: `soveryn/agents/vett/harness/vendor/agent.py` (verbatim from upstream)
- Create: `soveryn/agents/vett/harness/vendor/config.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/prompts.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/rerank.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/tasks.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/tools.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/trajectory.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/ultra_core.py` (verbatim)
- Create: `soveryn/agents/vett/harness/vendor/utils.py` (verbatim)
- Modify: `soveryn/agents/vett/harness/__init__.py` (call `install_vendor_compat()` before any vendor import)
- Modify: `LICENSES/harness-1-NOTICE` (one-line addendum re: runtime compat layer)
- Modify: `tests/test_vett_harness_smoke.py` (extend)
- Modify: `pyproject.toml` (add the runtime deps actually needed, EXCEPT `tinker`)

- [ ] **Step 1: Write the failing test asserting vendor imports succeed**

Append to `tests/test_vett_harness_smoke.py`:
```python
def test_vendored_harness_importable():
    """All vendored upstream modules import cleanly from their new home."""
    expected = [
        "soveryn.agents.vett.harness.vendor.agent",
        "soveryn.agents.vett.harness.vendor.config",
        "soveryn.agents.vett.harness.vendor.prompts",
        "soveryn.agents.vett.harness.vendor.rerank",
        "soveryn.agents.vett.harness.vendor.tasks",
        "soveryn.agents.vett.harness.vendor.tools",
        "soveryn.agents.vett.harness.vendor.trajectory",
        "soveryn.agents.vett.harness.vendor.ultra_core",
        "soveryn.agents.vett.harness.vendor.utils",
    ]
    for module_path in expected:
        importlib.import_module(module_path)


def test_vendored_trajectory_class_present():
    """Trajectory is the Pydantic class the harness uses to carry state."""
    import uuid
    from soveryn.agents.vett.harness.vendor.trajectory import Trajectory
    t = Trajectory(actions_and_observations=[], id=uuid.uuid4())
    assert t.num_turns == 0
```

*(Note: upstream `Trajectory` Pydantic model requires `id: uuid.UUID`. Earlier draft of this test omitted that and was corrected during Task 2 execution.)*

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_smoke.py::test_vendored_harness_importable -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness.vendor.agent'`

- [ ] **Step 3: Fetch the upstream harness directory**

```bash
mkdir -p /tmp/harness-1-clone
cd /tmp/harness-1-clone
git clone --depth 1 https://github.com/pat-jj/harness-1.git
cd ~/soveryn_vnext

# Copy harness/ verbatim
rm soveryn/agents/vett/harness/vendor/.gitkeep
cp /tmp/harness-1-clone/harness-1/harness/*.py soveryn/agents/vett/harness/vendor/

# Verify what we got
ls soveryn/agents/vett/harness/vendor/
```

Expected output: `__init__.py agent.py config.py prompts.py rerank.py tasks.py tools.py trajectory.py ultra_core.py utils.py` (or similar — confirm full list matches Task 2's "Create" file list).

- [ ] **Step 4: Install vendored runtime dependencies (EXCEPT tinker)**

Inspect the top-level imports across vendored modules:
```bash
grep -h '^import\|^from' soveryn/agents/vett/harness/vendor/*.py | sort -u
```

Verify which deps are already present in the conda `soveryn` env:
```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pip list 2>/dev/null | grep -E "openai|anthropic|harmony|pydantic|rank-bm25|datasketch|structlog|tiktoken|tenacity|json-repair|baseten|chromadb"
```

For each external dep that's actually missing, add to `[project.dependencies]` in `pyproject.toml`. Then:
```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/pip install -e .
```

**DO NOT install `tinker`.** It's the Thinking Machines cloud-inference SDK; we use llama-server instead. The compat shim in Step 5 stubs it out.

- [ ] **Step 5: Inspect what vendor/agent.py and vendor/config.py import from tinker**

The compat shim needs to stub the EXACT symbols upstream uses. Bare `AttributeError`-on-access can break `from tinker import X` imports at module load. Inspect both files:
```bash
grep -n "tinker" soveryn/agents/vett/harness/vendor/agent.py soveryn/agents/vett/harness/vendor/config.py
```

Capture:
- Whether each uses `import tinker` (referenced later as `tinker.SamplingClient` etc.) OR `from tinker import X, Y`
- For `from tinker import X`-style: every symbol `X` that needs to exist as an attribute on the stub module
- For `tinker.<member>` access elsewhere in the vendored code: every attribute referenced

Document these in your report so the stub can be made airtight.

- [ ] **Step 6: Write the failing compat-shim test**

Append to `tests/test_vett_harness_smoke.py`:
```python
def test_vendor_compat_aliases_harness():
    """After install_vendor_compat(), `import harness` resolves to our vendored package."""
    from soveryn.agents.vett.harness import _vendor_compat
    _vendor_compat.install_vendor_compat()
    import harness as aliased  # noqa: E402  — alias is the whole point
    from soveryn.agents.vett.harness import vendor
    assert aliased is vendor, "harness alias did not resolve to vendor package"


def test_vendor_compat_tinker_stub_imports_succeed_but_fail_on_use():
    """tinker stub allows imports; raises clear RuntimeError when actually used."""
    import sys
    from soveryn.agents.vett.harness import _vendor_compat
    _vendor_compat.install_vendor_compat()
    import tinker  # noqa: E402
    # Any attribute exists (so `from tinker import X` succeeds) but using it fails.
    SamplingClient = tinker.SamplingClient  # accessor must not raise
    try:
        SamplingClient()
    except RuntimeError as e:
        assert "SOVERYN" in str(e) and "SoverynVettInferenceModel" in str(e), \
            f"stub error should direct caller to SoverynVettInferenceModel; got: {e}"
    else:
        raise AssertionError("Tinker stub did not raise when instantiated")
```

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_vett_harness_smoke.py::test_vendor_compat_aliases_harness -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness._vendor_compat'`

- [ ] **Step 7: Implement `_vendor_compat.py`**

Create `soveryn/agents/vett/harness/_vendor_compat.py`:
```python
"""Runtime compatibility shim for the vendored Harness-1 upstream.

This file is SOVERYN-side; it is NOT part of upstream pat-jj/harness-1.

Two compatibility issues are addressed at import time, BEFORE any
`soveryn.agents.vett.harness.vendor.*` module is imported:

1. **`harness` alias.** Upstream uses absolute imports like
   `from harness.tools import X`. When vendored under a nested package
   path, those imports fail. We register `sys.modules['harness']` so
   it resolves to our vendored package.

2. **`tinker` stub.** Upstream's `agent.py` and `config.py` import the
   Thinking Machines `tinker` SDK at module top. SOVERYN does not use
   the Tinker backend in phase 1 (we use llama-server via
   `SoverynVettInferenceModel`). Rather than pull in the cloud SDK,
   we register a stub `tinker` module that satisfies the imports but
   raises a clear `RuntimeError` on actual use, directing callers to
   the supported inference path.

Call `install_vendor_compat()` from the parent package's `__init__.py`
before any vendor import takes place.
"""
from __future__ import annotations
import sys
import types
from typing import Any


_TINKER_FAILURE_MSG = (
    "Tinker backend is not available in the SOVERYN Harness-1 port. "
    "Use SoverynVettInferenceModel (chat-completions against the "
    "llama-server router at :8090) instead. See "
    "docs/superpowers/specs/2026-06-11-vett-harness-port-design.md."
)


def _make_failing_class(name: str) -> type:
    """Build a stub class that raises on instantiation with a clear message."""
    def _init(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"{name}: {_TINKER_FAILURE_MSG}")
    return type(name, (), {"__init__": _init})


def _build_tinker_stub_module() -> types.ModuleType:
    """Construct a fail-closed stub module that satisfies upstream's imports.

    The symbol set here MUST cover every name upstream's vendored agent.py
    and config.py import from tinker. Inspect those files (Task 2 Step 5)
    and add any missing names to this list before depending on the stub.
    """
    stub = types.ModuleType("tinker")
    # Known classes upstream imports/uses (per Task 2 Step 5 inspection):
    # Add to this list any additional symbols inspection surfaced.
    for cls_name in ("SamplingClient", "ServiceClient", "TrainingClient"):
        setattr(stub, cls_name, _make_failing_class(cls_name))
    # Fallback for any attribute access not enumerated above: return a
    # failing class on demand so `from tinker import X` patterns succeed.
    def _dynamic_attr(name: str) -> type:
        return _make_failing_class(name)
    stub.__getattr__ = _dynamic_attr  # type: ignore[method-assign]
    return stub


def install_vendor_compat() -> None:
    """Install harness alias and tinker stub in sys.modules.

    Idempotent: safe to call multiple times. Must be called BEFORE any
    `soveryn.agents.vett.harness.vendor.*` module is imported.
    """
    # 1. harness alias → our vendored package.
    if "harness" not in sys.modules:
        # Import lazily to avoid touching vendor at module-load of this file.
        from soveryn.agents.vett.harness import vendor as _vendor_pkg
        sys.modules["harness"] = _vendor_pkg

    # 2. tinker stub.
    if "tinker" not in sys.modules:
        sys.modules["tinker"] = _build_tinker_stub_module()
```

- [ ] **Step 8: Wire `install_vendor_compat()` into parent `__init__.py`**

Modify `soveryn/agents/vett/harness/__init__.py` so it installs the compat shim before anything else can import vendor modules:
```python
"""SOVERYN Vett — Harness-1 port (phase 1, eval-only).

Vendored harness code lives under `vendor/` with its upstream
Apache 2.0 LICENSE and NOTICE preserved at `LICENSES/`. SOVERYN
shims (inference model, lattice tool handlers, CLI runner) live
alongside this __init__.

This package is NOT wired into Vett's normal task surface in
phase 1. See `docs/superpowers/specs/2026-06-11-vett-harness-port-design.md`.

Runtime compatibility:
    Upstream vendored files assume the top-level package name `harness`
    and import the Tinker SDK at module load. SOVERYN aliases `harness`
    to our vendored package and stubs `tinker` (fail-closed) via the
    explicit compatibility shim in `_vendor_compat.py`, installed below
    before any vendor module is touched.
"""
from soveryn.agents.vett.harness._vendor_compat import install_vendor_compat

install_vendor_compat()
```

- [ ] **Step 9: Add NOTICE addendum**

Append to `LICENSES/harness-1-NOTICE` (as a new paragraph after the existing modifications list):
```

Runtime compatibility layer (SOVERYN, outside `vendor/`):
SOVERYN provides runtime aliases/stubs at module import time so that the
upstream vendored modules can be imported under SOVERYN's nested package
path without modification. Specifically:
  - `sys.modules['harness']` is aliased to the vendored package so
    upstream's absolute imports (`from harness.X import Y`) resolve.
  - A fail-closed stub `tinker` module is registered so that vendored
    modules importing the Thinking Machines SDK at module top can load
    without the SDK being installed; actual use of any Tinker class
    raises `RuntimeError` and directs the caller to the supported
    `SoverynVettInferenceModel` inference path.
Implementation: `soveryn/agents/vett/harness/_vendor_compat.py`.
Vendored upstream files under `vendor/` are unmodified.
```

- [ ] **Step 10: Run the full smoke test suite**

Run: `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_vett_harness_smoke.py -v`
Expected: 5 passed (test_package_importable, test_vendored_harness_importable, test_vendored_trajectory_class_present, test_vendor_compat_aliases_harness, test_vendor_compat_tinker_stub_imports_succeed_but_fail_on_use)

If a vendored module still fails to import due to a tinker attribute the stub doesn't cover, add the missing name to the `_TINKER_STUB_CLASSES`-equivalent enumeration in `_vendor_compat.py` and re-run. The dynamic `__getattr__` fallback should catch most cases.

- [ ] **Step 11: Commit**

```bash
git add soveryn/agents/vett/harness/vendor/*.py \
        tests/test_vett_harness_smoke.py \
        pyproject.toml
git rm soveryn/agents/vett/harness/vendor/.gitkeep
git commit -m "feat(vett-harness): vendor upstream harness/ at pat-jj/harness-1 main"
```

Capture the upstream commit SHA in the commit body for traceability:
```bash
cd /tmp/harness-1-clone/harness-1
UPSTREAM_SHA=$(git rev-parse HEAD)
cd ~/soveryn_vnext
git commit --amend -m "feat(vett-harness): vendor upstream harness/ at pat-jj/harness-1 main

Upstream SHA: $UPSTREAM_SHA
Vendored verbatim — no SOVERYN modifications under vendor/."
```

---

### Task 3: Verify Vett accepts harness chat-completions message shape (blocker check)

**Files:**
- Create: `soveryn/agents/vett/harness/_format_probe.py`
- Test: `tests/test_vett_harness_format_compat.py`

This task is a **format-compatibility blocker check**. The vendored harness produces chat-completions messages tuned to gpt-oss-20b's chat template. Vett (Qwen3.6-27B) has a different chat template. We need to verify Vett can accept and respond meaningfully to the harness's message shape *before* implementing the inference model subclass. If Vett rejects or produces garbage, this is a phase 1 blocker that escalates to Jon.

- [ ] **Step 1: Write the failing test that probes message-format compat**

Create `tests/test_vett_harness_format_compat.py`:
```python
"""Phase 1 blocker check: does Vett accept a harness-shaped message?

The vendored harness emits chat-completions messages tuned to
gpt-oss-20b. This test confirms our Vett (Qwen3.6-27B at the
llama-server router on :8090) accepts that shape and returns a
non-empty, non-error response. If this test fails, the entire
plan is blocked until the format question is resolved.

The test is GATED on the router being up; it is marked with
`@pytest.mark.integration` and skipped by default in unit runs.
"""
from __future__ import annotations
import os
import pytest

from soveryn.agents.vett.harness._format_probe import probe_vett_format_compat


@pytest.mark.integration
def test_vett_accepts_harness_message_shape():
    """Vett returns a non-empty, non-error response to a harness-shape probe."""
    router_url = os.environ.get("SOVERYN_ROUTER_URL", "http://127.0.0.1:8090")
    result = probe_vett_format_compat(router_url=router_url, model="vett-scotty")
    assert result.ok, f"Vett rejected harness message shape: {result.reason}"
    assert result.response_text, "Vett returned empty content"
    assert len(result.response_text) > 5, f"Vett response suspiciously short: {result.response_text!r}"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_format_compat.py -v --run-integration` (assuming pytest is configured with an integration marker)

If the project doesn't yet have an integration marker, configure it. Add to `pyproject.toml`:
```toml
[tool.pytest.ini_options]
markers = [
    "integration: tests that hit live services (router, lattice, etc.); opt-in with --run-integration",
]
```

And in `conftest.py` (create if absent):
```python
def pytest_addoption(parser):
    parser.addoption("--run-integration", action="store_true", default=False,
                     help="Run tests marked @pytest.mark.integration (hit live router etc.)")

def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-integration"):
        return
    skip_integration = __import__("pytest").mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
```

Expected from initial run: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness._format_probe'`

- [ ] **Step 3: Implement the format probe**

Create `soveryn/agents/vett/harness/_format_probe.py`:
```python
"""Phase 1 blocker probe: send a harness-shape message to Vett.

This isolates the format-compat question from the full inference
model implementation. If it fails, we know it before writing more
SOVERYN-side glue code.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

import httpx


@dataclass
class FormatProbeResult:
    ok: bool
    response_text: str
    reason: Optional[str] = None


# A reduced harness-shape message: system prompt with tool-instructions
# echo + a user query. This mirrors the simplest case the harness can
# emit. If Vett can't handle this, she can't handle the real thing.
_HARNESS_SHAPE_SYSTEM = (
    "You are a research subagent. You have access to tools to search a "
    "corpus, read documents, and verify claims. Plan your research before "
    "acting. Reply briefly to confirm you understand the task."
)
_HARNESS_SHAPE_USER = (
    "Confirm by replying with exactly the phrase: HARNESS_OK"
)


def probe_vett_format_compat(*, router_url: str, model: str) -> FormatProbeResult:
    """Send a harness-shape message; assert response is non-empty + non-error."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _HARNESS_SHAPE_SYSTEM},
            {"role": "user", "content": _HARNESS_SHAPE_USER},
        ],
        # 256, not 32 — Vett's preset is `reasoning = on` + `reasoning-format = deepseek`,
        # which routes hidden chain-of-thought into `reasoning_content` BEFORE any
        # visible `content` is emitted. A small budget gets entirely consumed by
        # thinking, leaving content="" and finish_reason="length" even when the
        # format is accepted at parse + dispatch level. Surfaced in Task 3 execution.
        "max_tokens": 256,
        "temperature": 0.0,
    }
    try:
        resp = httpx.post(f"{router_url}/v1/chat/completions", json=payload, timeout=30.0)
    except httpx.HTTPError as e:
        return FormatProbeResult(ok=False, response_text="", reason=f"HTTP error: {e}")
    if resp.status_code != 200:
        return FormatProbeResult(ok=False, response_text="", reason=f"status={resp.status_code} body={resp.text[:200]}")
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        return FormatProbeResult(ok=False, response_text="", reason=f"unexpected response shape: {e}, body={resp.text[:200]}")
    return FormatProbeResult(ok=True, response_text=content.strip())
```

- [ ] **Step 4: Run the test (against live router) to verify it passes**

Run: `pytest tests/test_vett_harness_format_compat.py -v --run-integration`
Expected: PASS, with Vett returning something containing "HARNESS_OK" or close to it.

**If FAIL:** Capture the `reason` and the body fragment. This is a phase 1 BLOCKER. Open a task labeled `vett-harness-blocker` and escalate to Jon before continuing. The likely fixes are: (a) adjust system prompt to match Vett's expected role markers, (b) use `/v1/completions` instead of `/v1/chat/completions`, (c) verify llama-server's `--jinja` chat-template handling is wired. None of those should be attempted as a hidden fix inside this task.

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/vett/harness/_format_probe.py \
        tests/test_vett_harness_format_compat.py \
        pyproject.toml \
        conftest.py
git commit -m "feat(vett-harness): format-compat blocker probe — Vett accepts harness chat shape"
```

---

### Task 4: SoverynVettInferenceModel — chat-completions client targeting llama-server

**Files:**
- Create: `soveryn/agents/vett/harness/llm_client.py`
- Test: `tests/test_vett_harness_llm_client.py`

The vendored harness's `OpenAIAgentInferenceModel` takes an `openai_client: OpenAI` instance and a `model: str`. Our subclass configures the OpenAI client to point at llama-server's OpenAI-compat endpoint at `:8090` and pins `model="vett-scotty"`. No other behavior changes; we inherit the entire `__call__(context) -> Optional[Action]` flow from upstream.

- [ ] **Step 1: Write the failing test asserting the client is constructible against our router**

Create `tests/test_vett_harness_llm_client.py`:
```python
"""SoverynVettInferenceModel — chat-completions client for Vett."""
from __future__ import annotations
import os
import pytest

from soveryn.agents.vett.harness.llm_client import SoverynVettInferenceModel


def test_inference_model_constructs_with_defaults():
    """Constructor produces a working OpenAI-compat client without errors."""
    model = SoverynVettInferenceModel()
    assert model.model == "vett-scotty"
    assert model.openai_client.base_url.host in ("127.0.0.1", "localhost")
    assert "8090" in str(model.openai_client.base_url)


def test_inference_model_constructor_accepts_overrides():
    """Constructor allows the router URL and model name to be overridden."""
    model = SoverynVettInferenceModel(
        router_url="http://10.0.0.5:9999",
        model_name="custom-alias",
    )
    assert model.model == "custom-alias"
    assert "10.0.0.5:9999" in str(model.openai_client.base_url)


@pytest.mark.integration
def test_inference_model_round_trips_against_live_router():
    """Construct, call against live router, get a non-None Action back."""
    # Actual vendored shape (per Task 4 inspection):
    #   InferenceContext(trajectory, toolset, max_tokens=None,
    #                    previous_response_id=None, skip_response_id_update=False)
    # - toolset is REQUIRED (use empty ToolSet(), not None)
    # - field name is `max_tokens`, not `max_completion_tokens`
    # - Trajectory requires id: uuid.UUID
    import uuid
    from soveryn.agents.vett.harness.vendor.agent import InferenceContext, ToolSet
    from soveryn.agents.vett.harness.vendor.trajectory import Trajectory
    model = SoverynVettInferenceModel()
    ctx = InferenceContext(
        trajectory=Trajectory(actions_and_observations=[], id=uuid.uuid4()),
        toolset=ToolSet(),
        max_tokens=64,
    )
    action = model(ctx)
    assert action is not None, "model returned None — chat-completions path is broken"
```

- [ ] **Step 2: Run the unit tests to verify they fail (integration test will be skipped without --run-integration)**

Run: `pytest tests/test_vett_harness_llm_client.py::test_inference_model_constructs_with_defaults -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness.llm_client'`

- [ ] **Step 3: Implement the inference model subclass**

Create `soveryn/agents/vett/harness/llm_client.py`:
```python
"""SOVERYN inference-model shim for the vendored harness.

Subclasses the vendored `OpenAIAgentInferenceModel` and points its
OpenAI client at our llama-server router (OpenAI-compat layer). No
behavioral changes — we inherit prompt assembly, tool-call parsing,
and the __call__ flow from upstream.
"""
from __future__ import annotations
from typing import Optional

from openai import OpenAI

from soveryn.agents.vett.harness.vendor.agent import OpenAIAgentInferenceModel


_DEFAULT_ROUTER_URL = "http://127.0.0.1:8090"
_DEFAULT_MODEL = "vett-scotty"


class SoverynVettInferenceModel(OpenAIAgentInferenceModel):
    """Vett's LLM client for the vendored harness.

    Targets the llama-server router at :8090, model=vett-scotty.
    Uses the chat-completions API path; avoids token-level coupling
    with gpt-oss-20b's tokenizer.
    """

    def __init__(
        self,
        *,
        router_url: str = _DEFAULT_ROUTER_URL,
        model_name: str = _DEFAULT_MODEL,
        max_output_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> None:
        # llama-server's OpenAI-compat layer doesn't enforce API keys;
        # use a placeholder so the OpenAI SDK doesn't raise.
        client = OpenAI(base_url=f"{router_url}/v1", api_key="not-used")
        super().__init__(
            openai_client=client,
            model=model_name,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            api_style="chat_completions",  # not "responses" — Vett serves chat-completions
        )
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `pytest tests/test_vett_harness_llm_client.py -v` (no `--run-integration` flag — only unit tests run)
Expected: 2 passed, 1 skipped (the integration test)

- [ ] **Step 5: Run the integration test against the live router**

Run: `pytest tests/test_vett_harness_llm_client.py::test_inference_model_round_trips_against_live_router -v --run-integration`
Expected: PASS, with the model returning a non-None Action object.

**If FAIL with `unsupported api_style` or similar:** the vendored agent.py may not expose `api_style="chat_completions"` literally. Inspect `soveryn/agents/vett/harness/vendor/agent.py` for the actual constant name (it could be `"chat"` or an enum). Replace the literal in `llm_client.py:__init__` and re-run.

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/vett/harness/llm_client.py \
        tests/test_vett_harness_llm_client.py
git commit -m "feat(vett-harness): SoverynVettInferenceModel — chat-completions client for :8090"
```

---

### Task 5: Lattice + embed entrypoint discovery (BLOCKER)

**Files:**
- Create: `docs/notes/2026-06-XX-lattice-discovery.md` (date set at run time)

This task is a **discovery blocker**, same strength as Task 3. The next tasks (6 lattice handlers, 8 `_build_agent` wiring) assume specific lattice API shapes and import paths. If the actual SOVERYN code differs from the plan's assumptions, the engineer will write a fake-compatible adapter that breaks against the live lattice. This task makes the discovery explicit and captures findings to a notes file that downstream tasks reference.

No code yet — this is a `grep` and `read` task that produces a notes file.

- [ ] **Step 1: Find the lattice module and its retrieval class**

Run:
```bash
cd ~/soveryn_vnext
find soveryn/ -type f -name "*.py" | xargs grep -l "class.*Lattice\|class.*Store" | grep -i lattice
```

Open each result and identify:
- The class that owns vector retrieval (likely `LatticeStore`, `Lattice`, or similar)
- Its constructor signature: what arguments does `__init__` take? (DB path? Embedding function?)
- Its retrieval method: what's the actual name? (`find_nodes_by_embedding`, `find_by_embedding`, `search`, `query`, etc.) What kwargs does it take?
- Its single-node lookup method: what's the actual name? (`get_node`, `get`, `lookup`, etc.)
- The Node/Result type returned: is it a Pydantic model, dataclass, or plain dict? What attributes does it expose (id, content, metadata, score)?

- [ ] **Step 2: Find the embedding entrypoint**

Run:
```bash
grep -rn "def embed_text\|def embed(\|class.*Embed\|nomic-embed" soveryn/ | head -10
```

Identify:
- The function or class method that takes a string and returns a vector
- Its full import path
- Whether it makes an HTTP call to the embeddings model at `:8090 model=embeddings` (likely) or runs locally
- Whether it's synchronous or async

- [ ] **Step 3: Find the lattice DB path resolution**

The harness handlers need a live lattice instance. Find how SOVERYN constructs one in normal use:
```bash
grep -rn "Lattice(\|LatticeStore(\|lattice_path" soveryn/ | grep -v test | head -10
```

Identify:
- Where is the lattice instantiated in normal vnext startup?
- Is there a singleton `lattice` exposed somewhere we can import?
- Or does each caller construct its own with a path from config?
- If a path is configured, where does it come from? (env var, app config, default)

- [ ] **Step 4: Write the discovery notes**

Create `docs/notes/<YYYY-MM-DD>-lattice-discovery.md` (use today's date) with the structure:
```markdown
# Lattice + Embed Discovery — Vett Harness Phase 1

## Lattice class

- Class: `soveryn.memory.lattice.<ActualClassName>`
- Constructor: `<actual signature>`
- Retrieval method: `<actual_method_name>(<kwargs>) -> <return type>`
- Single-node lookup: `<actual_method_name>(<kwargs>) -> <return type>`
- Node/Result type: `<actual type>` exposing `<attributes>`

## Embedding entrypoint

- Function: `<actual import path>`
- Signature: `<actual signature>`
- Sync/async: <sync|async>
- Backend: <local|HTTP to :8090>

## Lattice instantiation

- Normal vnext path: `<how Aetheria's recall constructs lattice>` (file:line)
- Singleton available?: <yes|no>
- If no singleton, config source: `<env var | config key | default>`

## Implications for Task 6 (handlers) and Task 8 (_build_agent)

[List specific code changes vs the plan's example signatures.]
```

- [ ] **Step 5: Decide pass/blocker**

If any of the following are true, this is a **blocker** — escalate to Jon before continuing to Task 6:
- The retrieval method's kwargs / return shape are incompatible with the harness's needs (e.g., requires a Document instead of returning text)
- No embedding entrypoint exists, OR it returns something other than a float vector
- The lattice has no clear instantiation path that handler code can call (no singleton, no config-driven constructor)

If discovery passes, commit the notes and proceed to Task 6.

- [ ] **Step 6: Commit**

```bash
git add docs/notes/<YYYY-MM-DD>-lattice-discovery.md
git commit -m "docs(vett-harness): lattice + embed discovery notes for phase 1 (Task 5 blocker check)"
```

---

### Task 6: Lattice tool handlers (search_corpus / fan_out_search / read_doc)

**Files:**
- Create: `soveryn/agents/vett/harness/lattice_tools.py`
- Test: `tests/test_vett_harness_lattice_tools.py`

The harness Agent invokes search and read tools at runtime; we register handlers that resolve those calls against the lattice. Read-through only — no writes to the lattice during phase 1. Results are formatted as `# DOCUMENT ID: <id>\n<text>` strings, matching the format `parse_doc_ids_from_observation` expects (per inspection of `vendor/ultra_core.py`).

**Before writing handler code, read the Task 5 discovery notes** at `docs/notes/<YYYY-MM-DD>-lattice-discovery.md`. The example signatures in this task (`find_nodes_by_embedding(query_embedding=..., top_k=...)`, `get_node(node_id)`) are PLACEHOLDERS. Replace them with the actual method names and kwargs captured in Task 5's notes file before running tests. The fake lattice in the unit tests is fine as-is (it exercises the handler's wrapping logic, not the real lattice's API).

- [ ] **Step 1: Read the vendored lattice/search interface to confirm exact tool-handler signatures**

Read `soveryn/agents/vett/harness/vendor/tools.py` and `soveryn/agents/vett/harness/vendor/ultra_core.py` and note:
- Exact `ToolSchema` names (`SEARCH_CORPUS_SCHEMA`, `FAN_OUT_SEARCH_SCHEMA`, etc.)
- The `Toolset` registration API
- The handler signature each tool expects (sync vs async, return type, exception contract)

Document findings as a comment block at the top of `lattice_tools.py`. If the signature differs from this plan's assumed `(query: str, top_k: int) -> List[Dict[str, str]]`, adjust the code blocks below to match.

- [ ] **Step 2: Write the failing tests asserting handler behavior**

Create `tests/test_vett_harness_lattice_tools.py`:
```python
"""Lattice tool handlers — read-through, no writes."""
from __future__ import annotations
from typing import Iterable
import pytest

from soveryn.agents.vett.harness.lattice_tools import (
    LatticeToolHandlers,
    format_search_observation,
)


class _FakeLatticeNode:
    def __init__(self, node_id: str, content: str, score: float = 1.0):
        self.id = node_id
        self.content = content
        self.score = score


class _FakeLattice:
    """Minimal lattice fake exposing the methods our handlers call."""
    def __init__(self, nodes: Iterable[_FakeLatticeNode]):
        self._nodes = list(nodes)

    def find_nodes_by_embedding(self, *, query_embedding, top_k: int):
        return self._nodes[:top_k]

    def get_node(self, node_id: str):
        for n in self._nodes:
            if n.id == node_id:
                return n
        return None


class _FakeEmbed:
    def __call__(self, text: str):
        return [0.0] * 384  # nomic-embed-text-v1.5 dim


def test_search_corpus_returns_formatted_observation():
    """search_corpus returns # DOCUMENT ID:... formatted string per upstream parse expectations."""
    fake = _FakeLattice([_FakeLatticeNode("n-1", "Alpha is the first letter."),
                         _FakeLatticeNode("n-2", "Beta is the second letter.")])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_FakeEmbed())
    result = h.search_corpus(query="what is alpha", top_k=2)
    assert "# DOCUMENT ID: n-1" in result
    assert "Alpha is the first letter." in result
    assert "# DOCUMENT ID: n-2" in result


def test_fan_out_search_dispatches_to_multiple_queries():
    """fan_out_search calls search_corpus for each query and concatenates."""
    fake = _FakeLattice([_FakeLatticeNode("n-1", "Topic A"), _FakeLatticeNode("n-2", "Topic B")])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_FakeEmbed())
    result = h.fan_out_search(queries=["query1", "query2"], top_k_per_query=2)
    assert result.count("# DOCUMENT ID:") >= 2


def test_read_doc_returns_full_text_for_known_id():
    """read_doc returns full text for an existing node id."""
    fake = _FakeLattice([_FakeLatticeNode("n-1", "This is the full text of node 1.")])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_FakeEmbed())
    result = h.read_doc(doc_id="n-1")
    assert "This is the full text of node 1." in result


def test_read_doc_returns_not_found_for_missing_id():
    """read_doc returns a 'not found' observation rather than raising."""
    fake = _FakeLattice([])
    h = LatticeToolHandlers(lattice=fake, embed_fn=_FakeEmbed())
    result = h.read_doc(doc_id="nonexistent")
    assert "not found" in result.lower()


def test_format_observation_uses_harness_canonical_marker():
    """Format helper produces strings parseable by the vendored parse_doc_ids_from_observation."""
    obs = format_search_observation([("doc-1", "Text one."), ("doc-2", "Text two.")])
    assert "# DOCUMENT ID: doc-1" in obs
    assert "# DOCUMENT ID: doc-2" in obs

    # Confirm the vendored parser recovers the IDs we put in.
    from soveryn.agents.vett.harness.vendor.ultra_core import parse_doc_ids_from_observation
    parsed = parse_doc_ids_from_observation(obs)
    assert "doc-1" in parsed
    assert "doc-2" in parsed
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_vett_harness_lattice_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'soveryn.agents.vett.harness.lattice_tools'`

- [ ] **Step 4: Implement the handlers**

Create `soveryn/agents/vett/harness/lattice_tools.py`:
```python
"""Lattice-backed tool handlers for the vendored harness (read-through only).

The vendored harness dispatches tools like fan_out_search and
search_corpus to handler callables. This module provides those handlers
backed by SOVERYN's Synapse lattice. All handlers are pure read — no
writes to the lattice during phase 1.

Observation strings are formatted with the canonical
`# DOCUMENT ID: <id>\\n<text>` marker so the vendored
parse_doc_ids_from_observation can recover IDs downstream.

Signature audit:
    Verify against soveryn/agents/vett/harness/vendor/tools.py before
    wiring into a Toolset (Task 6). If the harness expects async
    handlers, wrap each method in `async def`.
"""
from __future__ import annotations
from typing import Callable, Iterable, List, Sequence, Tuple


DEFAULT_TOP_K = 5
DEFAULT_FAN_OUT_K = 3


def format_search_observation(items: Sequence[Tuple[str, str]]) -> str:
    """Render a list of (doc_id, text) as the harness-canonical marker format."""
    blocks = [f"# DOCUMENT ID: {doc_id}\n{text}".rstrip() for doc_id, text in items]
    return "\n\n".join(blocks)


class LatticeToolHandlers:
    """Tool handlers backed by SOVERYN's lattice.

    Parameters
    ----------
    lattice
        An object exposing:
          - find_nodes_by_embedding(*, query_embedding, top_k) -> Iterable[Node]
          - get_node(node_id) -> Optional[Node]
        Both Node-like objects must expose `.id` (str) and `.content` (str).
    embed_fn
        Callable returning a vector for a string query. In production,
        wraps the embeddings model at port 8090 model=embeddings.
    """
    def __init__(self, *, lattice, embed_fn: Callable[[str], Sequence[float]]):
        self._lattice = lattice
        self._embed = embed_fn

    def search_corpus(self, *, query: str, top_k: int = DEFAULT_TOP_K) -> str:
        """Run a single query against the lattice, return harness-formatted result."""
        emb = self._embed(query)
        nodes = self._lattice.find_nodes_by_embedding(query_embedding=emb, top_k=top_k)
        items = [(n.id, n.content) for n in nodes]
        return format_search_observation(items)

    def fan_out_search(
        self,
        *,
        queries: Iterable[str],
        top_k_per_query: int = DEFAULT_FAN_OUT_K,
    ) -> str:
        """Run multiple queries in parallel-ish (sync loop), concatenate observations."""
        chunks: List[str] = []
        for q in queries:
            chunks.append(self.search_corpus(query=q, top_k=top_k_per_query))
        return "\n\n".join(chunks)

    def read_doc(self, *, doc_id: str) -> str:
        """Return the full content of a node by id, or a not-found observation."""
        node = self._lattice.get_node(doc_id)
        if node is None:
            return f"# DOCUMENT ID: {doc_id}\nDocument not found."
        return format_search_observation([(node.id, node.content)])
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_vett_harness_lattice_tools.py -v`
Expected: 5 passed.

If `parse_doc_ids_from_observation` import fails (different name in vendored ultra_core.py), inspect the file and adjust the import in the test.

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/vett/harness/lattice_tools.py \
        tests/test_vett_harness_lattice_tools.py
git commit -m "feat(vett-harness): lattice tool handlers (read-through, format-compatible)"
```

---

### Task 7: CLI runner skeleton (argparse, no harness yet)

**Files:**
- Create: `soveryn/agents/vett/harness/run_eval.py`
- Create: `soveryn/agents/vett/harness/eval_tasks/__init__.py`
- Test: `tests/test_vett_harness_run_eval.py`

- [ ] **Step 1: Write the failing test asserting CLI parses args**

Create `tests/test_vett_harness_run_eval.py`:
```python
"""run_eval CLI runner — argparse + task loading + JSON output."""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

from soveryn.agents.vett.harness import run_eval


def test_parse_args_minimal():
    """CLI accepts --task and --output args."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json"])
    assert args.task == "smoke"
    assert args.output == "/tmp/out.json"


def test_parse_args_has_turn_budget_default():
    """Default turn budget is 20 (per spec)."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json"])
    assert args.max_turns == 20


def test_parse_args_accepts_turn_budget_override():
    """--max-turns flag overrides the default."""
    args = run_eval.parse_args(["--task", "smoke", "--output", "/tmp/out.json", "--max-turns", "5"])
    assert args.max_turns == 5


def test_load_task_returns_task_object_for_known_task():
    """A built-in task is loadable by name."""
    task = run_eval.load_task("smoke")
    assert task.name == "smoke"
    assert task.query
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_run_eval.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the skeleton**

Create `soveryn/agents/vett/harness/run_eval.py`:
```python
"""Standalone CLI runner for the Vett harness eval.

Usage:
    python -m soveryn.agents.vett.harness.run_eval --task <name> --output <path.json>

Loads a SOVERYN eval task by name, runs it through the vendored harness
Agent backed by SoverynVettInferenceModel + LatticeToolHandlers, enforces
a turn budget, persists the resulting Trajectory to JSON, and emits
failure-mode telemetry on stderr.

Phase 1: not wired into Vett's normal task surface. CLI-only.
"""
from __future__ import annotations
import argparse
import sys
from dataclasses import dataclass
from typing import List

from soveryn.agents.vett.harness.eval_tasks import get_task, EvalTask


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Run a SOVERYN eval task through the Vett harness port.",
    )
    parser.add_argument("--task", required=True, help="Name of eval task to load.")
    parser.add_argument("--output", required=True, help="Path to write Trajectory JSON.")
    parser.add_argument("--max-turns", type=int, default=20,
                        help="Max harness turns before forced stop (default 20).")
    parser.add_argument("--router-url", default="http://127.0.0.1:8090",
                        help="llama-server router URL (default :8090).")
    parser.add_argument("--model", default="vett-scotty",
                        help="Router model alias (default vett-scotty).")
    return parser.parse_args(argv)


def load_task(name: str) -> EvalTask:
    """Resolve a task by name from the eval_tasks registry."""
    return get_task(name)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)
    # Task 8 wires the actual harness Agent in; for now, exit clean.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `soveryn/agents/vett/harness/eval_tasks/__init__.py`:
```python
"""SOVERYN eval-task registry.

Tasks are simple dataclasses with a name and a query. Task 11 (the
cross_source_link eval task) populates the registry with a real
SOVERYN-representative task. For now, a 'smoke' task is registered so
the CLI skeleton has something to load.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EvalTask:
    name: str
    query: str
    expected_evidence_ids: tuple = ()  # for scoring; populated by Task 11 (cross_source_link)


_REGISTRY: Dict[str, EvalTask] = {
    "smoke": EvalTask(
        name="smoke",
        query="reply with: SMOKE_OK",
    ),
}


def get_task(name: str) -> EvalTask:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown eval task: {name!r}. Registered: {list(_REGISTRY)}")
    return _REGISTRY[name]


def register_task(task: EvalTask) -> None:
    _REGISTRY[task.name] = task
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_vett_harness_run_eval.py -v`
Expected: 4 passed.

- [ ] **Step 5: Smoke-run the CLI to confirm it loads the smoke task**

Run:
```bash
python -m soveryn.agents.vett.harness.run_eval --task smoke --output /tmp/out.json
```
Expected on stderr: `loaded task: smoke`
Expected exit code: 0

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/vett/harness/run_eval.py \
        soveryn/agents/vett/harness/eval_tasks/__init__.py \
        tests/test_vett_harness_run_eval.py
git commit -m "feat(vett-harness): CLI runner skeleton with task registry (no harness yet)"
```

---

### Task 8: Wire harness Agent into the CLI runner

**Files:**
- Modify: `soveryn/agents/vett/harness/run_eval.py`
- Test: `tests/test_vett_harness_run_eval.py` (extend)

This task replaces the skeleton's no-op main with a real run that constructs the harness `Agent`, runs it against the loaded task, and returns the resulting Trajectory. Turn budget enforcement comes in Task 9 — for now, we accept whatever upstream-default budget the harness imposes.

- [ ] **Step 1: Write the failing test asserting `main` runs end-to-end with a fake harness**

Append to `tests/test_vett_harness_run_eval.py`:
```python
import json
import tempfile
from unittest import mock
from pathlib import Path


def test_main_persists_trajectory_json_with_fake_harness(monkeypatch):
    """main() runs the harness against a task and writes a JSON file."""
    # Stub the harness Agent so we don't need a live router for the unit test.
    fake_trajectory_dict = {"actions_and_observations": [], "id": "fake-uuid"}

    class _FakeTrajectory:
        def model_dump(self):
            return fake_trajectory_dict

    class _FakeAgent:
        def __init__(self, *args, **kwargs): pass
        def run(self, task):
            return _FakeTrajectory()

    monkeypatch.setattr(
        "soveryn.agents.vett.harness.run_eval._build_agent",
        lambda args: _FakeAgent(),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        rc = run_eval.main(["--task", "smoke", "--output", str(out_path)])
        assert rc == 0
        assert out_path.exists()
        loaded = json.loads(out_path.read_text())
        assert loaded["id"] == "fake-uuid"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_run_eval.py::test_main_persists_trajectory_json_with_fake_harness -v`
Expected: FAIL — `main` doesn't write a JSON file yet.

- [ ] **Step 3: Wire the agent + persistence**

Modify `soveryn/agents/vett/harness/run_eval.py`:
```python
"""Standalone CLI runner for the Vett harness eval.

Usage:
    python -m soveryn.agents.vett.harness.run_eval --task <name> --output <path.json>

Loads a SOVERYN eval task by name, runs it through the vendored harness
Agent backed by SoverynVettInferenceModel + LatticeToolHandlers, enforces
a turn budget, persists the resulting Trajectory to JSON, and emits
failure-mode telemetry on stderr.

Phase 1: not wired into Vett's normal task surface. CLI-only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

from soveryn.agents.vett.harness.eval_tasks import get_task, EvalTask
from soveryn.agents.vett.harness.llm_client import SoverynVettInferenceModel
from soveryn.agents.vett.harness.lattice_tools import LatticeToolHandlers


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_eval",
        description="Run a SOVERYN eval task through the Vett harness port.",
    )
    parser.add_argument("--task", required=True, help="Name of eval task to load.")
    parser.add_argument("--output", required=True, help="Path to write Trajectory JSON.")
    parser.add_argument("--max-turns", type=int, default=20,
                        help="Max harness turns before forced stop (default 20).")
    parser.add_argument("--router-url", default="http://127.0.0.1:8090",
                        help="llama-server router URL (default :8090).")
    parser.add_argument("--model", default="vett-scotty",
                        help="Router model alias (default vett-scotty).")
    return parser.parse_args(argv)


def load_task(name: str) -> EvalTask:
    return get_task(name)


def _build_agent(args: argparse.Namespace) -> Any:
    """Construct the vendored harness Agent wired with SOVERYN shims.

    Imported lazily so the lattice/embed connection isn't required for
    unit tests that monkeypatch this function.

    Lattice + embed import paths and instantiation must come from the
    Task 5 discovery notes at `docs/notes/<YYYY-MM-DD>-lattice-discovery.md`.
    Replace the example imports below with the actual paths captured
    there before running tests against the live lattice. The structure
    is the same regardless of where the real imports live:
        - obtain a lattice instance (singleton or constructed)
        - obtain an embed function (callable: str -> Sequence[float])
        - pass both to LatticeToolHandlers
    """
    from soveryn.agents.vett.harness.vendor.agent import Agent
    # === REPLACE FROM TASK 5 DISCOVERY NOTES ===
    # The two lines below are EXAMPLES. The discovery notes file captures
    # the actual import paths; substitute them here.
    from soveryn.memory.lattice import lattice as default_lattice  # EXAMPLE
    from soveryn.platform.inference.embed_client import embed_text  # EXAMPLE
    # ===========================================

    inference_model = SoverynVettInferenceModel(
        router_url=args.router_url,
        model_name=args.model,
    )
    tool_handlers = LatticeToolHandlers(
        lattice=default_lattice,
        embed_fn=embed_text,
    )
    return Agent(
        inference_model=inference_model,
        tool_handlers=tool_handlers,
    )


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)

    agent = _build_agent(args)
    trajectory = agent.run(task)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_dict = trajectory.model_dump() if hasattr(trajectory, "model_dump") else dict(trajectory)
    out_path.write_text(json.dumps(trajectory_dict, indent=2, default=str))
    print(f"wrote trajectory: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_vett_harness_run_eval.py::test_main_persists_trajectory_json_with_fake_harness -v`
Expected: PASS.

If the vendored `Agent` class signature differs from `Agent(inference_model=..., tool_handlers=...)`, inspect `vendor/agent.py` and adjust. Common variations: `Agent(model=..., toolset=...)` or `Agent(inference_model=..., toolset=...)`.

If `embed_text`'s import path doesn't exist, find the right entry point with:
```bash
grep -rn "def embed_text\|nomic-embed-text" soveryn/ | head -5
```

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/vett/harness/run_eval.py \
        tests/test_vett_harness_run_eval.py
git commit -m "feat(vett-harness): wire harness Agent + trajectory persistence into CLI runner"
```

---

### Task 9: Enforce the turn budget

**Files:**
- Modify: `soveryn/agents/vett/harness/run_eval.py`
- Test: `tests/test_vett_harness_run_eval.py` (extend)

The vendored harness may not respect an external turn cap. We wrap the Agent call to enforce one. The implementation: poll `trajectory.num_turns` after each Agent step (if the API exposes step-level execution) or set the harness's own `MAX_TURNS` constant if available.

- [ ] **Step 1: Read the vendored Agent to determine the turn-budget seam**

Read `soveryn/agents/vett/harness/vendor/agent.py` and identify:
- Does `Agent` have a `max_turns` constructor arg?
- Does it expose a per-step `step()` method, or only a monolithic `run()`?
- Is there a module-level constant like `MAX_TURNS = 40`?

The implementation in Step 3 below assumes a `max_turns` constructor arg. If the vendored Agent exposes a different seam, adjust accordingly:
- If `step()` is available: replace `agent.run(task)` with a manual loop bounded by `args.max_turns`.
- If only `MAX_TURNS` constant: monkeypatch it before calling `agent.run(task)`.

Document the chosen seam as a comment in `_build_agent`.

- [ ] **Step 2: Write the failing test asserting turn budget is forwarded**

Append to `tests/test_vett_harness_run_eval.py`:
```python
def test_main_passes_max_turns_to_agent(monkeypatch):
    """The --max-turns CLI flag reaches the harness Agent constructor."""
    captured = {}

    class _FakeTrajectory:
        def model_dump(self): return {"actions_and_observations": [], "id": "fake"}

    class _FakeAgent:
        def __init__(self, *args, max_turns=None, **kwargs):
            captured["max_turns"] = max_turns
        def run(self, task): return _FakeTrajectory()

    def _fake_build(args):
        return _FakeAgent(max_turns=args.max_turns)

    monkeypatch.setattr("soveryn.agents.vett.harness.run_eval._build_agent", _fake_build)

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        rc = run_eval.main(["--task", "smoke", "--output", str(out_path),
                             "--max-turns", "7"])
        assert rc == 0
        assert captured["max_turns"] == 7
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_run_eval.py::test_main_passes_max_turns_to_agent -v`
Expected: FAIL — `_build_agent` doesn't forward `max_turns` yet.

- [ ] **Step 4: Forward the turn budget in `_build_agent`**

Modify `_build_agent` in `soveryn/agents/vett/harness/run_eval.py`:
```python
def _build_agent(args: argparse.Namespace) -> Any:
    """Construct the vendored harness Agent wired with SOVERYN shims.

    Turn-budget seam: passing max_turns=args.max_turns to Agent's constructor.
    If the vendored Agent doesn't accept this kwarg, fall back to monkeypatching
    the module-level MAX_TURNS constant before agent.run().
    """
    from soveryn.agents.vett.harness.vendor.agent import Agent
    from soveryn.memory.lattice import lattice as default_lattice
    from soveryn.platform.inference.embed_client import embed_text

    inference_model = SoverynVettInferenceModel(
        router_url=args.router_url,
        model_name=args.model,
    )
    tool_handlers = LatticeToolHandlers(
        lattice=default_lattice,
        embed_fn=embed_text,
    )
    return Agent(
        inference_model=inference_model,
        tool_handlers=tool_handlers,
        max_turns=args.max_turns,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_vett_harness_run_eval.py::test_main_passes_max_turns_to_agent -v`
Expected: PASS.

If the vendored `Agent.__init__` doesn't accept `max_turns`, switch to the monkeypatch-MAX_TURNS fallback:
```python
def _build_agent(args: argparse.Namespace) -> Any:
    from soveryn.agents.vett.harness.vendor import agent as vendor_agent
    # ... build inference_model + tool_handlers ...
    vendor_agent.MAX_TURNS = args.max_turns  # documented seam, see Task 9
    return vendor_agent.Agent(inference_model=inference_model, tool_handlers=tool_handlers)
```
Update the test accordingly to assert the constant got set.

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/vett/harness/run_eval.py \
        tests/test_vett_harness_run_eval.py
git commit -m "feat(vett-harness): enforce CLI --max-turns through to vendored Agent"
```

---

### Task 10: Failure-mode telemetry to stderr

**Files:**
- Modify: `soveryn/agents/vett/harness/run_eval.py`
- Test: `tests/test_vett_harness_run_eval.py` (extend)

Phase 1's success criterion includes seeing *how* the harness fails when it fails. After the run completes, emit a structured telemetry block to stderr capturing: turn count, tool-call counts by tool name, whether the harness reached `stop`, evidence promotion count.

- [ ] **Step 1: Write the failing test asserting telemetry appears on stderr**

Append to `tests/test_vett_harness_run_eval.py`:
```python
def test_main_emits_telemetry_to_stderr(monkeypatch, capsys):
    """Telemetry block is written to stderr after the run."""

    class _FakeTrajectory:
        # Pretend the harness emitted 3 actions, one of each kind, and stopped.
        actions_and_observations = []
        @property
        def num_turns(self): return 3
        def model_dump(self): return {"actions_and_observations": [], "id": "fake"}

    class _FakeAgent:
        def __init__(self, *a, **kw): pass
        def run(self, task): return _FakeTrajectory()

    monkeypatch.setattr(
        "soveryn.agents.vett.harness.run_eval._build_agent",
        lambda args: _FakeAgent(),
    )
    # The telemetry helper needs to walk actions_and_observations; we test
    # the call site invokes it, not its full content (which Task 10 step 4
    # tests via direct call).
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        rc = run_eval.main(["--task", "smoke", "--output", str(out_path)])
        captured = capsys.readouterr()
        assert "[telemetry]" in captured.err
        assert "num_turns=3" in captured.err


def test_telemetry_counts_tool_calls_by_name():
    """Direct call: telemetry helper aggregates tool-call counts from a trajectory."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeAction:
        def __init__(self, tool_name, errored=False):
            self.tools = [type("T", (), {"name": tool_name})()]
            self.params = [{}]
            self.errored = errored

    class _FakeTraj:
        num_turns = 4
        actions_and_observations = [
            _FakeAction("search_corpus"),
            _FakeAction("search_corpus"),
            _FakeAction("read_doc"),
            _FakeAction("verify", errored=True),
        ]

    summary = emit_telemetry(
        _FakeTraj(),
        max_turns=20,
        reached_stop=True,
        evidence_promoted=2,
    )
    assert summary["num_turns"] == 4
    assert summary["tool_calls"]["search_corpus"] == 2
    assert summary["tool_calls"]["read_doc"] == 1
    assert summary["reached_stop"] is True
    assert summary["evidence_promoted"] == 2
    # Failure-mode diagnostics
    assert summary["turn_cap_hit"] is False        # 4 < 20
    assert summary["zero_promotion"] is False      # promoted_evidence == 2
    assert summary["tool_diversity_collapse"] is False  # 3 distinct tools
    assert summary["tool_error_count"] == 1        # one errored action


def test_telemetry_flags_turn_cap_hit():
    """turn_cap_hit fires when num_turns hits max_turns."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeTraj:
        num_turns = 20
        actions_and_observations = []

    summary = emit_telemetry(_FakeTraj(), max_turns=20, reached_stop=False, evidence_promoted=0)
    assert summary["turn_cap_hit"] is True
    assert summary["zero_promotion"] is True


def test_telemetry_flags_tool_diversity_collapse():
    """tool_diversity_collapse fires when one tool dominates >80% of calls."""
    from soveryn.agents.vett.harness.run_eval import emit_telemetry

    class _FakeAction:
        def __init__(self, tool_name):
            self.tools = [type("T", (), {"name": tool_name})()]
            self.params = [{}]
            self.errored = False

    class _FakeTraj:
        num_turns = 10
        # 9 search_corpus, 1 verify — search dominates 90%
        actions_and_observations = [_FakeAction("search_corpus")] * 9 + [_FakeAction("verify")]

    summary = emit_telemetry(_FakeTraj(), max_turns=20, reached_stop=True, evidence_promoted=1)
    assert summary["tool_diversity_collapse"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_vett_harness_run_eval.py::test_main_emits_telemetry_to_stderr tests/test_vett_harness_run_eval.py::test_telemetry_counts_tool_calls_by_name -v`
Expected: both FAIL — `emit_telemetry` not defined.

- [ ] **Step 3: Implement telemetry**

Append to `soveryn/agents/vett/harness/run_eval.py`:
```python
DOMINANT_TOOL_FRACTION_THRESHOLD = 0.8


def emit_telemetry(
    trajectory,
    *,
    max_turns: int,
    reached_stop: bool,
    evidence_promoted: int,
) -> dict:
    """Aggregate per-trajectory failure-mode telemetry.

    Returns the dict for testability. The CLI's main() also prints a
    one-line stderr summary.

    Failure-mode fields:
        - turn_cap_hit: ran out of turn budget without natural stop
        - zero_promotion: never promoted any evidence to the curated set
        - tool_diversity_collapse: one tool dominated >80% of calls
          (e.g., searched forever, never verified)
        - tool_error_count: count of actions where the tool errored
    """
    tool_call_counts: dict[str, int] = {}
    tool_error_count = 0
    for entry in getattr(trajectory, "actions_and_observations", []):
        for tool in getattr(entry, "tools", []) or []:
            name = getattr(tool, "name", "unknown")
            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
        if getattr(entry, "errored", False):
            tool_error_count += 1

    num_turns = getattr(trajectory, "num_turns", -1)
    total_calls = sum(tool_call_counts.values())
    tool_diversity_collapse = (
        total_calls > 0
        and max(tool_call_counts.values()) / total_calls > DOMINANT_TOOL_FRACTION_THRESHOLD
    )

    return {
        "num_turns": num_turns,
        "tool_calls": tool_call_counts,
        "reached_stop": reached_stop,
        "evidence_promoted": evidence_promoted,
        # Failure-mode diagnostics
        "turn_cap_hit": num_turns >= max_turns,
        "zero_promotion": evidence_promoted == 0,
        "tool_diversity_collapse": tool_diversity_collapse,
        "tool_error_count": tool_error_count,
    }
```

Modify `main()` to call `emit_telemetry` and print:
```python
def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    task = load_task(args.task)
    print(f"loaded task: {task.name}", file=sys.stderr)

    agent = _build_agent(args)
    trajectory = agent.run(task)

    # Failure-mode telemetry. The reached_stop / evidence_promoted fields
    # require introspection of the trajectory's terminal state; for phase 1
    # we use simple defaults that Task 12's eval task verification can refine.
    reached_stop = bool(getattr(trajectory, "stopped_by_tool", False))
    evidence_promoted = len(getattr(trajectory, "promoted_evidence_ids", []))
    summary = emit_telemetry(
        trajectory,
        max_turns=args.max_turns,
        reached_stop=reached_stop,
        evidence_promoted=evidence_promoted,
    )
    print(
        f"[telemetry] num_turns={summary['num_turns']} "
        f"tool_calls={summary['tool_calls']} reached_stop={summary['reached_stop']} "
        f"evidence_promoted={summary['evidence_promoted']} "
        f"turn_cap_hit={summary['turn_cap_hit']} "
        f"zero_promotion={summary['zero_promotion']} "
        f"tool_diversity_collapse={summary['tool_diversity_collapse']} "
        f"tool_error_count={summary['tool_error_count']}",
        file=sys.stderr,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    trajectory_dict = trajectory.model_dump() if hasattr(trajectory, "model_dump") else dict(trajectory)
    out_path.write_text(json.dumps(trajectory_dict, indent=2, default=str))
    print(f"wrote trajectory: {out_path}", file=sys.stderr)
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_vett_harness_run_eval.py -v`
Expected: all passing (4 + 2 = 6 tests in this file).

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/vett/harness/run_eval.py \
        tests/test_vett_harness_run_eval.py
git commit -m "feat(vett-harness): failure-mode telemetry on stderr after each run"
```

---

### Task 11: Define one SOVERYN-representative eval task

**Files:**
- Create: `soveryn/agents/vett/harness/eval_tasks/cross_source_link.py`
- Modify: `soveryn/agents/vett/harness/eval_tasks/__init__.py`
- Test: `tests/test_vett_harness_eval_tasks.py`

Phase 1 needs at least one task that's representative of SOVERYN's actual retrieval workload. The task is: "find every lattice node that mentions topic X, link the evidence, verify a specific claim against the linked evidence." Use a topic Vett-current has actually patrolled — pick from the patrol_sources data, not synthetic.

- [ ] **Step 1: Identify a real topic + claim from Vett's patrol history**

First, locate the live lattice DB (path varies between vnext versions and consolidations — do NOT assume a hardcoded path):
```bash
find ~/soveryn_vnext -type f -name "*.db" 2>/dev/null | head
```

Candidate paths in current vnext: `data/memory/*.db`, `data/lattice/*.db`. The Task 5 discovery notes should already have captured the canonical path — use that. If it's still unclear, inspect which file is most recently modified and which has node-shaped content:
```bash
ls -la $(find ~/soveryn_vnext -type f -name "*.db" 2>/dev/null)
```

Once located, sample the contents (replace `<LATTICE_DB>` with the path from above):
```bash
sqlite3 <LATTICE_DB> ".tables"
sqlite3 <LATTICE_DB> "SELECT id, substr(content, 1, 80) FROM nodes ORDER BY salience DESC LIMIT 10;"
```

If `nodes` isn't a table, list the actual tables and pick the one holding the lattice entries (likely `nodes`, `lattice_nodes`, or similar — Task 5 notes will say).

Pick a topic that appears in 3+ nodes (so there's cross-source linking to do). Capture the topic string and the expected node IDs for scoring.

- [ ] **Step 2: Write the failing test asserting the task is loadable + structured**

Create `tests/test_vett_harness_eval_tasks.py`:
```python
"""Eval task registry — phase 1 SOVERYN tasks."""
from __future__ import annotations
import pytest

from soveryn.agents.vett.harness.eval_tasks import get_task


def test_cross_source_link_task_is_registered():
    task = get_task("cross_source_link")
    assert task.name == "cross_source_link"
    assert "topic" in task.query.lower() or "claim" in task.query.lower()


def test_cross_source_link_task_has_expected_evidence_ids():
    """The task carries the canonical answer-set so the comparison run can score it."""
    task = get_task("cross_source_link")
    assert len(task.expected_evidence_ids) >= 3
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/test_vett_harness_eval_tasks.py -v`
Expected: FAIL with `KeyError: 'Unknown eval task: ...'`.

- [ ] **Step 4: Define the task module + register**

Create `soveryn/agents/vett/harness/eval_tasks/cross_source_link.py`:
```python
"""cross_source_link: a SOVERYN-representative phase-1 eval task.

The query asks Vett-in-harness to find nodes about a specific topic
across multiple lattice sources, link the evidence, and verify a claim.
The expected_evidence_ids are the node IDs Vett-current has previously
surfaced for this topic (curated by Jon during Task 11 step 1).

This task exercises:
    - fan_out_search (multiple framings of the topic)
    - read_doc (full-text inspection of candidates)
    - the verification primitive (does the claim survive the evidence?)
    - the curation primitive (which nodes deserve the curated set?)

Replace TOPIC, CLAIM, and EXPECTED_IDS with the actual values surfaced
in Task 11 step 1.
"""
from __future__ import annotations
from soveryn.agents.vett.harness.eval_tasks import EvalTask, register_task


# === FILL FROM TASK 10 STEP 1 ===
TOPIC = "<topic-string-from-step-1>"
CLAIM = "<one-sentence-claim-about-the-topic>"
EXPECTED_IDS = (
    "<node-id-1>",
    "<node-id-2>",
    "<node-id-3>",
)
# =================================


CROSS_SOURCE_LINK = EvalTask(
    name="cross_source_link",
    query=(
        f"Search the lattice for evidence about: {TOPIC}\n"
        f"Once you have candidate documents, verify this claim against them: {CLAIM}\n"
        "Curate the strongest evidence set, link the documents that mutually support the claim, "
        "and stop when you've reached a confident verification or determined the claim is unsupported."
    ),
    expected_evidence_ids=EXPECTED_IDS,
)


register_task(CROSS_SOURCE_LINK)
```

Modify `soveryn/agents/vett/harness/eval_tasks/__init__.py` to import the new task module so registration runs:
```python
"""SOVERYN eval-task registry.

Tasks are simple dataclasses with a name and a query. Phase 1 ships:
    - 'smoke': trivial loadability check
    - 'cross_source_link': real SOVERYN retrieval task
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EvalTask:
    name: str
    query: str
    expected_evidence_ids: tuple = ()


_REGISTRY: Dict[str, EvalTask] = {
    "smoke": EvalTask(
        name="smoke",
        query="reply with: SMOKE_OK",
    ),
}


def get_task(name: str) -> EvalTask:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown eval task: {name!r}. Registered: {list(_REGISTRY)}")
    return _REGISTRY[name]


def register_task(task: EvalTask) -> None:
    _REGISTRY[task.name] = task


# Trigger registration of phase-1 tasks
from soveryn.agents.vett.harness.eval_tasks import cross_source_link  # noqa: F401, E402
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_vett_harness_eval_tasks.py -v`
Expected: 2 passed.

If the placeholder TOPIC/CLAIM/EXPECTED_IDS were not replaced with real values, the second test will fail (`len(EXPECTED_IDS) >= 3`). Replace them before continuing.

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/vett/harness/eval_tasks/cross_source_link.py \
        soveryn/agents/vett/harness/eval_tasks/__init__.py \
        tests/test_vett_harness_eval_tasks.py
git commit -m "feat(vett-harness): cross_source_link eval task — real SOVERYN topic"
```

---

### Task 12: End-to-end integration smoke test

**Files:**
- Test: `tests/test_vett_harness_smoke.py` (extend)

Wire everything together against the live router + live lattice and confirm the CLI completes within bounds. This is an integration test, opt-in.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_vett_harness_smoke.py`:
```python
import subprocess
import sys
import tempfile
from pathlib import Path
import json

import pytest


@pytest.mark.integration
def test_end_to_end_smoke_task_against_live_services():
    """The CLI runs the 'smoke' task end-to-end and produces a valid trajectory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "trajectory.json"
        result = subprocess.run(
            [sys.executable, "-m", "soveryn.agents.vett.harness.run_eval",
             "--task", "smoke", "--output", str(out_path),
             "--max-turns", "3"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert "actions_and_observations" in data
        assert "[telemetry]" in result.stderr
```

- [ ] **Step 2: Run it**

Run: `pytest tests/test_vett_harness_smoke.py::test_end_to_end_smoke_task_against_live_services -v --run-integration`
Expected: PASS within 120 seconds.

If it hangs: harness may not respect the `--max-turns` flag. Verify the seam chosen in Task 9 is actually enforced (Agent constructor took it OR MAX_TURNS constant was set). Tighten if needed.

If it fails for some other reason: check the trajectory.json to see where Vett got stuck.

- [ ] **Step 3: Commit**

```bash
git add tests/test_vett_harness_smoke.py
git commit -m "test(vett-harness): end-to-end smoke against live router + lattice"
```

---

### Task 13: Comparison run + writeup

**Files:**
- Create: `docs/notes/2026-06-XX-vett-harness-eval.md` (date set at run time)
- Optional: `scripts/vett_compare.py` for repeatability

This task produces the phase 1 deliverable: a measurement of Vett-in-harness vs Vett-current on `cross_source_link`, with the result deciding whether phase 2 is justified.

- [ ] **Step 1: Run Vett-in-harness on the eval task**

```bash
mkdir -p ~/soveryn_vnext/eval_runs
python -m soveryn.agents.vett.harness.run_eval \
    --task cross_source_link \
    --output ~/soveryn_vnext/eval_runs/$(date +%Y%m%d_%H%M%S)_harness.json \
    --max-turns 20 \
    2> ~/soveryn_vnext/eval_runs/$(date +%Y%m%d_%H%M%S)_harness.stderr
```

Note the trajectory JSON path + stderr telemetry block.

- [ ] **Step 2: Run Vett-current on the same task**

Use Vett's existing chat-completions path against the same query:
```bash
SID=$(curl -s -X POST http://127.0.0.1:5001/sessions \
    -H 'Content-Type: application/json' \
    -d '{"agent":"vett","title":"[harness-eval-baseline]"}' | jq -r .session_id)

# Pull the cross_source_link.py query string
QUERY=$(python -c "from soveryn.agents.vett.harness.eval_tasks import get_task; print(get_task('cross_source_link').query)")

time curl -s -X POST http://127.0.0.1:5001/chat \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg q "$QUERY" --arg sid "$SID" '{agent:"vett", session_id:$sid, message:$q}')" \
    > ~/soveryn_vnext/eval_runs/$(date +%Y%m%d_%H%M%S)_baseline.json
```

- [ ] **Step 3: Score both runs against the expected_evidence_ids**

Open both JSON files. For each:
- Did the run mention each expected_evidence_id?
- Was the verification verdict correct?
- Wall-time, turn count (harness only), tool-call breakdown

Capture in a comparison table.

- [ ] **Step 4: Write the eval report**

Create `docs/notes/<YYYY-MM-DD>-vett-harness-eval.md` (use the date the eval ran):
```markdown
# Vett Harness Port — Phase 1 Eval Results (YYYY-MM-DD)

**Task:** cross_source_link
**Topic:** [insert from cross_source_link.py]
**Expected evidence IDs:** [list]

## Vett-in-harness

- Wall-time: [s]
- Turn count: [n]
- Tool-call breakdown: [from stderr telemetry]
- Reached stop: [bool]
- Evidence promoted: [n]
- Coverage of expected IDs: [m / 3]
- Verification correct: [yes/no]

## Vett-current (baseline)

- Wall-time: [s]
- Coverage of expected IDs: [m / 3]
- Verification correct: [yes/no]

## Verdict against phase 1 success bar

[Match Vett-current with cleaner evidence state = pass; beat = home run; worse = fail]

## Failure modes observed

[From telemetry — did Vett never verify? Get stuck in fan_out_search loop? etc.]

## Recommendation

[Proceed to phase 2 / iterate on prompts/tools / write phase 1 off]
```

- [ ] **Step 5: Commit the report + the trajectory JSON snapshots**

```bash
git add docs/notes/<YYYY-MM-DD>-vett-harness-eval.md \
        eval_runs/*.json eval_runs/*.stderr
git commit -m "eval(vett-harness): phase 1 cross_source_link results — [pass|home-run|fail]"
```

- [ ] **Step 6: Open the PR back to main**

```bash
git push -u origin vett-harness-phase1
gh pr create --title "vett-harness: phase 1 — eval-only port of Harness-1" \
    --body "$(cat <<'EOF'
## Summary

Phase 1 port of the Harness-1 retrieval orchestration pattern onto Vett's
existing model + SOVERYN's lattice. CLI-only; no Vett product wiring.

Spec: docs/superpowers/specs/2026-06-11-vett-harness-port-design.md
Plan: docs/superpowers/plans/2026-06-11-vett-harness-port-phase1.md

## What's in this PR

- Vendored upstream harness/ under soveryn/agents/vett/harness/vendor/
- SoverynVettInferenceModel (chat-completions, points at :8090)
- Lattice tool handlers (read-through)
- Standalone CLI runner with turn budget, trajectory JSON, telemetry
- One real SOVERYN eval task (cross_source_link)
- Comparison run report: docs/notes/<DATE>-vett-harness-eval.md

## Test plan

- [x] All unit tests pass: `pytest tests/test_vett_harness_*.py -v`
- [x] All integration tests pass: `pytest tests/test_vett_harness_*.py -v --run-integration`
- [x] CLI smoke runs end-to-end in <120s
- [x] cross_source_link eval completes within --max-turns=20
- [x] Report committed under docs/notes/

## Phase 2 decision

See report's "Recommendation" section.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Return the PR URL.

---

## Self-Review

**1. Spec coverage check.** Walking the spec:

| Spec requirement | Plan task |
|---|---|
| Vendor harness/ to `vendor/` with Apache 2.0 + NOTICE | Task 1 (LICENSE/NOTICE), Task 2 (vendor) |
| Format-compat blocker check | Task 3 |
| LLM client config patch | Task 4 |
| Lattice + embed entrypoint discovery (blocker) | Task 5 |
| Lattice adapter (read-through) | Task 6 (lattice tool handlers — different seam than spec's "adapter" framing, see plan preamble) |
| Standalone CLI runner | Tasks 7, 8 |
| Bounded turn budget (start at 20) | Task 9 |
| Failure-mode telemetry (turn_cap_hit, zero_promotion, tool_diversity_collapse, tool_error_count) | Task 10 |
| SOVERYN-representative eval task | Task 11 |
| Smoke test (end-to-end) | Task 12 |
| Trajectory JSON persistence | Task 8 |
| Comparison run + writeup | Task 13 |
| NOT modify vett/research_surface.py, patrol/, loop.py, etc. | Not in any "Modify" list |
| NOT track BrowseComp+ | Not in any task |
| NOT integrate patrol daemon | Not in any task |
| NOT modify Aetheria's path | Not in any task |
| NOT modify router preset | Not in any task |
| NO write-back to lattice | Lattice tool handlers (Task 6) are read-only |

All requirements covered.

**2. Placeholder scan.**

- "TBD" / "TODO" / "fill in later": Only at Task 11 step 4 (`TOPIC = "<topic-string-from-step-1>"`) and in Task 8's `_build_agent` (lattice/embed import paths flagged as `# EXAMPLE` requiring substitution from Task 5 discovery notes). Both are **intentional** — values cannot be filled until live-codebase discovery (Task 5) or live-lattice sampling (Task 11 step 1). The plan explicitly directs the engineer to fill them before committing.
- "Add appropriate error handling": None.
- "Write tests for the above": None.
- "Similar to Task N": None.
- Steps describing what to do without code: None — every implementation step shows code.

**3. Type consistency.**

- `EvalTask` defined in Task 7 with fields `name`, `query`, `expected_evidence_ids`. Used in Tasks 8, 11, 13 with same fields. ✓
- `SoverynVettInferenceModel` constructor signature `(router_url, model_name, ...)` in Task 4 used identically in Task 8. ✓
- `LatticeToolHandlers` constructor `(lattice, embed_fn)` in Task 6 used identically in Task 8. ✓
- `emit_telemetry(trajectory, *, max_turns, reached_stop, evidence_promoted) -> dict` in Task 10 — tests assert dict-keyed return with the failure-mode fields (`turn_cap_hit`, `zero_promotion`, `tool_diversity_collapse`, `tool_error_count`). Signature includes `max_turns` so it can compute `turn_cap_hit` correctly. ✓

No drift detected.
