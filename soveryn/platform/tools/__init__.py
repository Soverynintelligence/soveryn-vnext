"""Tool registration and mediated execution boundary.

Tools become capabilities only when registered through the platform. Agents
should not import implementation modules directly to bypass schema validation,
permission checks, or audit hooks.
"""

