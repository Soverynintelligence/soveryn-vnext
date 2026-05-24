"""SOVERYN vNext — agent-to-server routing.

Pure lookup table over soveryn.config.runtime.AGENT_TO_SERVER + MODEL_SERVERS.
No I/O. Failure modes are typed.

The point of having routing in a dedicated module: tests can verify that
an unknown or retired agent name is rejected BEFORE any HTTP client tries
to contact a server. Routing is the trust boundary.
"""

from __future__ import annotations

from soveryn.config.runtime import (
    AGENT_TO_SERVER,
    MODEL_SERVERS,
    RETIRED,
    ModelServer,
)


class RoutingError(LookupError):
    """Raised when an agent has no valid model-server route."""


def route_for_agent(agent_name: str) -> ModelServer:
    """Return the ModelServer that handles requests for `agent_name`.

    Fails loud (RoutingError) on:
      - retired names (caught at the routing boundary before any network call)
      - unknown names (not in AGENT_TO_SERVER)
      - misconfiguration where AGENT_TO_SERVER points to a server name not
        in MODEL_SERVERS (should already be caught by runtime._validate)
    """
    name = agent_name.lower().strip()
    if name in RETIRED:
        raise RoutingError(
            f"Cannot route for retired agent {name!r} (spec §10 Bucket C)"
        )
    if name not in AGENT_TO_SERVER:
        raise RoutingError(
            f"No route for agent {name!r}: not in AGENT_TO_SERVER "
            f"({sorted(AGENT_TO_SERVER)})"
        )
    target_server_name = AGENT_TO_SERVER[name]
    for server in MODEL_SERVERS:
        if server.name == target_server_name:
            return server
    raise RoutingError(
        f"Routing table corruption: agent {name!r} → {target_server_name!r} "
        f"but no MODEL_SERVERS entry has that name"
    )
