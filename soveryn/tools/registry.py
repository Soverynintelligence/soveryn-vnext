"""SOVERYN vNext — tool registry.

Declarative registration of tool implementations keyed by name and owning
agent. Validates that tool owners are in ACTIVE_AGENTS (no retired agent can
own a tool). Dispatches tool execution calls from AgentLoop. Replaces the
scattered app.py agent_loops[x].tools.register(...) pattern with a single
declarative source (spec §14).
Placeholder; implementation comes in a later vNext step.
"""
