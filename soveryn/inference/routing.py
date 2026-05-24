"""SOVERYN vNext — inference routing.

Maps an agent name to the correct ModelServer via AGENT_TO_SERVER from
soveryn.config.runtime. Returns the appropriate llama_server_client instance.
Raises immediately (not silently) if the agent has no route or the target
server is unreachable. Placeholder; implementation comes in a later vNext step.
"""
