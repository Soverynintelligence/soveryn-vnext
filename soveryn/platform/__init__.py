"""Platform mechanisms for SOVERYN vNext.

The platform layer owns shared mechanisms: memory access, tool execution,
inference routing, event delivery, supervision, telemetry, and repair grammar.
Agent packages own policy and should call these interfaces rather than reaching
around them to raw files, model endpoints, or process controls.
"""

