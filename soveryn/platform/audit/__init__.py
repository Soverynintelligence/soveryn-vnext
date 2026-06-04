"""Self-audit tool surface.

Lets an agent query the audit log for its own recent actions. Closes
the introspection gap surfaced 2026-06-03: agents can't see intermediate
tool calls in their conversation history (AgentLoop.save_turn only
persists user/assistant content), so they confabulate absence of
actions they actually took. The audit log is ground truth; this tool
gives them direct access to it.
"""

from soveryn.platform.audit.tools import (
    build_recent_self_audit_tool,
    register_audit_tools,
)


__all__ = [
    "build_recent_self_audit_tool",
    "register_audit_tools",
]
