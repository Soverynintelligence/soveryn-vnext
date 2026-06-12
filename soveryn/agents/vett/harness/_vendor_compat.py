"""Runtime compatibility shim for the vendored Harness-1 upstream.

This file is SOVERYN-side; it is NOT part of upstream pat-jj/harness-1.

Three compatibility issues are addressed at import time, BEFORE any
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

3. **`datagen` stub.** Upstream's `agent.py` also imports from a sibling
   `datagen` package at module top (`from datagen.search_dataset import
   SearchDataset, get_dataset`). SOVERYN does not vendor upstream's
   training-time dataset registry in phase 1 (eval-only against the
   Synapse lattice, not against BrowseCompPlus / upstream training
   datasets). Same pattern as the `tinker` stub: imports succeed,
   instantiation/use raises a clear RuntimeError.

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

_DATAGEN_FAILURE_MSG = (
    "Upstream `datagen` package is not vendored in the SOVERYN Harness-1 "
    "phase 1 port (eval-only against the Synapse lattice, no upstream "
    "training datasets). See "
    "docs/superpowers/specs/2026-06-11-vett-harness-port-design.md."
)


def _make_failing_class(name: str, failure_msg: str = _TINKER_FAILURE_MSG) -> type:
    """Build a stub class that raises on instantiation with a clear message."""
    def _init(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"{name}: {failure_msg}")

    def _classmethod_call(cls: Any, *args: Any, **kwargs: Any) -> None:
        # Catches classmethod-style invocations like
        # `tinker.types.ModelInput.from_ints(tokens=...)`. We register a
        # __getattr__ on the class below so any unknown attribute returns
        # this callable.
        raise RuntimeError(f"{name}: {failure_msg}")

    def _class_getattr(cls: Any, item: str) -> Any:
        # Returning a callable that raises lets any classmethod-style
        # access (e.g. `Cls.from_ints(...)`) load without error but fail
        # immediately on call. We deliberately do NOT return a value
        # silently — RuntimeError on use is the entire point of the stub.
        return _classmethod_call.__get__(cls, type(cls))

    # type.__getattr__ is consulted on the metaclass, not the class itself,
    # so we install via a custom metaclass.
    meta = type(
        f"{name}_Meta",
        (type,),
        {"__getattr__": lambda cls, item: _class_getattr(cls, item)},
    )
    return meta(name, (), {"__init__": _init})


def _build_tinker_types_submodule() -> types.ModuleType:
    """Build `tinker.types` as a submodule with its own fail-closed stubs.

    Upstream's vendored agent.py references `tinker.types.SamplingParams`,
    `tinker.types.ModelInput`, and `tinker.types.SampleResponse` — some
    in class-body annotations (evaluated at module load, since vendor
    agent.py does NOT use `from __future__ import annotations`). We
    therefore need `tinker.types` to be a *module-like* object that
    resolves those attributes, not a flat failing class.
    """
    sub = types.ModuleType("tinker.types")
    for cls_name in ("SamplingParams", "ModelInput", "SampleResponse"):
        setattr(sub, cls_name, _make_failing_class(cls_name))

    def _dynamic_attr(name: str) -> Any:
        # Any other `tinker.types.X` becomes a failing class on demand.
        return _make_failing_class(name)

    sub.__getattr__ = _dynamic_attr  # type: ignore[attr-defined]
    return sub


def _build_tinker_stub_module() -> types.ModuleType:
    """Construct a fail-closed stub module that satisfies upstream's imports.

    The symbol set here MUST cover every name upstream's vendored agent.py
    and config.py import from tinker. Inspect those files (Task 2 Step 5)
    and add any missing names to this list before depending on the stub.
    """
    stub = types.ModuleType("tinker")
    # Known classes upstream uses at module-load time (per Task 2 Step 5):
    #   config.py:   tinker.ServiceClient (function body — runtime)
    #   agent.py:    tinker.SamplingClient (class annotation — module-load)
    #   agent.py:    tinker.types.SamplingParams (class annotation — module-load)
    for cls_name in ("SamplingClient", "ServiceClient", "TrainingClient"):
        setattr(stub, cls_name, _make_failing_class(cls_name))

    # `tinker.types` must be a module-like object — see note in
    # _build_tinker_types_submodule.
    types_sub = _build_tinker_types_submodule()
    stub.types = types_sub  # type: ignore[attr-defined]
    # Also register as a real submodule so `import tinker.types` would work.
    sys.modules["tinker.types"] = types_sub

    def _dynamic_attr(name: str) -> Any:
        # Fallback for any `from tinker import X` we did not enumerate.
        return _make_failing_class(name)

    stub.__getattr__ = _dynamic_attr  # type: ignore[attr-defined]
    return stub


def _build_datagen_stub_module() -> types.ModuleType:
    """Build the fail-closed `datagen` stub + its `search_dataset` submodule.

    Upstream's vendored `agent.py` does:
        from datagen.search_dataset import SearchDataset, get_dataset
    at module top. We need `datagen.search_dataset` to be importable and to
    expose `SearchDataset` (class) and `get_dataset` (callable). Both fail
    closed when actually used; phase 1 does not call into them.
    """
    pkg = types.ModuleType("datagen")
    sub = types.ModuleType("datagen.search_dataset")

    sub.SearchDataset = _make_failing_class(  # type: ignore[attr-defined]
        "SearchDataset", _DATAGEN_FAILURE_MSG
    )

    def _get_dataset_stub(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"get_dataset: {_DATAGEN_FAILURE_MSG}")

    sub.get_dataset = _get_dataset_stub  # type: ignore[attr-defined]
    sub.DATASET_REGISTRY = {}  # type: ignore[attr-defined]

    def _dynamic_attr(name: str) -> Any:
        return _make_failing_class(name, _DATAGEN_FAILURE_MSG)

    sub.__getattr__ = _dynamic_attr  # type: ignore[attr-defined]

    pkg.search_dataset = sub  # type: ignore[attr-defined]
    pkg.__getattr__ = _dynamic_attr  # type: ignore[attr-defined]

    sys.modules["datagen.search_dataset"] = sub
    return pkg


def install_vendor_compat() -> None:
    """Install harness alias and tinker/datagen stubs in sys.modules.

    Idempotent: safe to call multiple times. Must be called BEFORE any
    `soveryn.agents.vett.harness.vendor.*` module is imported.
    """
    # 1. tinker / datagen stubs MUST be installed before any vendor module
    #    is imported below — vendor/agent.py imports `tinker` at module-load.
    if "tinker" not in sys.modules:
        sys.modules["tinker"] = _build_tinker_stub_module()
    if "datagen" not in sys.modules:
        sys.modules["datagen"] = _build_datagen_stub_module()

    # 2. harness alias → our vendored package.
    if "harness" not in sys.modules:
        from soveryn.agents.vett.harness import vendor as _vendor_pkg
        sys.modules["harness"] = _vendor_pkg

    # 3. Pre-bind each vendor submodule under its `harness.<name>` alias so
    #    a subsequent `from harness.trajectory import Observation` resolves
    #    to the SAME module object as
    #    `from soveryn.agents.vett.harness.vendor.trajectory import Observation`.
    #
    #    Without this, the first `from harness.trajectory import X` (from
    #    inside vendored code, e.g. agent.py:47) causes Python's import
    #    machinery to re-import trajectory.py and register a second copy
    #    under `sys.modules["harness.trajectory"]`. That second copy
    #    defines a separate `Observation` class — `isinstance` checks in
    #    agent.py / trajectory.py then fail against `Observation` instances
    #    constructed from the `soveryn.agents.vett.harness.vendor.*` path
    #    (e.g. in run_eval.py's `_build_initial_observation`).
    #
    #    Order matters: bind leaf modules (no inter-vendor deps) first so
    #    that when a higher-level module like `agent.py` imports
    #    `from harness.trajectory import X`, the alias already points at
    #    the canonical vendor module.
    import importlib
    for _name in (
        "utils",       # no harness.* deps
        "rerank",      # deps: config
        "config",      # no harness.* deps
        "tools",       # deps: utils, rerank
        "trajectory",  # deps: utils, tools
        "prompts",     # no harness.* deps (verify)
        "tasks",       # deps: tools, trajectory
        "ultra_core",  # deps: tools, trajectory
        "agent",       # deps: most of the above
    ):
        _vendor_full = f"soveryn.agents.vett.harness.vendor.{_name}"
        _alias = f"harness.{_name}"
        if (_alias in sys.modules and _vendor_full in sys.modules
                and sys.modules[_alias] is sys.modules[_vendor_full]):
            continue
        try:
            _mod = importlib.import_module(_vendor_full)
        except Exception:
            # If a vendor module fails to import here, propagate at use
            # time rather than masking — but don't break the rest of the
            # alias install.
            continue
        sys.modules[_alias] = _mod
