"""Deprecated — use soveryn.platform.acttruth.hooks."""
from soveryn.platform.acttruth.hooks import (  # noqa: F401
    acttruth_and_telemetry_audit_hook as continuum_and_telemetry_audit_hook,
    get_acttruth as get_continuum,
    record_tool_audit,
    reset_acttruth_cache as reset_continuum_cache,
)
